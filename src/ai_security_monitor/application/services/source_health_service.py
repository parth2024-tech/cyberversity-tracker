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
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_latency_ms: int = 0
    latencies: list[int] = field(default_factory=list)
    last_error_message: str | None = None
    last_entries_new: int = 0

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
        """Health classification: healthy, degraded, or failing."""
        if self.consecutive_failures >= 3:
            return "failing"
        if self.consecutive_failures >= 1 or self.success_rate < 80.0:
            return "degraded"
        return "healthy"

    def to_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "category": self.category,
            "region": self.region,
            "status": self.status,
            "success_rate": self.success_rate,
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
    """Manages source health telemetry and diagnostics."""

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
        metrics.last_run_at = now
        metrics.last_success_at = now
        metrics.last_latency_ms = duration_ms
        metrics.last_entries_new = entries_new
        metrics.last_error_message = None

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
    ) -> None:
        """Record a failed fetch attempt for a source."""
        metrics = self._get_or_create(source_name, source_type, category, region)
        now = datetime.now(UTC)
        metrics.total_runs += 1
        metrics.error_count += 1
        metrics.consecutive_failures += 1
        metrics.last_run_at = now
        metrics.last_error_at = now
        metrics.last_latency_ms = duration_ms
        metrics.last_error_message = error_message[:500]

        metrics.latencies.append(duration_ms)
        if len(metrics.latencies) > 20:
            metrics.latencies.pop(0)

        logger.warning(
            f"Source '{source_name}' health degraded: {metrics.consecutive_failures} "
            f"consecutive failures (status: {metrics.status})"
        )

    def get_source_health(self, source_name: str) -> dict | None:
        """Get health data for a specific source."""
        m = self._sources.get(source_name)
        return m.to_dict() if m else None

    def get_health_report(self) -> dict:
        """Compile comprehensive system-wide source health report."""
        sources_list = [m.to_dict() for m in self._sources.values()]
        total_sources = len(sources_list)
        healthy_count = sum(1 for s in sources_list if s["status"] == "healthy")
        degraded_count = sum(1 for s in sources_list if s["status"] == "degraded")
        failing_count = sum(1 for s in sources_list if s["status"] == "failing")

        # Regional health rollups
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


# Global singleton source health service
source_health_service = SourceHealthService()
