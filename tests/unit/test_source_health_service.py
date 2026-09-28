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
