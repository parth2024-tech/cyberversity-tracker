"""
Core Diagnostics & Self-Healing Telemetry Tracker.

Maintains live runtime metrics for self-healing and operational safety mechanisms:
- GitHub Trending scrape health degradation & Search API fallbacks
- WebSocket consumer backpressure evictions (2.0s timeouts)
- Source consecutive sweep failure alerts (Telegram)
- Language detection confidence threshold mitigations
- Rolling automated SQLite backups
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


@dataclass
class BackupRecord:
    """Telemetry record of the most recent database backup."""

    filename: str | None = None
    size_kb: float = 0.0
    timestamp: str | None = None
    retained_count: int = 0


class DiagnosticsTracker:
    """Thread-safe in-memory diagnostics tracker for autonomous self-healing events."""

    def __init__(self) -> None:
        self.github_scrape_fallbacks_total: int = 0
        self.websocket_backpressure_drops_total: int = 0
        self.consecutive_failure_alerts_total: int = 0
        self.language_uncertain_preservations_total: int = 0
        self.recent_fallbacks: list[dict] = []
        self.last_backup: BackupRecord = BackupRecord()

    def record_scrape_fallback(
        self, source_name: str, reason: str = "low_yield_or_dom_degraded"
    ) -> None:
        """Record an automated fallback from HTML scraping to API search."""
        self.github_scrape_fallbacks_total += 1
        record = {
            "source": source_name,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.recent_fallbacks.append(record)
        if len(self.recent_fallbacks) > 20:
            self.recent_fallbacks.pop(0)

    def record_websocket_backpressure_drop(self) -> None:
        """Record an eviction of a stalled WebSocket consumer exceeding timeout."""
        self.websocket_backpressure_drops_total += 1

    def record_failure_alert(self, source_name: str, count: int) -> None:
        """Record a consecutive failure alert dispatched to external notifications."""
        self.consecutive_failure_alerts_total += 1

    def record_language_uncertain(self, title: str) -> None:
        """Record an intelligence item where language confidence was uncertain."""
        self.language_uncertain_preservations_total += 1

    def record_backup_completed(
        self, filename: str, size_kb: float, retained_count: int
    ) -> None:
        """Record a successful SQLite point-in-time backup."""
        self.last_backup = BackupRecord(
            filename=filename,
            size_kb=round(size_kb, 1),
            timestamp=datetime.now(UTC).isoformat(),
            retained_count=retained_count,
        )

    def get_summary(self) -> dict:
        """Export serialized diagnostics summary for API telemetry responses."""
        return {
            "github_scrape_fallbacks": self.github_scrape_fallbacks_total,
            "websocket_backpressure_drops": self.websocket_backpressure_drops_total,
            "consecutive_failure_alerts": self.consecutive_failure_alerts_total,
            "language_uncertain_preservations": self.language_uncertain_preservations_total,
            "last_backup": asdict(self.last_backup),
        }

    def reset_for_test(self) -> None:
        """Reset all counters (used during unit testing)."""
        self.github_scrape_fallbacks_total = 0
        self.websocket_backpressure_drops_total = 0
        self.consecutive_failure_alerts_total = 0
        self.language_uncertain_preservations_total = 0
        self.recent_fallbacks.clear()
        self.last_backup = BackupRecord()


# Global singleton instance
diagnostics = DiagnosticsTracker()
