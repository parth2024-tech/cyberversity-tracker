"""Unit tests for SchedulerService."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_security_monitor.application.services.scheduler_service import SchedulerService


@pytest.fixture
def mock_monitor_service() -> MagicMock:
    svc = MagicMock()
    svc.fetch_all = AsyncMock(return_value={"sources_fetched": 3, "total_new": 10, "success": 2, "total_sources": 3})
    svc.purge_stale_entries = AsyncMock(return_value={"purged": 0})
    return svc


@pytest.fixture
def mock_newspaper_service() -> MagicMock:
    svc = MagicMock()
    svc.generate_edition = AsyncMock(return_value={"edition_number": 1001, "total_stories": 50})
    return svc


@pytest.fixture
def scheduler(mock_monitor_service: MagicMock, mock_newspaper_service: MagicMock) -> SchedulerService:
    return SchedulerService(
        monitor_service=mock_monitor_service,
        newspaper_service=mock_newspaper_service,
    )


def test_scheduler_initial_state(scheduler: SchedulerService):
    """Scheduler should start in a stopped, not-running state."""
    assert not scheduler._running
    assert scheduler._task is None
    assert scheduler._newspaper_task is None


@pytest.mark.asyncio
async def test_scheduler_start_sets_running_flag(scheduler: SchedulerService):
    """start() should set _running flag and create background tasks."""
    with patch.object(scheduler, "_loop", new=AsyncMock()):
        with patch.object(scheduler, "_newspaper_loop", new=AsyncMock()):
            await scheduler.start()
            assert scheduler._running
            assert scheduler._task is not None
            assert scheduler._newspaper_task is not None
            await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_stop_sets_running_false(scheduler: SchedulerService):
    """stop() should cancel tasks and set _running to False."""
    with patch.object(scheduler, "_loop", new=AsyncMock()):
        with patch.object(scheduler, "_newspaper_loop", new=AsyncMock()):
            await scheduler.start()
            await scheduler.stop()

    assert not scheduler._running


@pytest.mark.asyncio
async def test_scheduler_start_is_idempotent(scheduler: SchedulerService):
    """Calling start() twice should not create duplicate tasks."""
    with patch.object(scheduler, "_loop", new=AsyncMock()):
        with patch.object(scheduler, "_newspaper_loop", new=AsyncMock()):
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
