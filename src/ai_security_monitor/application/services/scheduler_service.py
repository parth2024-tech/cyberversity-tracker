"""
Application scheduler service for periodic intelligence sweeps.
"""
from __future__ import annotations

import asyncio

from ai_security_monitor.application.services.monitor_service import MonitorService
from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


class SchedulerService:
    """Manages background polling loop for real-time intelligence feeds."""

    def __init__(self, monitor_service: MonitorService | None = None):
        self._monitor = monitor_service or MonitorService()
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start periodic background radar sweeps."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Background radar scheduler service started")

    async def stop(self) -> None:
        """Stop background sweeps."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Background radar scheduler service stopped")

    async def _loop(self) -> None:
        """Periodic sweep loop."""
        # Initial wait before starting first sweep
        await asyncio.sleep(5)

        interval = max(60, settings.scheduler.fetch_interval_minutes * 60)

        while self._running:
            try:
                logger.info("Executing scheduled intelligence radar sweep...")
                results = await self._monitor.fetch_all()
                logger.info(f"Scheduled sweep complete: {results.get('total_new', 0)} new items ingested.")
            except Exception as e:
                logger.error(f"Scheduler execution error: {e}")

            await asyncio.sleep(interval)
