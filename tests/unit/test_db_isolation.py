"""
Unit tests for database test-isolation invariants.
Verifies that test execution never mutates or targets the developer's
local development database (data/monitor.db).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_security_monitor.config.settings import settings


def test_resolved_database_url_is_isolated():
    """Assert that the runtime resolved database URL points strictly to the isolated temp directory."""
    resolved_url = settings.database.url
    assert "/tmp/aetherguard_test_data" in resolved_url, (
        f"Test safety breach: settings.database.url ({resolved_url}) does not point to /tmp/aetherguard_test_data"
    )
    assert not resolved_url.endswith("data/monitor.db") or "/tmp/" in resolved_url


@pytest.mark.asyncio
async def test_dev_database_unmodified_by_tests():
    """Verify that data/monitor.db mtime does not change during unit test actions."""
    dev_db = Path("data/monitor.db")
    if dev_db.exists():
        stat_before = dev_db.stat()
        mtime_before = stat_before.st_mtime
        size_before = stat_before.st_size

        from ai_security_monitor.infrastructure.database.unit_of_work import (
            SqlAlchemyUnitOfWork,
        )

        async with SqlAlchemyUnitOfWork() as uow:
            # Simple read
            await uow.sources.list(enabled_only=False)

        stat_after = dev_db.stat()
        assert stat_after.st_mtime == mtime_before, (
            "Dev database was modified by test suite!"
        )
        assert stat_after.st_size == size_before, (
            "Dev database size changed during test execution!"
        )
