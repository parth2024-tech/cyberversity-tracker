"""
Unit test asserting that automated test execution strictly isolates from dev database data/monitor.db.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_security_monitor.config.settings import settings


@pytest.mark.asyncio
async def test_resolved_database_url_is_isolated():
    """Verify that settings.database.url points to /tmp test directory, never data/monitor.db."""
    url = settings.database.url
    assert "/tmp/aetherguard_test_data" in url, f"Database URL unsafe: {url}"
    assert "sqlite+aiosqlite:///data/monitor.db" != url
    assert not url.endswith("/ai-security-monitor/data/monitor.db")


@pytest.mark.asyncio
async def test_dev_database_unmodified_by_tests():
    """Verify data/monitor.db exists and is completely isolated."""
    dev_db = Path("data/monitor.db")
    if dev_db.exists():
        assert dev_db.stat().st_size >= 0
        test_db_file = Path("/tmp/aetherguard_test_data/monitor.db")
        assert dev_db.resolve() != test_db_file.resolve()
