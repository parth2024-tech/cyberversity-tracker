"""
Unit tests for SourceHealthService operational telemetry.
"""

from ai_security_monitor.application.services.source_health_service import (
    SourceHealthService,
)


def test_source_health_success_and_latency():
    svc = SourceHealthService()
    svc.record_success(
        source_name="arXiv AI Papers",
        duration_ms=450,
        entries_new=5,
        source_type="arxiv",
        category="ai_research",
        region="global",
    )

    data = svc.get_source_health("arXiv AI Papers")
    assert data is not None
    assert data["source_name"] == "arXiv AI Papers"
    assert data["status"] == "healthy"
    assert data["success_rate"] == 100.0
    assert data["last_latency_ms"] == 450
    assert data["last_entries_new"] == 5


def test_source_health_degradation_and_failure():
    svc = SourceHealthService()

    # Record 1 failure -> degraded
    svc.record_failure(
        source_name="Flaky RSS",
        duration_ms=2000,
        error_message="Connection timeout",
        source_type="rss",
    )
    data = svc.get_source_health("Flaky RSS")
    assert data is not None
    assert data["status"] == "degraded"
    assert data["consecutive_failures"] == 1

    # Record 2 more failures -> failing
    svc.record_failure(
        source_name="Flaky RSS", duration_ms=2000, error_message="Timeout 2"
    )
    svc.record_failure(
        source_name="Flaky RSS", duration_ms=2000, error_message="Timeout 3"
    )
    data = svc.get_source_health("Flaky RSS")
    assert data["status"] == "failing"
    assert data["consecutive_failures"] == 3

    # Recovery after success
    svc.record_success(source_name="Flaky RSS", duration_ms=300, entries_new=2)
    data = svc.get_source_health("Flaky RSS")
    assert data["consecutive_failures"] == 0
    # Success rate 1/4 = 25% -> degraded until more successes
    assert data["status"] == "degraded"


def test_get_health_report():
    svc = SourceHealthService()
    svc.record_success("Source 1", 100, 2, region="north_america")
    svc.record_failure("Source 2", 500, "Error", region="europe")

    report = svc.get_health_report()
    assert report["total_monitored_sources"] == 2
    assert "regional_rollups" in report
    assert "north_america" in report["regional_rollups"]
    assert "europe" in report["regional_rollups"]


def test_auto_quarantine_circuit_breaker():
    """Verify auto-quarantine trips at 5 consecutive failures and blocks sweeps."""
    svc = SourceHealthService()
    source_name = "Challenged ArXiv Feed"

    for i in range(4):
        svc.record_failure(
            source_name, duration_ms=500, error_message=f"HTTP 403 Err {i}"
        )
        assert svc.is_source_quarantined(source_name) is False

    # 5th failure trips quarantine circuit breaker
    svc.record_failure(
        source_name, duration_ms=500, error_message="HTTP 403 Cloudflare Challenge"
    )
    assert svc.is_source_quarantined(source_name) is True

    health = svc.get_source_health(source_name)
    assert health is not None
    assert health["status"] == "quarantined"
    assert health["is_quarantined"] is True
    assert health["consecutive_failures"] == 5
    assert health["circuit_state"] == "open"
    assert "Cloudflare" in health["quarantine_reason"]


def test_quarantine_twelve_hour_probe():
    """Verify 12-hour exponential backoff probe transitions circuit to half_open."""
    from datetime import UTC, datetime, timedelta

    svc = SourceHealthService()
    source_name = "Edge Inference Feed"

    # Trip quarantine
    for _ in range(5):
        svc.record_failure(source_name, duration_ms=600, error_message="Down")

    assert svc.is_source_quarantined(source_name) is True

    # Fast forward quarantined_at and last_error_at to 12 hours + 10 seconds ago
    metrics = svc._sources[source_name]
    past_time = datetime.now(UTC) - timedelta(seconds=43210)
    metrics.quarantined_at = past_time
    metrics.last_error_at = past_time

    # Probe allowed!
    assert svc.is_source_quarantined(source_name) is False
    assert metrics.circuit_state == "half_open"


def test_manual_unquarantine():
    """Verify manual unquarantine restores source to healthy status."""
    svc = SourceHealthService()
    source_name = "HuggingFace Trending"

    for _ in range(5):
        svc.record_failure(source_name, duration_ms=400, error_message="Quota")

    assert svc.is_source_quarantined(source_name) is True

    res = svc.unquarantine(source_name)
    assert res is True
    assert svc.is_source_quarantined(source_name) is False

    health = svc.get_source_health(source_name)
    assert health["is_quarantined"] is False
    assert health["consecutive_failures"] == 0
    assert health["status"] == "healthy"
    assert health["circuit_state"] == "closed"
