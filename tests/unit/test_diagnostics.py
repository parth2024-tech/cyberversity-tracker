"""
Unit tests for Core Diagnostics & Self-Healing Telemetry Tracker.
"""
from ai_security_monitor.core.diagnostics import DiagnosticsTracker


def test_diagnostics_tracker_lifecycle():
    tracker = DiagnosticsTracker()

    # Initial state
    summary = tracker.get_summary()
    assert summary["github_scrape_fallbacks"] == 0
    assert summary["websocket_backpressure_drops"] == 0
    assert summary["consecutive_failure_alerts"] == 0
    assert summary["language_uncertain_preservations"] == 0
    assert summary["last_backup"]["filename"] is None

    # Record events
    tracker.record_scrape_fallback("GitHub Trending Test", "DOM elements missing")
    tracker.record_websocket_backpressure_drop()
    tracker.record_websocket_backpressure_drop()
    tracker.record_failure_alert("ArXiv AI", 3)
    tracker.record_language_uncertain("ambiguous title")
    tracker.record_backup_completed("monitor_backup_20260101.db", 1536.4, 60)

    # Verify updated summary
    updated = tracker.get_summary()
    assert updated["github_scrape_fallbacks"] == 1
    assert updated["websocket_backpressure_drops"] == 2
    assert updated["consecutive_failure_alerts"] == 1
    assert updated["language_uncertain_preservations"] == 1
    assert updated["last_backup"]["filename"] == "monitor_backup_20260101.db"
    assert updated["last_backup"]["size_kb"] == 1536.4
    assert updated["last_backup"]["retained_count"] == 60

    # Reset
    tracker.reset_for_test()
    reset_summary = tracker.get_summary()
    assert reset_summary["github_scrape_fallbacks"] == 0
    assert reset_summary["websocket_backpressure_drops"] == 0
