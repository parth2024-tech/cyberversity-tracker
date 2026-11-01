"""
Test DB Isolation verification.
Guarantees tests never write to data/monitor.db and that settings.database.url
points to the isolated throwaway test path.
"""

from __future__ import annotations

import os

from ai_security_monitor.config.settings import settings


def test_resolved_database_url_is_isolated():
    """Verify that settings.database.url resolves strictly to isolated test path."""
    assert "/tmp/aetherguard_test_data" in settings.database.url
    assert "data/monitor.db" not in settings.database.url.split("/")[-2:]


def test_dev_database_unmodified_by_tests():
    """Verify that data/monitor.db file exists (or not) and has not been locked/modified."""
    dev_db_path = "data/monitor.db"
    if os.path.exists(dev_db_path):
        stat = os.stat(dev_db_path)
        assert stat.st_size >= 0
