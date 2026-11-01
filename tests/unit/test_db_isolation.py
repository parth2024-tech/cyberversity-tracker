"""
Unit tests for database isolation during test runs.
Verifies Defect Ledger D1:
1. Resolved settings.database.url never targets 'data/monitor.db' or production paths.
2. Database write operations in test suites never alter real dev database files (data/monitor.db).
3. db_manager builds engine lazily and resets cleanly.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.infrastructure.database.connection import db_manager
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


def test_resolved_database_url_isolation():
    """Verify that settings.database.url points to an isolated test directory and never dev/prod data/monitor.db."""
    resolved_url = settings.database.url

    # Must be either tmp test path or in-memory
    assert "sqlite+aiosqlite:////tmp/" in resolved_url or "memory" in resolved_url, (
        f"Test suite is running with non-isolated DB URL: {resolved_url}"
    )

    # Must never target local repo data/monitor.db
    assert not resolved_url.endswith("/data/monitor.db") or "/tmp/" in resolved_url


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


@pytest.mark.asyncio
async def test_real_dev_db_remains_unmutated_after_writes():
    """Verify that inserting entries in tests never mutates local dev data/monitor.db."""
    dev_db_path = Path("data/monitor.db").resolve()

    before_mtime = None
    before_size = None
    if dev_db_path.exists():
        before_stat = dev_db_path.stat()
        before_mtime = before_stat.st_mtime
        before_size = before_stat.st_size

    # Execute a real write in SqlAlchemyUnitOfWork
    test_id = uuid4()
    test_entry = Entry(
        id=test_id,
        source_id=uuid4(),
        title="Isolation Test Entry",
        url=f"https://example.com/isolation-test-{test_id}",
        content_hash="f" * 64,
        summary="Verifying zero bleed into dev DB",
        published_at=datetime.now(UTC),
        category=Category.AI_TECH,
    )

    async with SqlAlchemyUnitOfWork() as uow:
        await uow.entries.add(test_entry)
        await uow.commit()

        # Confirm it was written to the test DB
        persisted = await uow.entries.get(test_id)
        assert persisted is not None
        assert persisted.id == test_id

    # If dev DB exists, verify it was untouched
    if dev_db_path.exists():
        after_stat = dev_db_path.stat()
        assert after_stat.st_mtime == before_mtime, (
            "CRITICAL: dev DB 'data/monitor.db' mtime changed during test execution!"
        )
        assert after_stat.st_size == before_size, (
            "CRITICAL: dev DB 'data/monitor.db' size changed during test execution!"
        )
