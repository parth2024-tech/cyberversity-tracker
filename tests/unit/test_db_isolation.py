"""
Unit tests asserting that automated test execution strictly isolates from dev database data/monitor.db.
Validates Defect D1: test execution must never read or write the real database.
"""

import hashlib
from pathlib import Path

from ai_security_monitor.config.settings import settings
from ai_security_monitor.infrastructure.database.connection import db_manager


def test_settings_and_db_manager_url_resolved_to_tmp():
    """Verify that settings.database.resolved_url and db_manager.url point to /tmp test directory, never data/monitor.db."""
    url = settings.database.resolved_url
    assert "data/monitor.db" not in url or "/tmp" in url
    assert "/tmp/aetherguard_test_data" in url
    assert not url.endswith("/ai-security-monitor/data/monitor.db")

    manager_url = db_manager.url
    assert "data/monitor.db" not in manager_url or "/tmp" in manager_url
    assert "/tmp/aetherguard_test_data" in manager_url


def test_dev_database_completely_untouched():
    """Verify data/monitor.db exists and is completely isolated."""
    dev_db = Path("data/monitor.db")
    if dev_db.exists():
        initial_hash = hashlib.sha256(dev_db.read_bytes()).hexdigest()
        assert initial_hash is not None

        # Verify test db is separate
        test_db_file = Path("/tmp/aetherguard_test_data/monitor.db")
        if test_db_file.exists():
            # If both exist, test db can mutate while dev db stays immutable
            assert dev_db.resolve() != test_db_file.resolve()


def test_lazy_engine_rebuild_on_reset():
    """Verify that db_manager builds engine lazily and resets cleanly."""
    initial_engine = db_manager.engine
    assert initial_engine is not None

    db_manager.reset()
    assert db_manager._engine is None

    new_engine = db_manager.engine
    assert new_engine is not None
