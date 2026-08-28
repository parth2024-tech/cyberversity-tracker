"""
Application scheduler service for periodic intelligence sweeps.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from ai_security_monitor.application.services.monitor_service import MonitorService
from ai_security_monitor.application.services.newspaper_service import NewspaperService
from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)

# Module-level: last sweep timestamp accessible to MonitorService.get_sweep_status()
_last_sweep_at: datetime | None = None


class SchedulerService:
    """Manages background polling loop for real-time intelligence feeds and 5-hour newspapers."""

    def __init__(
        self,
        monitor_service: MonitorService | None = None,
        newspaper_service: NewspaperService | None = None,
    ):
        self._monitor = monitor_service or MonitorService()
        self._newspaper = newspaper_service or NewspaperService()
        self._task: asyncio.Task | None = None
        self._newspaper_task: asyncio.Task | None = None
        self._running = False
        self._sweep_count = 0  # Total sweeps since service start

    async def start(self) -> None:
        """Start periodic background radar sweeps and 5-hour newspaper compiler."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._loop())
        self._newspaper_task = asyncio.create_task(self._newspaper_loop())
        logger.info("Background radar scheduler & 5-hour newspaper compiler started")

    async def stop(self) -> None:
        """Stop background sweeps and newspaper compiler."""
        self._running = False
        for task in (self._task, self._newspaper_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("Background radar scheduler and newspaper compiler stopped")

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

    async def _newspaper_loop(self) -> None:
        """Periodic 5-hour loop generating authentic Newspaper Intelligence Documents."""
        # Initial 10-second warm-up: ensures first edition is published quickly on server boot
        await asyncio.sleep(10)
        five_hours_seconds = 5 * 3600

        while self._running:
            try:
                logger.info("Executing scheduled 5-hour Newspaper Chronicle compilation...")
                meta = await self._newspaper.generate_edition(window_hours=5)
                logger.info(
                    f"Published Newspaper Edition #{meta['edition_number']} "
                    f"({meta['total_threats']} threats compiled into {meta['md_path']})"
                )

                # Auto-email PDF if email delivery is enabled
                if settings.delivery.email_enabled and settings.delivery.email_to:
                    try:
                        from ai_security_monitor.infrastructure.delivery.base import delivery_registry
                        email_delivery = delivery_registry.create("email", {
                            "smtp_server": settings.delivery.email_smtp_server,
                            "smtp_port": settings.delivery.email_smtp_port,
                            "username": settings.delivery.email_username or "",
                            "password": settings.delivery.email_password or "",
                            "from_email": settings.delivery.email_from or settings.delivery.email_username or "noreply@aetherguard.ai",
                            "to_email": settings.delivery.email_to,
                        })
                        pdf_path = meta.get("pdf_path")
                        if pdf_path:
                            email_res = await email_delivery.send_newspaper_pdf(
                                pdf_path=pdf_path,
                                edition_number=meta["edition_number"],
                                to_email=settings.delivery.email_to,
                                lead_story=meta.get("lead_story", ""),
                                total_threats=meta.get("total_threats", 0),
                            )
                            if email_res.success:
                                logger.info(f"Auto-emailed Newspaper PDF Edition #{meta['edition_number']} to {settings.delivery.email_to}")
                            else:
                                logger.warning(f"Auto-email PDF delivery notice: {email_res.error}")
                    except Exception as mail_err:
                        logger.warning(f"Auto-email newspaper dispatch failed: {mail_err}")
            except Exception as e:
                logger.error(f"Error in 5-hour newspaper compilation loop: {e}")

            await asyncio.sleep(five_hours_seconds)

