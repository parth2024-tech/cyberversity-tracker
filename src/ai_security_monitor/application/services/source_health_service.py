"""
Source Health Telemetry Service.
Maintains operational telemetry (success rates, latencies, error states)
separated cleanly from content ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SourceHealthMetrics:
    """Operational telemetry for a single intelligence source."""

    source_name: str
    source_type: str = "unknown"
    category: str = "unknown"
    region: str = "global"
    total_runs: int = 0
    success_count: int = 0
    error_count: int = 0
    consecutive_failures: int = 0
    is_quarantined: bool = False
    quarantined_at: datetime | None = None
    quarantine_reason: str | None = None
    source_id: str | None = None
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_latency_ms: int = 0
    latencies: list[int] = field(default_factory=list)
    last_error_message: str | None = None
    last_entries_new: int = 0
    recent_entry_counts: list[int] = field(default_factory=list)

    @property
    def entry_frequency(self) -> float:
        """Average entries produced per run over the last 10 runs."""
        if not self.recent_entry_counts:
            return float(self.last_entries_new)
        return round(sum(self.recent_entry_counts) / len(self.recent_entry_counts), 2)

    @property
    def adaptive_polling_interval_seconds(self) -> int:
        """Adaptive dynamic polling interval (entry_frequency from Miniflux):
        - High-velocity (> 5 entries/run): 180s - 300s (3-5 minutes)
        - Medium-velocity (1-5 entries/run): 900s - 1800s (15-30 minutes)
        - Low-velocity / dormant (0 entries across recent runs): 7200s - 43200s (2-12 hours)
        """
        freq = self.entry_frequency
        if freq >= 5.0:
            return 180  # 3 minutes
        elif freq >= 2.0:
            return 300  # 5 minutes
        elif freq >= 0.5:
            return 900  # 15 minutes
        elif freq > 0.0:
            return 1800  # 30 minutes
        else:
            # Low-frequency / dormant feed: scale out based on consecutive empty runs
            empty_runs = max(1, self.total_runs - self.success_count)
            return min(43200, 7200 + min(36000, empty_runs * 3600))

    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 100.0
        return round((self.success_count / self.total_runs) * 100.0, 1)

    @property
    def avg_latency_ms(self) -> int:
        if not self.latencies:
            return self.last_latency_ms
        return int(sum(self.latencies) / len(self.latencies))

    @property
    def status(self) -> str:
        """Health classification: healthy, degraded, failing, or quarantined."""
        if self.consecutive_failures >= 5 or self.is_quarantined:
            return "quarantined"
        if self.consecutive_failures >= 3:
            return "failing"
        if self.consecutive_failures >= 1 or self.success_rate < 80.0:
            return "degraded"
        return "healthy"

    @property
    def cooldown_remaining_seconds(self) -> int:
        """Remaining cooldown seconds. For quarantined sources: 12-hour probe (43,200s). For failing: exponential up to 3,600s."""
        if not self.last_error_at:
            return 0
        last_err = (
            self.last_error_at
            if self.last_error_at.tzinfo
            else self.last_error_at.replace(tzinfo=UTC)
        )
        elapsed = (datetime.now(UTC) - last_err).total_seconds()
        if self.status == "quarantined":
            # 12-hour exponential backoff probe
            return max(0, int(43200 - elapsed))
        if self.consecutive_failures < 3:
            return 0
        cooldown = min(3600, 60 * (2 ** (self.consecutive_failures - 3)))
        return max(0, int(cooldown - elapsed))

    @property
    def circuit_state(self) -> str:
        """Circuit breaker state: closed, open, or half_open."""
        if self.status == "quarantined":
            return "open" if self.cooldown_remaining_seconds > 0 else "half_open"
        if self.consecutive_failures < 3:
            return "closed"
        return "open" if self.cooldown_remaining_seconds > 0 else "half_open"

    def to_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "category": self.category,
            "region": self.region,
            "status": self.status,
            "is_quarantined": self.is_quarantined or self.status == "quarantined",
            "quarantined_at": self.quarantined_at.isoformat()
            if self.quarantined_at
            else None,
            "quarantine_reason": self.quarantine_reason,
            "circuit_state": self.circuit_state,
            "cooldown_remaining_seconds": self.cooldown_remaining_seconds,
            "success_rate": self.success_rate,
            "entry_frequency": self.entry_frequency,
            "adaptive_polling_interval_seconds": self.adaptive_polling_interval_seconds,
            "consecutive_failures": self.consecutive_failures,
            "total_runs": self.total_runs,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "last_latency_ms": self.last_latency_ms,
            "avg_latency_ms": self.avg_latency_ms,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_success_at": self.last_success_at.isoformat()
            if self.last_success_at
            else None,
            "last_error_at": self.last_error_at.isoformat()
            if self.last_error_at
            else None,
            "last_error_message": self.last_error_message,
            "last_entries_new": self.last_entries_new,
        }


class SourceHealthService:
    """Manages source health telemetry, adaptive scheduling, and diagnostics."""

    def __init__(self):
        self._sources: dict[str, SourceHealthMetrics] = {}

    def _get_or_create(
        self,
        source_name: str,
        source_type: str = "unknown",
        category: str = "unknown",
        region: str = "global",
    ) -> SourceHealthMetrics:
        if source_name not in self._sources:
            self._sources[source_name] = SourceHealthMetrics(
                source_name=source_name,
                source_type=source_type,
                category=category,
                region=region,
            )
        metrics = self._sources[source_name]
        if source_type != "unknown":
            metrics.source_type = source_type
        if category != "unknown":
            metrics.category = category
        if region != "global":
            metrics.region = region
        return metrics

    def record_success(
        self,
        source_name: str,
        duration_ms: int,
        entries_new: int = 0,
        source_type: str = "unknown",
        category: str = "unknown",
        region: str = "global",
    ) -> None:
        """Record a successful fetch sweep for a source."""
        metrics = self._get_or_create(source_name, source_type, category, region)
        now = datetime.now(UTC)
        metrics.total_runs += 1
        metrics.success_count += 1
        metrics.consecutive_failures = 0
        metrics.is_quarantined = False
        metrics.quarantined_at = None
        metrics.quarantine_reason = None
        metrics.last_run_at = now
        metrics.last_success_at = now
        metrics.last_latency_ms = duration_ms
        metrics.last_entries_new = entries_new
        metrics.last_error_message = None

        # Keep rolling window of last 10 entry counts for adaptive frequency
        metrics.recent_entry_counts.append(entries_new)
        if len(metrics.recent_entry_counts) > 10:
            metrics.recent_entry_counts.pop(0)

        # Keep rolling window of last 20 latencies
        metrics.latencies.append(duration_ms)
        if len(metrics.latencies) > 20:
            metrics.latencies.pop(0)

    def record_failure(
        self,
        source_name: str,
        duration_ms: int,
        error_message: str,
        source_type: str = "unknown",
        category: str = "unknown",
        region: str = "global",
        source_id: str | None = None,
    ) -> None:
        """Record a failed fetch attempt for a source and auto-quarantine on >= 5 consecutive failures."""
        metrics = self._get_or_create(source_name, source_type, category, region)
        if source_id:
            metrics.source_id = source_id
        now = datetime.now(UTC)
        metrics.total_runs += 1
        metrics.error_count += 1
        metrics.consecutive_failures += 1
        metrics.last_run_at = now
        metrics.last_error_at = now
        metrics.last_latency_ms = duration_ms
        metrics.last_error_message = error_message[:500]

        # Auto-Quarantine Circuit Breaker: Trip on >= 5 consecutive sweep failures
        just_quarantined = False
        if metrics.consecutive_failures >= 5 and not metrics.is_quarantined:
            metrics.is_quarantined = True
            metrics.quarantined_at = now
            metrics.quarantine_reason = error_message[:500]
            just_quarantined = True
            logger.critical(
                f"🚨 Auto-quarantine triggered: Source '{source_name}' tripped circuit breaker "
                f"after {metrics.consecutive_failures} consecutive failures. Polling suspended for 12 hours."
            )

        # Record 0 entries on failure to reflect dormant/failing frequency
        metrics.recent_entry_counts.append(0)
        if len(metrics.recent_entry_counts) > 10:
            metrics.recent_entry_counts.pop(0)

        metrics.latencies.append(duration_ms)
        if len(metrics.latencies) > 20:
            metrics.latencies.pop(0)

        logger.warning(
            f"Source '{source_name}' health degraded: {metrics.consecutive_failures} "
            f"consecutive failures (status: {metrics.status})"
        )

        if just_quarantined:
            self._emit_quarantine_telegram_alert(
                source_name=source_name,
                consecutive_failures=metrics.consecutive_failures,
                error_message=error_message,
                source_id=metrics.source_id,
            )

    def unquarantine(self, source_name: str) -> bool:
        """Manually restore and reset a quarantined source back to healthy state."""
        m = self._sources.get(source_name)
        if not m:
            for s in self._sources.values():
                if s.source_id and (
                    s.source_id == source_name or s.source_id.startswith(source_name)
                ):
                    m = s
                    break
                if s.source_name.lower() == source_name.lower():
                    m = s
                    break

        if m:
            m.is_quarantined = False
            m.consecutive_failures = 0
            m.quarantined_at = None
            m.quarantine_reason = None
            m.last_error_message = None
            m.error_count = 0
            m.total_runs = 0
            m.success_count = 0
            logger.info(f"Source '{m.source_name}' manually unquarantined and reset.")
            return True
        return False

    def is_source_quarantined(self, source_name: str) -> bool:
        """Return True if source is quarantined and its 12-hour backoff probe has not elapsed."""
        m = self._sources.get(source_name)
        return bool(m and m.status == "quarantined" and m.circuit_state == "open")

    def _emit_quarantine_telegram_alert(
        self,
        source_name: str,
        consecutive_failures: int,
        error_message: str,
        source_id: str | None = None,
    ) -> None:
        """Emit a diagnostic notification via TelegramChatOpsService when quarantined."""
        try:
            import asyncio

            from ai_security_monitor.application.services.telegram_chatops_service import (
                telegram_chatops_service,
            )

            coro = telegram_chatops_service.notify_source_quarantined(
                source_name=source_name,
                consecutive_failures=consecutive_failures,
                error_message=error_message,
                source_id=source_id,
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(coro)
            except RuntimeError:
                asyncio.run(coro)
        except Exception as e:
            logger.debug(f"Telegram quarantine alert suppressed: {e}")

    def get_source_health(self, source_name: str) -> dict | None:
        """Get health data for a specific source."""
        m = self._sources.get(source_name)
        return m.to_dict() if m else None

    def get_adaptive_interval(
        self, source_name: str, fallback_seconds: int = 3600
    ) -> int:
        """Retrieve dynamic polling interval based on historical entry_frequency."""
        m = self._sources.get(source_name)
        if m:
            return m.adaptive_polling_interval_seconds
        return fallback_seconds

    def is_circuit_open(self, source_name: str) -> bool:
        """Return True if the circuit breaker for this source is currently open (cooling down or quarantined)."""
        m = self._sources.get(source_name)
        return m.circuit_state == "open" if m else False

    def get_health_report(self) -> dict:
        """Compile comprehensive system-wide source health report."""
        sources_list = [m.to_dict() for m in self._sources.values()]
        total_sources = len(sources_list)
        healthy_count = sum(1 for s in sources_list if s["status"] == "healthy")
        degraded_count = sum(1 for s in sources_list if s["status"] == "degraded")
        failing_count = sum(1 for s in sources_list if s["status"] == "failing")
        quarantined_count = sum(1 for s in sources_list if s["status"] == "quarantined")

        # Regional health rollups
        by_region: dict[str, dict] = {}
        for s in sources_list:
            reg = s["region"]
            if reg not in by_region:
                by_region[reg] = {
                    "total": 0,
                    "healthy": 0,
                    "failing": 0,
                    "quarantined": 0,
                }
            by_region[reg]["total"] += 1
            if s["status"] == "healthy":
                by_region[reg]["healthy"] += 1
            elif s["status"] == "failing":
                by_region[reg]["failing"] += 1
            elif s["status"] == "quarantined":
                by_region[reg]["quarantined"] += 1

        overall_status = "healthy"
        if quarantined_count > 0 or failing_count > 0:
            unhealthy_count = quarantined_count + failing_count
            overall_status = (
                "degraded" if unhealthy_count < total_sources * 0.3 else "critical"
            )

        from ai_security_monitor.infrastructure.fetchers.throttle import (
            domain_throttle,
        )

        return {
            "overall_status": overall_status,
            "total_monitored_sources": total_sources,
            "healthy_count": healthy_count,
            "degraded_count": degraded_count,
            "failing_count": failing_count,
            "quarantined_count": quarantined_count,
            "regional_rollups": by_region,
            "domain_throttle": domain_throttle.get_stats(),
            "sources": sorted(
                sources_list,
                key=lambda x: (x["status"] == "healthy", x["source_name"]),
            ),
        }


# Global singleton source health service
source_health_service = SourceHealthService()
