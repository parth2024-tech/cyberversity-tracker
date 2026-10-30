"""
Source Health Telemetry & Dashboard Service.
Maintains deterministic, database-backed source health states (OK, STALE, DEAD, BLOCKED, REDIRECTED)
derived from fetch_log and entry history, with alerting on degradation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import SourceHealthState
from ai_security_monitor.infrastructure.database.models import (
    EntryModel,
    FetchLogModel,
    SourceHealthModel,
    SourceModel,
)

logger = get_logger(__name__)


def compute_source_state(
    *,
    last_http_status: int | None = None,
    last_new_entry_at: datetime | None = None,
    consecutive_failures: int = 0,
    is_html_error: bool = False,
    is_redirected: bool = False,
    now: datetime | None = None,
    source_created_at: datetime | None = None,
) -> SourceHealthState:
    """Compute deterministic health state according to AetherGuard specification:
    - BLOCKED: HTTP 403/429, or HTML returned instead of XML/JSON feed
    - REDIRECTED: final URL host differs from configured host
    - DEAD: no new entry for >14 days OR 5+ consecutive failures
    - STALE: no new entry for 7-14 days
    - OK: new entry within 7 days (and not BLOCKED/DEAD)
    """
    ref_now = now or datetime.now(UTC)
    if ref_now.tzinfo is None:
        ref_now = ref_now.replace(tzinfo=UTC)

    # 1. BLOCKED check (HTTP 403/429 or HTML returned instead of feed)
    if last_http_status in (403, 429) or is_html_error:
        return SourceHealthState.BLOCKED

    # 2. REDIRECTED check
    if is_redirected:
        return SourceHealthState.REDIRECTED

    # 3. DEAD check (5+ consecutive failures)
    if consecutive_failures >= 5:
        return SourceHealthState.DEAD

    # Calculate days since last productive entry
    ref_time = last_new_entry_at or source_created_at
    if ref_time is not None:
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=UTC)
        age_days = (ref_now - ref_time).total_seconds() / 86400.0
        if age_days > 14.0:
            return SourceHealthState.DEAD
        elif age_days > 7.0:
            return SourceHealthState.STALE
        else:
            return SourceHealthState.OK

    # If never fetched and created recently, assume OK
    return SourceHealthState.OK


@dataclass
class SourceHealthMetrics:
    """In-memory telemetry helper for fast runtime frequency & circuit breaker."""

    source_name: str
    source_type: str = "unknown"
    category: str = "unknown"
    region: str = "global"
    total_runs: int = 0
    success_count: int = 0
    error_count: int = 0
    consecutive_failures: int = 0
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_latency_ms: int = 0
    latencies: list[int] = field(default_factory=list)
    last_error_message: str | None = None
    last_entries_new: int = 0
    recent_entry_counts: list[int] = field(default_factory=list)
    zero_entry_streak: int = 0
    last_productive_at: datetime | None = None

    @property
    def entry_frequency(self) -> float:
        """Average entries produced per run over the last 10 runs."""
        if not self.recent_entry_counts:
            return float(self.last_entries_new)
        return round(sum(self.recent_entry_counts) / len(self.recent_entry_counts), 2)

    @property
    def adaptive_polling_interval_seconds(self) -> int:
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
        if self.consecutive_failures >= 3:
            return "failing"
        if (
            self.consecutive_failures >= 1
            or self.zero_entry_streak >= 5
            or self.success_rate < 80.0
        ):
            return "degraded"
        return "healthy"

    @property
    def cooldown_remaining_seconds(self) -> int:
        if self.consecutive_failures < 3 or not self.last_error_at:
            return 0
        cooldown = min(3600, 60 * (2 ** (self.consecutive_failures - 3)))
        last_err = (
            self.last_error_at
            if self.last_error_at.tzinfo
            else self.last_error_at.replace(tzinfo=UTC)
        )
        elapsed = (datetime.now(UTC) - last_err).total_seconds()
        return max(0, int(cooldown - elapsed))

    @property
    def circuit_state(self) -> str:
        if self.consecutive_failures < 3:
            return "closed"
        return "open" if self.cooldown_remaining_seconds > 0 else "half_open"

    def to_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "category": self.category,
            "region": self.region,
            "status": self.status,
            "circuit_state": self.circuit_state,
            "cooldown_remaining_seconds": self.cooldown_remaining_seconds,
            "success_rate": self.success_rate,
            "entry_frequency": self.entry_frequency,
            "adaptive_polling_interval_seconds": self.adaptive_polling_interval_seconds,
            "consecutive_failures": self.consecutive_failures,
            "zero_entry_streak": self.zero_entry_streak,
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
            "last_productive_at": self.last_productive_at.isoformat()
            if self.last_productive_at
            else None,
        }


class SourceHealthService:
    """Manages database-backed source health, state transitions, and alerting."""

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
        is_not_modified: bool = False,
    ) -> None:
        """Record a successful fetch sweep for in-memory telemetry."""
        metrics = self._get_or_create(source_name, source_type, category, region)
        now = datetime.now(UTC)
        metrics.total_runs += 1
        metrics.success_count += 1
        metrics.consecutive_failures = 0
        metrics.last_run_at = now
        metrics.last_success_at = now
        metrics.last_latency_ms = duration_ms
        metrics.last_entries_new = entries_new
        metrics.last_error_message = None

        if entries_new > 0:
            metrics.zero_entry_streak = 0
            metrics.last_productive_at = now
        elif not is_not_modified:
            metrics.zero_entry_streak += 1

        metrics.recent_entry_counts.append(entries_new)
        if len(metrics.recent_entry_counts) > 10:
            metrics.recent_entry_counts.pop(0)

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
    ) -> None:
        """Record a failed fetch attempt for in-memory telemetry."""
        metrics = self._get_or_create(source_name, source_type, category, region)
        now = datetime.now(UTC)
        metrics.total_runs += 1
        metrics.error_count += 1
        metrics.consecutive_failures += 1
        metrics.zero_entry_streak += 1
        metrics.last_run_at = now
        metrics.last_error_at = now
        metrics.last_latency_ms = duration_ms
        metrics.last_error_message = error_message[:500]

        metrics.recent_entry_counts.append(0)
        if len(metrics.recent_entry_counts) > 10:
            metrics.recent_entry_counts.pop(0)

        metrics.latencies.append(duration_ms)
        if len(metrics.latencies) > 20:
            metrics.latencies.pop(0)

    def is_stale(self, source_name: str, threshold: int = 5) -> bool:
        m = self._sources.get(source_name)
        return m.zero_entry_streak >= threshold if m else False

    def get_source_health(self, source_name: str) -> dict | None:
        m = self._sources.get(source_name)
        return m.to_dict() if m else None

    def get_adaptive_interval(
        self, source_name: str, fallback_seconds: int = 3600
    ) -> int:
        m = self._sources.get(source_name)
        if m:
            return m.adaptive_polling_interval_seconds
        return fallback_seconds

    def is_circuit_open(self, source_name: str) -> bool:
        m = self._sources.get(source_name)
        return m.circuit_state == "open" if m else False

    def get_health_report(self) -> dict:
        sources_list = [m.to_dict() for m in self._sources.values()]
        total_sources = len(sources_list)
        healthy_count = sum(1 for s in sources_list if s["status"] == "healthy")
        degraded_count = sum(1 for s in sources_list if s["status"] == "degraded")
        failing_count = sum(1 for s in sources_list if s["status"] == "failing")

        by_region: dict[str, dict] = {}
        for s in sources_list:
            reg = s["region"]
            if reg not in by_region:
                by_region[reg] = {"total": 0, "healthy": 0, "failing": 0}
            by_region[reg]["total"] += 1
            if s["status"] == "healthy":
                by_region[reg]["healthy"] += 1
            elif s["status"] == "failing":
                by_region[reg]["failing"] += 1

        overall_status = "healthy"
        if failing_count > 0:
            overall_status = (
                "degraded" if failing_count < total_sources * 0.3 else "critical"
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
            "regional_rollups": by_region,
            "domain_throttle": domain_throttle.get_stats(),
            "sources": sorted(
                sources_list,
                key=lambda x: (x["status"] != "failing", x["source_name"]),
            ),
        }

    # ── Database-Backed Source Health Synchronization ─────────────────────────

    async def sync_source_from_db(
        self,
        session: AsyncSession,
        source: SourceModel,
        *,
        now: datetime | None = None,
    ) -> SourceHealthModel:
        """Derive source health from fetch_log and entries for a single source and persist to source_health."""
        ref_now = now or datetime.now(UTC)
        if ref_now.tzinfo is None:
            ref_now = ref_now.replace(tzinfo=UTC)

        source_id = str(source.id)

        # 1. Query recent fetch_logs (last 20) ordered by fetched_at DESC
        logs_stmt = (
            select(FetchLogModel)
            .where(FetchLogModel.source_id == source_id)
            .order_by(desc(FetchLogModel.fetched_at))
            .limit(20)
        )
        logs_res = await session.execute(logs_stmt)
        recent_logs = list(logs_res.scalars().all())

        last_log = recent_logs[0] if recent_logs else None
        last_fetch_at = last_log.fetched_at if last_log else source.last_fetched_at
        last_http_status = getattr(last_log, "http_status", None) if last_log else None
        error_msg = last_log.error_message if last_log else None
        entries_filtered_last = getattr(last_log, "entries_filtered", 0) if last_log else 0

        # Calculate consecutive failures from latest fetch backwards
        consecutive_failures = 0
        for log_entry in recent_logs:
            if log_entry.status != "success":
                consecutive_failures += 1
            else:
                break

        # Calculate consecutive zero runs
        consecutive_zero_runs = 0
        for log_entry in recent_logs:
            if log_entry.status == "success":
                # 304 does not touch zero runs counter
                if getattr(log_entry, "http_status", None) == 304:
                    continue
                if log_entry.entries_new == 0:
                    consecutive_zero_runs += 1
                else:
                    break
            else:
                consecutive_zero_runs += 1

        # 2. Query last_new_entry_at from entries table
        last_entry_stmt = (
            select(func.max(EntryModel.published_at))
            .where(EntryModel.source_id == source_id)
        )
        last_entry_res = await session.execute(last_entry_stmt)
        last_new_entry_at = last_entry_res.scalar()

        # If entries table has no published_at, fallback to last productive fetch_log
        if not last_new_entry_at:
            prod_log_stmt = (
                select(func.max(FetchLogModel.fetched_at))
                .where(
                    FetchLogModel.source_id == source_id,
                    FetchLogModel.entries_new > 0,
                )
            )
            prod_log_res = await session.execute(prod_log_stmt)
            last_new_entry_at = prod_log_res.scalar()

        # 3. Query 7-day yield
        seven_days_ago = ref_now - timedelta(days=7)
        yield_stmt = (
            select(func.count(EntryModel.id))
            .where(
                EntryModel.source_id == source_id,
                EntryModel.published_at >= seven_days_ago,
            )
        )
        yield_res = await session.execute(yield_stmt)
        seven_day_yield = yield_res.scalar() or 0

        # 4. Check for HTML error or host redirection
        is_html_error = False
        if error_msg:
            err_lower = error_msg.lower()
            if "html instead of" in err_lower or "content-type: text/html" in err_lower:
                is_html_error = True

        is_redirected = False
        if error_msg and "redirected: host changed" in error_msg.lower():
            is_redirected = True

        # 5. Compute deterministic state
        new_state = compute_source_state(
            last_http_status=last_http_status,
            last_new_entry_at=last_new_entry_at,
            consecutive_failures=consecutive_failures,
            is_html_error=is_html_error,
            is_redirected=is_redirected,
            now=ref_now,
            source_created_at=source.created_at,
        )

        # 6. Upsert into source_health table
        health_stmt = select(SourceHealthModel).where(SourceHealthModel.source_id == source_id)
        health_res = await session.execute(health_stmt)
        health_model = health_res.scalar_one_or_none()

        prev_state = health_model.state if health_model else "OK"

        if not health_model:
            health_model = SourceHealthModel(
                source_id=source_id,
                last_fetch_at=last_fetch_at,
                last_http_status=last_http_status,
                last_new_entry_at=last_new_entry_at,
                consecutive_failures=consecutive_failures,
                consecutive_zero_runs=consecutive_zero_runs,
                state=new_state.value,
                error_message=error_msg,
                seven_day_yield=seven_day_yield,
                entries_filtered_last=entries_filtered_last,
                updated_at=ref_now,
            )
            session.add(health_model)
        else:
            health_model.last_fetch_at = last_fetch_at
            health_model.last_http_status = last_http_status
            health_model.last_new_entry_at = last_new_entry_at
            health_model.consecutive_failures = consecutive_failures
            health_model.consecutive_zero_runs = consecutive_zero_runs
            health_model.state = new_state.value
            health_model.error_message = error_msg
            health_model.seven_day_yield = seven_day_yield
            health_model.entries_filtered_last = entries_filtered_last
            health_model.updated_at = ref_now

        # 7. Alert notification on state transition OK -> STALE or DEAD
        if prev_state == "OK" and new_state.value in ("STALE", "DEAD"):
            logger.warning(
                f"[HEALTH ALERT] Source '{source.name}' transitioned from {prev_state} -> {new_state.value} "
                f"(failures={consecutive_failures}, zero_runs={consecutive_zero_runs}, "
                f"last_new_entry={last_new_entry_at}, status={last_http_status})"
            )

        return health_model

    async def sync_all_from_db(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Sweep all sources in the database and synchronize their source_health records."""
        sources_stmt = select(SourceModel)
        sources_res = await session.execute(sources_stmt)
        sources = list(sources_res.scalars().all())

        counts = {"OK": 0, "STALE": 0, "DEAD": 0, "BLOCKED": 0, "REDIRECTED": 0}

        for src in sources:
            h = await self.sync_source_from_db(session, src, now=now)
            counts[h.state] = counts.get(h.state, 0) + 1

        await session.flush()
        return {
            "total_sources": len(sources),
            "state_counts": counts,
            "counts": counts,
        }

    async def get_dashboard(
        self,
        session: AsyncSession,
        state: str | None = None,
        region: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query persistent source_health table joined with sources, sorted worst-first."""
        from ai_security_monitor.infrastructure.database.repositories import (
            SQLAlchemySourceHealthRepository,
        )

        repo = SQLAlchemySourceHealthRepository(session)
        items = await repo.list(state=state, region=region)
        return items[:limit]


source_health_service = SourceHealthService()
