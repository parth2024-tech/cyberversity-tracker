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


def test_source_health_zero_entry_streak():
    svc = SourceHealthService()

    # Record 4 consecutive runs with 0 new entries
    for _ in range(4):
        svc.record_success(
            source_name="Dormant Feed",
            duration_ms=150,
            entries_new=0,
            source_type="rss",
        )

    data = svc.get_source_health("Dormant Feed")
    assert data is not None
    assert data["zero_entry_streak"] == 4
    assert data["status"] == "healthy"
    assert not svc.is_stale("Dormant Feed", threshold=5)

    # 5th run with 0 new entries triggers degraded status and stale flag
    svc.record_success(
        source_name="Dormant Feed",
        duration_ms=150,
        entries_new=0,
        source_type="rss",
    )
    data = svc.get_source_health("Dormant Feed")
    assert data["zero_entry_streak"] == 5
    assert data["status"] == "degraded"
    assert svc.is_stale("Dormant Feed", threshold=5)

    # A productive run resets zero_entry_streak
    svc.record_success(
        source_name="Dormant Feed",
        duration_ms=200,
        entries_new=3,
        source_type="rss",
    )
    data = svc.get_source_health("Dormant Feed")
    assert data["zero_entry_streak"] == 0
    assert not svc.is_stale("Dormant Feed", threshold=5)


def test_source_health_http_304_not_modified_does_not_increment_streak():
    svc = SourceHealthService()

    # Active source has streak = 0
    svc.record_success(
        source_name="Active Feed",
        duration_ms=100,
        entries_new=5,
        source_type="rss",
    )
    assert svc.get_source_health("Active Feed")["zero_entry_streak"] == 0

    # HTTP 304 response (is_not_modified=True) occurs
    svc.record_success(
        source_name="Active Feed",
        duration_ms=45,
        entries_new=0,
        source_type="rss",
        is_not_modified=True,
    )
    # Streak should remain 0 because 304 is a valid cache hit, not dormant/dead
    assert svc.get_source_health("Active Feed")["zero_entry_streak"] == 0
    assert svc.get_source_health("Active Feed")["status"] == "healthy"

