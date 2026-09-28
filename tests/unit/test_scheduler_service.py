"""Unit tests for SchedulerService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_security_monitor.application.services.scheduler_service import SchedulerService
from ai_security_monitor.config.settings import settings


@pytest.fixture
def mock_monitor_service() -> MagicMock:
    svc = MagicMock()
    svc.fetch_all = AsyncMock(
        return_value={
            "sources_fetched": 3,
            "total_new": 10,
            "success": 2,
            "total_sources": 3,
        }
    )
    svc.purge_stale_entries = AsyncMock(return_value={"purged": 5})
    return svc


@pytest.fixture
def mock_newspaper_service() -> MagicMock:
    svc = MagicMock()
    svc.generate_edition = AsyncMock(
        return_value={
            "edition_number": 1001,
            "total_stories": 50,
            "md_path": "/tmp/edition_1001.md",
            "pdf_path": "/tmp/edition_1001.pdf",
            "lead_story": "Global AI Models Benchmark Released",
        }
    )
    return svc


@pytest.fixture
def scheduler(
    mock_monitor_service: MagicMock, mock_newspaper_service: MagicMock
) -> SchedulerService:
    return SchedulerService(
        monitor_service=mock_monitor_service,
        newspaper_service=mock_newspaper_service,
    )


def test_scheduler_initial_state(scheduler: SchedulerService):
    """Scheduler should start in a stopped, not-running state."""
    assert not scheduler._running
    assert scheduler._task is None
    assert scheduler._newspaper_task is None
    assert scheduler._backup_task is None


@pytest.mark.asyncio
async def test_scheduler_start_sets_running_flag(scheduler: SchedulerService):
    """start() should set _running flag and create background tasks."""
    with (
        patch.object(scheduler, "_loop", new=AsyncMock()),
        patch.object(scheduler, "_newspaper_loop", new=AsyncMock()),
        patch.object(scheduler, "_backup_loop", new=AsyncMock()),
    ):
        await scheduler.start()
        assert scheduler._running
        assert scheduler._task is not None
        assert scheduler._newspaper_task is not None
        assert scheduler._backup_task is not None
        await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_stop_sets_running_false(scheduler: SchedulerService):
    """stop() should cancel tasks and set _running to False."""
    with (
        patch.object(scheduler, "_loop", new=AsyncMock()),
        patch.object(scheduler, "_newspaper_loop", new=AsyncMock()),
        patch.object(scheduler, "_backup_loop", new=AsyncMock()),
    ):
        await scheduler.start()
        await scheduler.stop()

    assert not scheduler._running


@pytest.mark.asyncio
async def test_scheduler_start_is_idempotent(scheduler: SchedulerService):
    """Calling start() twice should not create duplicate tasks."""
    with (
        patch.object(scheduler, "_loop", new=AsyncMock()),
        patch.object(scheduler, "_newspaper_loop", new=AsyncMock()),
        patch.object(scheduler, "_backup_loop", new=AsyncMock()),
    ):
        await scheduler.start()
        task1 = scheduler._task
        await scheduler.start()  # Second call
        task2 = scheduler._task
        assert task1 is task2  # Same task object
        await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_stop_is_safe_when_not_started(scheduler: SchedulerService):
    """Calling stop() when never started should not raise any exception."""
    await scheduler.stop()  # Should be harmless
    assert not scheduler._running


@pytest.mark.asyncio
async def test_scheduler_loop_execution(
    scheduler: SchedulerService, mock_monitor_service: MagicMock
):
    """_loop should execute fetch_all and purge if auto_purge_enabled."""
    scheduler._running = True
    call_count = 0

    async def fake_sleep(duration: float):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            scheduler._running = False

    with (
        patch("asyncio.sleep", side_effect=fake_sleep),
        patch.object(settings.database, "auto_purge_enabled", True),
        patch.object(settings.database, "retention_days", 14),
    ):
        await scheduler._loop()

    mock_monitor_service.fetch_all.assert_awaited_once()
    mock_monitor_service.purge_stale_entries.assert_awaited_once_with(
        older_than_days=14
    )
    assert scheduler._sweep_count >= 1


@pytest.mark.asyncio
async def test_scheduler_loop_handles_exception(
    scheduler: SchedulerService, mock_monitor_service: MagicMock
):
    """_loop should catch and log exceptions without crashing."""
    scheduler._running = True
    mock_monitor_service.fetch_all.side_effect = RuntimeError("Network error")
    call_count = 0

    async def fake_sleep(duration: float):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            scheduler._running = False

    with patch("asyncio.sleep", side_effect=fake_sleep):
        await scheduler._loop()

    mock_monitor_service.fetch_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_newspaper_loop_execution_without_delivery(
    scheduler: SchedulerService, mock_newspaper_service: MagicMock
):
    """_newspaper_loop should compile edition and skip dispatch when delivery disabled."""
    scheduler._running = True
    call_count = 0

    async def fake_sleep(duration: float):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            scheduler._running = False

    with (
        patch("asyncio.sleep", side_effect=fake_sleep),
        patch.object(settings.delivery, "email_enabled", False),
        patch.object(settings.delivery, "telegram_enabled", False),
    ):
        await scheduler._newspaper_loop()

    mock_newspaper_service.generate_edition.assert_awaited_once_with(window_hours=5)


@pytest.mark.asyncio
async def test_newspaper_loop_with_email_delivery(
    scheduler: SchedulerService, mock_newspaper_service: MagicMock
):
    """_newspaper_loop should dispatch via email when enabled and permitted."""
    scheduler._running = True
    call_count = 0

    async def fake_sleep(duration: float):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            scheduler._running = False

    mock_email_del = MagicMock()
    mock_email_del.send_newspaper_pdf = AsyncMock(return_value=MagicMock(success=True))

    with (
        patch("asyncio.sleep", side_effect=fake_sleep),
        patch.object(settings.delivery, "email_enabled", True),
        patch.object(settings.delivery, "email_to", "team@example.com"),
        patch.object(settings.delivery, "telegram_enabled", False),
        patch(
            "ai_security_monitor.application.services.newspaper_delivery_tracker.delivery_tracker.should_dispatch",
            return_value=(True, "Allowed"),
        ),
        patch(
            "ai_security_monitor.application.services.newspaper_delivery_tracker.delivery_tracker.record_dispatch"
        ) as mock_record,
        patch(
            "ai_security_monitor.infrastructure.delivery.base.delivery_registry.create",
            return_value=mock_email_del,
        ),
    ):
        await scheduler._newspaper_loop()

    mock_email_del.send_newspaper_pdf.assert_awaited_once()
    mock_record.assert_called_once()


@pytest.mark.asyncio
async def test_newspaper_loop_with_telegram_delivery(
    scheduler: SchedulerService, mock_newspaper_service: MagicMock
):
    """_newspaper_loop should dispatch via telegram when enabled and permitted."""
    scheduler._running = True
    call_count = 0

    async def fake_sleep(duration: float):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            scheduler._running = False

    mock_tg_del = MagicMock()
    mock_tg_del.send_newspaper_document = AsyncMock(
        return_value=MagicMock(success=True)
    )

    with (
        patch("asyncio.sleep", side_effect=fake_sleep),
        patch.object(settings.delivery, "email_enabled", False),
        patch.object(settings.delivery, "telegram_enabled", True),
        patch.object(settings.delivery, "telegram_bot_token", "test-token"),
        patch.object(settings.delivery, "telegram_chat_id", "123456"),
        patch(
            "ai_security_monitor.application.services.newspaper_delivery_tracker.delivery_tracker.should_dispatch",
            return_value=(True, "Allowed"),
        ),
        patch(
            "ai_security_monitor.application.services.newspaper_delivery_tracker.delivery_tracker.record_dispatch"
        ) as mock_record,
        patch(
            "ai_security_monitor.infrastructure.delivery.base.delivery_registry.create",
            return_value=mock_tg_del,
        ),
    ):
        await scheduler._newspaper_loop()

    mock_tg_del.send_newspaper_document.assert_awaited_once()
    mock_record.assert_called_once()


@pytest.mark.asyncio
async def test_backup_loop_creates_backup_and_prunes(
    scheduler: SchedulerService, tmp_path
):
    """_backup_loop should run online sqlite backup and prune old backups."""
    scheduler._running = True
    db_file = tmp_path / "test_app.db"
    db_file.write_text("sqlite placeholder")
    call_count = 0

    async def fake_sleep(duration: float):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            scheduler._running = False

    async def fake_to_thread(func, src, dst):
        dst.write_text("sqlite backup content")

    with (
        patch("asyncio.sleep", side_effect=fake_sleep),
        patch.object(settings.database, "url", f"sqlite:///{db_file}"),
        patch.object(settings.database, "backup_interval_hours", 1),
        patch.object(settings.database, "backup_retention_copies", 2),
        patch("asyncio.to_thread", side_effect=fake_to_thread),
    ):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        # Create 3 fake backup files to test retention pruning
        b1 = backup_dir / "monitor_backup_20260101_000000.db"
        b2 = backup_dir / "monitor_backup_20260102_000000.db"
        b3 = backup_dir / "monitor_backup_20260103_000000.db"
        b1.write_text("b1")
        b2.write_text("b2")
        b3.write_text("b3")

        await scheduler._backup_loop()

    assert not b1.exists()  # Oldest should be pruned since retention is 2
