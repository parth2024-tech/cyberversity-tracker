"""
Application scheduler service for periodic intelligence sweeps.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from ai_security_monitor.application.services.monitor_service import MonitorService
from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)

# Module-level: last sweep timestamp accessible to MonitorService.get_sweep_status()
_last_sweep_at: datetime | None = None


class SchedulerService:
    """Manages background polling loop for real-time intelligence feeds."""

    def __init__(self, monitor_service: MonitorService | None = None):
        self._monitor = monitor_service or MonitorService()
        self._task: asyncio.Task | None = None
        self._running = False
        self._sweep_count = 0  # Total sweeps since service start

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
        """Periodic sweep loop with automatic data hygiene."""
        global _last_sweep_at

        # Initial warm-up wait before first sweep
        await asyncio.sleep(5)

        interval = max(60, settings.scheduler.fetch_interval_minutes * 60)

        while self._running:
            try:
                logger.info("Executing scheduled intelligence radar sweep...")
                results = await self._monitor.fetch_all()
                _last_sweep_at = datetime.utcnow()
                self._sweep_count += 1

                logger.info(
                    f"Sweep #{self._sweep_count} complete: "
                    f"{results.get('total_new', 0)} new items from "
                    f"{results.get('success', 0)}/{results.get('total_sources', 0)} sources."
                )

                # Nightly data hygiene purge:
                # At 30-min intervals, every 48 sweeps ≈ 24 hours.
                if self._sweep_count % max(1, 48) == 0:
                    try:
                        purge_result = await self._monitor.purge_stale_entries(older_than_days=30)
                        logger.info(
                            f"Data hygiene: purged {purge_result['purged']} entries "
                            f"older than {purge_result['older_than_days']} days."
                        )
                    except Exception as purge_err:
                        logger.warning(f"Data hygiene purge failed: {purge_err}")

            except Exception as e:
                logger.error(f"Scheduler execution error: {e}")

            await asyncio.sleep(interval)
