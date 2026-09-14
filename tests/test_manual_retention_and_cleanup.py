"""
Unit and integration tests for Manual-Only Intelligence Retention and Cleanup.
Ensures data is NEVER automatically deleted without explicit user manual action.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.scheduler_service import SchedulerService
from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.infrastructure.database.models import EntryModel
from ai_security_monitor.presentation.api.main import create_app


def test_auto_purge_disabled_by_default():
    """Verify that auto_purge_enabled is False by default to guarantee no automatic deletion."""
    assert settings.database.auto_purge_enabled is False


@pytest.mark.asyncio
async def test_scheduler_does_not_purge_when_auto_purge_disabled():
    """Verify that scheduler loop does NOT call purge_stale_entries when auto_purge_enabled is False."""
    mock_monitor = MagicMock()
    mock_monitor.fetch_all = AsyncMock(
        return_value={"total_new": 5, "success": 10, "total_sources": 10}
    )
    mock_monitor.purge_stale_entries = AsyncMock()

    scheduler = SchedulerService(monitor_service=mock_monitor)

    with patch(
        "ai_security_monitor.application.services.scheduler_service.settings"
    ) as mock_settings:
        mock_settings.database.auto_purge_enabled = False
        mock_settings.database.retention_days = 7
        mock_settings.scheduler.fetch_interval_minutes = 10

        with patch(
            "asyncio.sleep", new=AsyncMock(side_effect=[None, asyncio.CancelledError()])
        ):
            scheduler._running = True
            try:
                await scheduler._loop()
            except asyncio.CancelledError:
                pass

    mock_monitor.fetch_all.assert_awaited()
    # purge_stale_entries MUST NOT be called!
    mock_monitor.purge_stale_entries.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_purges_only_when_auto_purge_explicitly_enabled():
    """Verify that scheduler loop only calls purge_stale_entries when auto_purge_enabled is explicitly True."""
    mock_monitor = MagicMock()
    mock_monitor.fetch_all = AsyncMock(
        return_value={"total_new": 5, "success": 10, "total_sources": 10}
    )
    mock_monitor.purge_stale_entries = AsyncMock(return_value={"purged": 12})

    scheduler = SchedulerService(monitor_service=mock_monitor)

    with patch(
        "ai_security_monitor.application.services.scheduler_service.settings"
    ) as mock_settings:
        mock_settings.database.auto_purge_enabled = True
        mock_settings.database.retention_days = 7
        mock_settings.scheduler.fetch_interval_minutes = 10

        with patch(
            "asyncio.sleep", new=AsyncMock(side_effect=[None, asyncio.CancelledError()])
        ):
            scheduler._running = True
            try:
                await scheduler._loop()
            except asyncio.CancelledError:
                pass

    mock_monitor.fetch_all.assert_awaited()
    mock_monitor.purge_stale_entries.assert_awaited_once_with(older_than_days=7)


@pytest.mark.asyncio
async def test_repository_restore_purged_entries(test_uow):
    """Verify that restore_purged_entries un-purges soft-deleted entries back to active state."""
    # Insert two entries: one active, one soft-purged
    e1 = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Active Entry",
        url="https://example.com/1",
        content_hash="hash1",
        category=Category.AI_RESEARCH,
        published_at=datetime.now(UTC),
    )
    e2 = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Purged Entry",
        url="https://example.com/2",
        content_hash="hash2",
        category=Category.AI_RESEARCH,
        published_at=datetime.now(UTC) - timedelta(days=10),
    )

    await test_uow.entries.add(e1)
    await test_uow.entries.add(e2)
    await test_uow.commit()

    # Soft-purge e2
    model2 = await test_uow.session.get(EntryModel, str(e2.id))
    assert model2 is not None
    model2.is_purged = True
    model2.purged_at = datetime.now(UTC)
    await test_uow.commit()

    # Check retention counts before restoration
    counts_before = await test_uow.entries.get_retention_counts(older_than_days=7)
    assert counts_before["purged_count"] >= 1

    # Call restore_purged_entries
    restored = await test_uow.entries.restore_purged_entries()
    assert restored >= 1
    await test_uow.commit()

    # Check that model2 is now unpurged
    model2_after = await test_uow.session.get(EntryModel, str(e2.id))
    assert model2_after is not None
    assert model2_after.is_purged is False
    assert model2_after.purged_at is None

    counts_after = await test_uow.entries.get_retention_counts(older_than_days=7)
    assert counts_after["purged_count"] == 0


@pytest.mark.asyncio
async def test_api_retention_and_purge_endpoints():
    """Verify REST API endpoints: GET /api/stats/retention, POST /api/stats/purge, and POST /api/stats/restore-purged."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. GET /api/stats/retention
        ret_res = await client.get("/api/stats/retention?days=30")
        assert ret_res.status_code == 200
        data = ret_res.json()
        assert "active_count" in data
        assert "purged_count" in data
        assert "candidates_count" in data
        assert "vaulted_count" in data
        assert data["auto_purge_enabled"] is False
        assert data["older_than_days"] == 30

        # 2. POST /api/stats/purge
        purge_res = await client.post("/api/stats/purge?days=90")
        assert purge_res.status_code == 200
        p_data = purge_res.json()
        assert "purged" in p_data
        assert p_data["older_than_days"] == 90

        # 3. POST /api/stats/restore-purged
        restore_res = await client.post("/api/stats/restore-purged")
        assert restore_res.status_code == 200
        r_data = restore_res.json()
        assert "restored" in r_data
        assert r_data["success"] is True
