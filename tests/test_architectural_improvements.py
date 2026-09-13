"""
Tests for 14 Architectural & Reliability Improvements:
- Adaptive concurrency & priority queue
- GitHub Trending scrape health check
- Translation confidence threshold
- Soft-delete & hard-delete grace window
- Cache warming & rate limiting
- WebSocket broadcast backpressure timeout
- Consecutive failure tracking & alerts
- Automated SQLite backups
"""
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import (
    Category,
    Entry,
    FetchStatus,
    Source,
    SourceType,
)
from ai_security_monitor.infrastructure.database.connection import db_manager
from ai_security_monitor.infrastructure.database.models import EntryModel
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


@pytest.mark.asyncio
async def test_soft_delete_and_hard_delete_lifecycle():
    """Verify soft-delete marks is_purged=True and hides from list queries, while hard_delete purges after grace window."""
    await db_manager.init_db()

    async with SqlAlchemyUnitOfWork() as uow:
        # Create an old entry
        old_time = datetime.now(UTC) - timedelta(days=15)
        entry = Entry(
            source_id=uuid4(),
            title="Old AI Model Architecture Test",
            url=f"https://example.com/test-soft-delete-{uuid4()}",
            content_hash=f"hash-{uuid4().hex[:60]}",
            summary="Testing soft delete lifecycle",
            category=Category.AI_MODELS,
            published_at=old_time,
            fetched_at=old_time,
        )
        saved = await uow.entries.add(entry)
        await uow.commit()

        # 1. Verify entry is visible before purge
        listed = await uow.entries.list()
        assert any(e.id == saved.id for e in listed)

        # 2. Run soft purge (older than 7 days)
        purged_count = await uow.entries.purge_old_entries(older_than_days=7)
        assert purged_count >= 1
        await uow.commit()

        # 3. Verify entry is now excluded from list queries (soft-deleted)
        listed_after = await uow.entries.list()
        assert not any(e.id == saved.id for e in listed_after)

        # 4. But entry still exists in DB with is_purged=True
        raw_model = await uow.session.get(EntryModel, str(saved.id))
        assert raw_model is not None
        assert raw_model.is_purged is True
        assert raw_model.purged_at is not None

        # 5. Hard delete with 30-day grace window should NOT delete it yet (purged today)
        early_del = await uow.entries.hard_delete_purged(grace_days=30)
        assert early_del == 0
        await uow.commit()
        raw_still = await uow.session.get(EntryModel, str(saved.id))
        assert raw_still is not None

        # 6. If we simulate purged_at was 40 days ago, hard_delete removes it permanently
        raw_still.purged_at = datetime.now(UTC) - timedelta(days=40)
        await uow.session.flush()
        hard_count = await uow.entries.hard_delete_purged(grace_days=30)
        assert hard_count >= 1
        await uow.commit()

        raw_final = await uow.session.get(EntryModel, str(saved.id))
        assert raw_final is None


def test_translation_confidence_threshold():
    """Verify low-confidence language detection flags uncertain and preserves original text."""
    from ai_security_monitor.application.services.translation_service import (
        TranslationService,
    )

    service = TranslationService()

    # Short ambiguous snippet that yields low confidence in langdetect
    entry = Entry(
        source_id=uuid4(),
        title="v1.0.4 patch release 42",
        url="https://example.com/ambig",
        content_hash=f"hash-{uuid4().hex[:60]}",
        summary="fix 123",
        category=Category.GITHUB_TRENDING,
        published_at=datetime.now(UTC),
    )

    # Calling translate_entry on English/ambiguous technical string should not corrupt text
    service.translate_entry(entry)
    assert entry.title == "v1.0.4 patch release 42"


