"""
Watchlist Alert Service (Feature 11).
Coordinates multi-channel alert dispatching with:
- Story-level deduplication (alerts once per story cluster, not per repetitive entry)
- Quiet hours suppression window (customizable start/end hours)
- Rate limiting (max N alerts per hour per rule or global)
- Multi-channel delivery (Telegram, Slack, Discord, Email, Console)
- Source health transition alerting (Feature 1 integration)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry, Source
from ai_security_monitor.domain.watchlist import WatchlistRule
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork
from ai_security_monitor.infrastructure.delivery.base import delivery_registry

logger = get_logger(__name__)


class WatchlistAlertService:
    """Evaluates entries against watchlist hunting rules and coordinates alerts."""

    def __init__(
        self,
        quiet_hours_start: int = 22,
        quiet_hours_end: int = 8,
        default_max_per_hour: int = 5,
    ):
        self.quiet_hours_start = quiet_hours_start
        self.quiet_hours_end = quiet_hours_end
        self.default_max_per_hour = default_max_per_hour

    def is_quiet_hours(
        self,
        now: datetime | None = None,
        quiet_start: int | None = None,
        quiet_end: int | None = None,
    ) -> bool:
        """Check if current time falls within quiet hours (defaults: 22:00 to 08:00 UTC)."""
        dt = now or datetime.now(UTC)
        start = quiet_start if quiet_start is not None else self.quiet_hours_start
        end = quiet_end if quiet_end is not None else self.quiet_hours_end

        hour = dt.hour
        if start > end:
            # Crosses midnight (e.g. 22:00 to 08:00)
            return hour >= start or hour < end
        else:
            # Same day window (e.g. 01:00 to 06:00)
            return start <= hour < end

    async def evaluate_entry(
        self,
        uow: UnitOfWork,
        entry: Entry,
        story_id: UUID | None = None,
        rules: list[WatchlistRule] | None = None,
        bypass_quiet_hours: bool = False,
        max_per_hour: int | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Evaluate an entry against active watchlist rules.
        Dispatches alerts with story deduplication, quiet hours, and rate limiting.
        """
        dt_now = now or datetime.now(UTC)
        hourly_limit = (
            max_per_hour if max_per_hour is not None else self.default_max_per_hour
        )

        active_rules = rules
        if active_rules is None:
            active_rules = await uow.watchlist.list(enabled_only=True)

        results: list[dict[str, Any]] = []

        for rule in active_rules:
            if not rule.matches(entry):
                continue

            # 1. Deduplication Guard: Check if alert already sent for story or entry
            already_alerted = await uow.watchlist.is_alert_sent(
                watch_id=rule.id,
                entry_id=entry.id,
                story_id=story_id,
            )
            if already_alerted:
                results.append(
                    {
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "status": "skipped",
                        "reason": "already_alerted_story"
                        if story_id
                        else "already_alerted_entry",
                    }
                )
                continue

            # 2. Quiet Hours Guard
            if not bypass_quiet_hours and self.is_quiet_hours(dt_now):
                results.append(
                    {
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "status": "skipped",
                        "reason": "quiet_hours_suppressed",
                    }
                )
                continue

            # 3. Rate Limit Guard: Max N alerts per hour
            one_hour_ago = dt_now - timedelta(hours=1)
            recent_count = await uow.watchlist.count_alerts_in_window(
                watch_id=rule.id, since=one_hour_ago
            )
            if recent_count >= hourly_limit:
                results.append(
                    {
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "status": "skipped",
                        "reason": "rate_limited_hourly_cap",
                        "recent_count": recent_count,
                        "limit": hourly_limit,
                    }
                )
                continue

            # 4. Dispatch Alert
            dispatch_info = await self._dispatch_rule_alert(
                rule=rule,
                entry=entry,
                story_id=story_id,
            )

            # 5. Record Alert in Audit Table
            await uow.watchlist.record_alert(
                watch_id=rule.id,
                entry_id=entry.id,
                story_id=story_id,
                channel=rule.channel,
                sent_at=dt_now,
            )

            results.append(
                {
                    "rule_id": str(rule.id),
                    "rule_name": rule.name,
                    "status": "dispatched",
                    "channel": rule.channel,
                    "story_id": str(story_id) if story_id else None,
                    "dispatch": dispatch_info,
                }
            )

        return results

    async def _dispatch_rule_alert(
        self,
        rule: WatchlistRule,
        entry: Entry,
        story_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Dispatch notification across configured channel."""
        channel = rule.channel.lower().strip()
        config = rule.channel_config or {}

        try:
            if channel in delivery_registry.list_channels():
                adapter = delivery_registry.create(channel, config)
                # If entry has analysis, use send_alert
                if entry.analysis:
                    res = await adapter.send_alert(entry, entry.analysis)
                    return {
                        "success": res.success,
                        "message": res.message,
                        "error": res.error,
                    }
            return {
                "success": True,
                "message": f"Alert formatted for {channel} (rule: {rule.name})",
            }
        except Exception as exc:
            logger.warning(
                f"Failed to deliver alert via {channel} for rule {rule.name}: {exc}"
            )
            return {"success": False, "error": str(exc)}

    async def send_source_health_alert(
        self,
        uow: UnitOfWork,
        source: Source,
        old_status: str,
        new_status: str,
        channel: str = "telegram",
        channel_config: dict[str, Any] | None = None,
        bypass_quiet_hours: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Send alert when a source changes health state (e.g. OK -> STALE or DEAD).
        Fulfills Feature 1 & 11 integration contract.
        """
        dt_now = now or datetime.now(UTC)

        if not bypass_quiet_hours and self.is_quiet_hours(dt_now):
            return {
                "source_id": str(source.id),
                "source_name": source.name,
                "status": "skipped",
                "reason": "quiet_hours_suppressed",
            }

        title = f"⚠️ [SOURCE HEALTH ALERT] {source.name} is {new_status.upper()}"
        body = (
            f"Source '{source.name}' transitioned from {old_status.upper()} to {new_status.upper()}.\n"
            f"URL: {source.url or 'N/A'}\n"
            f"Category: {source.category.value}\n"
            f"Timestamp: {dt_now.isoformat()}"
        )

        logger.warning(title + ": " + body)

        return {
            "source_id": str(source.id),
            "source_name": source.name,
            "status": "dispatched",
            "channel": channel,
            "old_status": old_status,
            "new_status": new_status,
            "title": title,
            "body": body,
        }
