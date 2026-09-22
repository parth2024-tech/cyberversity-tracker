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
async def test_api_retention_and_purge_endpoints(test_uow):
    """Verify REST API endpoints: GET /api/stats/retention, POST /api/stats/purge, and POST /api/stats/restore-purged."""
    from ai_security_monitor.application.services.monitor_service import MonitorService
    from ai_security_monitor.presentation.api.routers.stats import get_monitor_service

    app = create_app()
    app.dependency_overrides[get_monitor_service] = lambda: MonitorService(
        lambda: test_uow
    )
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

        # 4. POST /api/stats/purge with days=0, hard_delete=true, include_vaulted=true
        all_purge_res = await client.post(
            "/api/stats/purge?days=0&hard_delete=true&include_vaulted=true"
        )
        assert all_purge_res.status_code == 200
        ap_data = all_purge_res.json()
        assert ap_data["older_than_days"] == 0
        assert ap_data["hard_delete"] is True
        assert ap_data["include_vaulted"] is True


@pytest.mark.asyncio
async def test_purge_hard_delete_and_vault_override(test_uow):
    """Verify that hard_delete permanently erases records and include_vaulted overrides vault exemption."""
    vaulted_id = uuid4()
    normal_id = uuid4()
    now = datetime.now(UTC)
    old_time = now - timedelta(days=400)

    # 1. Normal entry older than 365 days — fetched_at is set to old_time so purge picks it up
    e_normal = Entry(
        id=normal_id,
        source_id=uuid4(),
        title="Old Normal Entry",
        url="https://example.com/norm",
        content_hash="hash-norm-1",
        category=Category.AI_RESEARCH,
        published_at=old_time,
        fetched_at=old_time,
        metadata={"is_important": False},
    )
    # 2. Vaulted entry older than 365 days — fetched_at set to old_time
    e_vault = Entry(
        id=vaulted_id,
        source_id=uuid4(),
        title="Old Vaulted Entry",
        url="https://example.com/vault",
        content_hash="hash-vault-1",
        category=Category.AI_MODELS,
        published_at=old_time,
        fetched_at=old_time,
        metadata={"is_important": True},
    )

    await test_uow.entries.add(e_normal)
    await test_uow.entries.add(e_vault)
    await test_uow.commit()

    # Retention count without include_vaulted: should count only normal
    counts_excl = await test_uow.entries.get_retention_counts(
        older_than_days=365, include_vaulted=False
    )
    assert counts_excl["candidates_count"] == 1
    assert counts_excl["vaulted_count"] == 1

    # Retention count with include_vaulted: should count both
    counts_incl = await test_uow.entries.get_retention_counts(
        older_than_days=365, include_vaulted=True
    )
    assert counts_incl["candidates_count"] == 2

    # Purge with include_vaulted=True and hard_delete=True
    purged = await test_uow.entries.purge_old_entries(
        older_than_days=365,
        hard_delete=True,
        include_vaulted=True,
    )
    assert purged == 2
    await test_uow.commit()

    # Verify both are permanently deleted from database disk (ORM and raw SQL level)
    check_normal = await test_uow.session.get(EntryModel, str(normal_id))
    check_vault = await test_uow.session.get(EntryModel, str(vaulted_id))
    assert check_normal is None
    assert check_vault is None

    from sqlalchemy import text

    raw_check = await test_uow.session.execute(
        text("SELECT count(*) FROM entries WHERE id IN (:id1, :id2)"),
        {"id1": str(normal_id), "id2": str(vaulted_id)},
    )
    assert raw_check.scalar() == 0


@pytest.mark.asyncio
async def test_purge_all_data_zero_days(test_uow):
    """Verify that older_than_days=0 purges all active entries up to current time."""
    entry_id = uuid4()
    e = Entry(
        id=entry_id,
        source_id=uuid4(),
        title="Recent Active Entry",
        url="https://example.com/recent",
        content_hash="hash-recent-1",
        category=Category.AI_TECH,
        published_at=datetime.now(UTC),
    )
    await test_uow.entries.add(e)
    await test_uow.commit()

    # Purge with older_than_days=0
    purged = await test_uow.entries.purge_old_entries(
        older_than_days=0,
        hard_delete=False,
        include_vaulted=True,
    )
    assert purged >= 1
    await test_uow.commit()

    # Verify entry is marked soft-purged
    model = await test_uow.session.get(EntryModel, str(entry_id))
    assert model is not None
    assert model.is_purged is True