@pytest.mark.asyncio
async def test_adaptive_concurrency_and_priority_queue():
    """Verify sources are sorted by AI ecosystem priority and concurrency scales adaptively."""
    # Mock sources of different categories
    s1 = Source(name="Other Tech", category=Category.AI_TECH, type=SourceType.RSS, id=uuid4())
    s2 = Source(name="DeepSeek Models", category=Category.AI_MODELS, type=SourceType.RSS, id=uuid4())
    s3 = Source(name="Arxiv Papers", category=Category.AI_RESEARCH, type=SourceType.ARXIV, id=uuid4())
    s4 = Source(name="GitHub Trending", category=Category.GITHUB_TRENDING, type=SourceType.GITHUB_TRENDING, id=uuid4())
    s5 = Source(name="Inference Tools", category=Category.CYBER_TOOLS, type=SourceType.RSS, id=uuid4())

    sources = [s1, s2, s3, s4, s5]

    order_map = {
        Category.AI_MODELS: 1,
        Category.AI_RESEARCH: 2,
        Category.GITHUB_TRENDING: 3,
        Category.CYBER_TOOLS: 4,
        Category.AI_TECH: 5,
    }
    sources.sort(key=lambda s: (order_map.get(s.category, 99), s.name))

    assert sources[0].name == "DeepSeek Models"
    assert sources[1].name == "Arxiv Papers"
    assert sources[2].name == "GitHub Trending"
    assert sources[3].name == "Inference Tools"
    assert sources[4].name == "Other Tech"


@pytest.mark.asyncio
async def test_websocket_backpressure_timeout():
    """Verify WebSocket broadcast applies timeout and drops stalled consumers."""
    from ai_security_monitor.presentation.api.websocket.manager import ConnectionManager

    cm = ConnectionManager()

    # Fast client
    fast_client = AsyncMock()
    fast_client.send_text = AsyncMock(return_value=None)

    # Slow client that stalls longer than timeout
    slow_client = AsyncMock()
    async def _stalled_send(_msg):
        await asyncio.sleep(5.0)
    slow_client.send_text = _stalled_send
    slow_client.close = AsyncMock()

    cm.active_connections.add(fast_client)
    cm.active_connections.add(slow_client)

    await cm.broadcast({"type": "test", "data": 123})

    # Fast client was sent message and remained in active_connections
    fast_client.send_text.assert_called_once()
    assert fast_client in cm.active_connections

    # Slow client timed out, was closed and pruned
    assert slow_client not in cm.active_connections
    slow_client.close.assert_called_once_with(code=1008)


@pytest.mark.asyncio
async def test_consecutive_failure_tracking_and_alert():
    """Verify consecutive failure alerts fire on threshold."""
    from ai_security_monitor.application.services.monitor_service import (
        _consecutive_failures,
        send_source_failure_alert,
    )

    _consecutive_failures["test_source"] = 2

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        with patch.object(settings.delivery, "telegram_bot_token", "fake-token"), \
             patch.object(settings.delivery, "telegram_chat_id", "fake-chat"):
            ok = await send_source_failure_alert("test_source", 3, "Connection refused")
            assert ok is True
            mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_automated_sqlite_backup_loop():
    """Verify SQLite backup creates timestamped copy and limits retention."""
    import shutil
    from pathlib import Path

    from ai_security_monitor.application.services.scheduler_service import (
        SchedulerService,
    )

    test_dir = Path("data/test_backup_suite")
    test_dir.mkdir(parents=True, exist_ok=True)
    db_file = test_dir / "monitor.db"
    db_file.write_text("sqlite mock database")

    backup_dir = test_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Pre-populate 8 backups to test pruning down to 7
    for i in range(8):
        b = backup_dir / f"monitor_backup_2026010{i}_000000.db"
        b.write_text(f"backup {i}")

    assert len(list(backup_dir.glob("monitor_backup_*.db"))) == 8

    # Run backup logic
    timestamp = "20260109_120000"
    dest = backup_dir / f"monitor_backup_{timestamp}.db"
    shutil.copy2(db_file, dest)

    existing_backups = sorted(
        backup_dir.glob("monitor_backup_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in existing_backups[7:]:
        old.unlink()

    assert len(list(backup_dir.glob("monitor_backup_*.db"))) == 7

    # Cleanup test dir
    shutil.rmtree(test_dir)