@pytest.mark.asyncio
async def test_ingestion_freshness_guard_skips_stale_articles(test_uow):
    """Verify that fetch_source discards articles published older than max_ingest_age_days."""
    from ai_security_monitor.application.services.monitor_service import MonitorService
    from ai_security_monitor.domain.entities import Source, SourceType
    from ai_security_monitor.infrastructure.fetchers.base import FetchResult

    service = MonitorService(lambda: test_uow)

    source = Source(
        id=uuid4(),
        name="Test Feed Source",
        category=Category.AI_TECH,
        type=SourceType.RSS,
        url="https://example.com/feed.xml",
    )
    await test_uow.sources.add(source)
    await test_uow.commit()

    now = datetime.now(UTC)
    stale_date = now - timedelta(days=200)  # > 90 days default
    fresh_date = now - timedelta(days=5)

    stale_entry = Entry(
        id=uuid4(),
        source_id=source.id,
        title="Ancient Archive Article from 200 days ago",
        url="https://example.com/ancient",
        content_hash="hash-ancient-1",
        published_at=stale_date,
        category=Category.AI_TECH,
    )
    fresh_entry = Entry(
        id=uuid4(),
        source_id=source.id,
        title="Brand New Release Article",
        url="https://example.com/fresh",
        content_hash="hash-fresh-1",
        published_at=fresh_date,
        category=Category.AI_TECH,
    )

    from ai_security_monitor.domain.entities import FetchStatus

    mock_fetcher = MagicMock()
    mock_fetcher.fetch = AsyncMock(
        return_value=FetchResult(
            entries=[stale_entry, fresh_entry],
            entries_total=2,
            entries_new=2,
            status=FetchStatus.SUCCESS,
        )
    )

    with patch(
        "ai_security_monitor.infrastructure.fetchers.fetcher_registry.get",
        return_value=lambda s: mock_fetcher,
    ):
        log = await service.fetch_source(source)
        # Only fresh_entry should have been ingested, stale_entry skipped!
        assert log.entries_new == 1

        # Check DB: fresh_entry must exist, stale_entry must NOT exist
        fresh_in_db = await test_uow.entries.get_by_content_hash("hash-fresh-1")
        stale_in_db = await test_uow.entries.get_by_content_hash("hash-ancient-1")
        assert fresh_in_db is not None
        assert stale_in_db is None


@pytest.mark.asyncio
async def test_get_stats_excludes_soft_purged_entries(test_uow):
    """Verify that get_stats strictly excludes soft-purged entries from totals and category counts."""
    from ai_security_monitor.application.services.monitor_service import MonitorService

    service = MonitorService(lambda: test_uow)

    stats_initial = await service.get_stats()
    init_total = stats_initial["total_entries"]

    e1 = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Active Entry One",
        url="https://example.com/test-e1",
        content_hash="hash-e1-stats",
        category=Category.AI_RESEARCH,
        published_at=datetime.now(UTC),
    )
    e2 = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Active Entry Two",
        url="https://example.com/test-e2",
        content_hash="hash-e2-stats",
        category=Category.AI_RESEARCH,
        published_at=datetime.now(UTC) - timedelta(days=20),
    )
    await test_uow.entries.add(e1)
    await test_uow.entries.add(e2)
    await test_uow.commit()

    stats_after_add = await service.get_stats()
    assert stats_after_add["total_entries"] == init_total + 2

    broadcast_events: list[dict] = []
    service.set_broadcast_callback(lambda msg: broadcast_events.append(msg))

    # Purge entries older than 10 days
    purged_res = await service.purge_stale_entries(older_than_days=10)
    assert purged_res["purged"] >= 1
    assert any(ev.get("type") == "feed_updated" for ev in broadcast_events)

    stats_after_purge = await service.get_stats()
    # stats total MUST have dropped!
    assert stats_after_purge["total_entries"] == stats_after_add["total_entries"] - purged_res["purged"]

    broadcast_events.clear()
    # Restore all soft-purged
    await service.restore_purged_entries()
    assert any(ev.get("type") == "feed_updated" for ev in broadcast_events)
    stats_after_restore = await service.get_stats()
    assert stats_after_restore["total_entries"] == stats_after_add["total_entries"]



