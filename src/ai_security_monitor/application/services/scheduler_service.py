"""
Application scheduler service for periodic intelligence sweeps.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from ai_security_monitor.application.services.monitor_service import MonitorService
from ai_security_monitor.application.services.newspaper_delivery_tracker import (
    delivery_tracker,
)
from ai_security_monitor.application.services.newspaper_service import NewspaperService
from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)

# Module-level: last sweep timestamp and count accessible to MonitorService.get_sweep_status()
_last_sweep_at: datetime | None = None
_sweep_count: int = 0
_server_started_at: datetime = datetime.now(UTC)


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
        self._backup_task: asyncio.Task | None = None
        self._running = False
        self._sweep_count = 0  # Total sweeps since service start

    async def start(self) -> None:
        """Start periodic background radar sweeps, 5-hour newspaper compiler, and automated database backups."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._loop())
        self._newspaper_task = asyncio.create_task(self._newspaper_loop())
        self._backup_task = asyncio.create_task(self._backup_loop())
        logger.info(
            "Background radar scheduler, 5-hour newspaper compiler & auto-backup loop started"
        )

    async def stop(self) -> None:
        """Stop background sweeps, newspaper compiler, and backup tasks."""
        self._running = False
        for task in (self._task, self._newspaper_task, self._backup_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info(
            "Background radar scheduler, newspaper compiler and auto-backup stopped"
        )

    async def _loop(self) -> None:
        """Periodic sweep loop with automatic data hygiene."""
        global _last_sweep_at, _sweep_count

        # Initial warm-up wait before first sweep (3 seconds allows Uvicorn to bind cleanly)
        await asyncio.sleep(3)

        interval = max(60, settings.scheduler.fetch_interval_minutes * 60)

        while self._running:
            try:
                logger.info("Executing scheduled intelligence radar sweep...")
                results = await self._monitor.fetch_all()
                _last_sweep_at = datetime.now(UTC)
                _sweep_count += 1
                self._sweep_count = _sweep_count  # keep local copy in sync

                logger.info(
                    f"Sweep #{self._sweep_count} complete: "
                    f"{results.get('total_new', 0)} new items from "
                    f"{results.get('success', 0)}/{results.get('total_sources', 0)} sources."
                )

                # Rolling Data Retention Purge:
                # Disabled by default: data is preserved indefinitely until the user manually triggers a cleanup.
                if getattr(settings.database, "auto_purge_enabled", False):
                    try:
                        retention = settings.database.retention_days
                        purge_result = await self._monitor.purge_stale_entries(
                            older_than_days=retention
                        )
                        if purge_result.get("purged", 0) > 0:
                            logger.info(
                                f"Automatic retention hygiene: purged {purge_result['purged']} expired entries "
                                f"(retaining all intelligence strictly for {retention} days)."
                            )
                    except Exception as purge_err:
                        logger.warning(
                            f"Data hygiene retention purge failed: {purge_err}"
                        )
                else:
                    logger.debug(
                        "Automatic retention purge is disabled. Data is kept indefinitely until manually purged by user."
                    )

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
                logger.info(
                    "Executing scheduled 5-hour Newspaper Chronicle compilation..."
                )
                meta = await self._newspaper.generate_edition(window_hours=5)
                logger.info(
                    f"Published Newspaper Edition #{meta['edition_number']} "
                    f"({meta['total_threats']} threats compiled into {meta['md_path']})"
                )

                # Auto-email PDF if email delivery is enabled
                if settings.delivery.email_enabled and settings.delivery.email_to:
                    pdf_path = meta.get("pdf_path")
                    edition_num = meta["edition_number"]
                    lead_story = meta.get("lead_story", "")
                    stories_count = meta.get(
                        "total_stories", meta.get("total_threats", 0)
                    )

                    can_send, reason = delivery_tracker.should_dispatch(
                        channel="email",
                        edition_number=edition_num,
                        lead_story=lead_story,
                        min_cooldown_hours=4.0,
                    )
                    if can_send and pdf_path:
                        try:
                            from ai_security_monitor.infrastructure.delivery.base import (
                                delivery_registry,
                            )

                            email_delivery = delivery_registry.create(
                                "email",
                                {
                                    "smtp_server": settings.delivery.email_smtp_server,
                                    "smtp_port": settings.delivery.email_smtp_port,
                                    "username": settings.delivery.email_username or "",
                                    "password": settings.delivery.email_password or "",
                                    "from_email": settings.delivery.email_from
                                    or settings.delivery.email_username
                                    or "noreply@aetherguard.ai",
                                    "to_email": settings.delivery.email_to,
                                },
                            )
                            email_res = await email_delivery.send_newspaper_pdf(
                                pdf_path=pdf_path,
                                edition_number=edition_num,
                                to_email=settings.delivery.email_to,
                                lead_story=lead_story,
                                total_threats=stories_count,
                            )
                            if email_res.success:
                                delivery_tracker.record_dispatch(
                                    channel="email",
                                    edition_number=edition_num,
                                    lead_story=lead_story,
                                )
                                logger.info(
                                    f"Auto-emailed Newspaper PDF Edition #{edition_num} to {settings.delivery.email_to}"
                                )
                            else:
                                logger.warning(
                                    f"Auto-email PDF delivery notice: {email_res.error}"
                                )
                        except Exception as mail_err:
                            logger.warning(
                                f"Auto-email newspaper dispatch failed: {mail_err}"
                            )
                    else:
                        logger.info(f"Skipping scheduled Email dispatch: {reason}")

                # Auto-dispatch PDF to Telegram if configured
                tg_token = settings.delivery.telegram_bot_token
                tg_chat = settings.delivery.telegram_chat_id
                if settings.delivery.telegram_enabled and tg_token and tg_chat:
                    pdf_path = meta.get("pdf_path")
                    edition_num = meta["edition_number"]
                    lead_story = meta.get("lead_story", "")
                    stories_count = meta.get(
                        "total_stories", meta.get("total_threats", 0)
                    )

                    can_send, reason = delivery_tracker.should_dispatch(
                        channel="telegram",
                        edition_number=edition_num,
                        lead_story=lead_story,
                        min_cooldown_hours=4.0,
                    )
                    if can_send and pdf_path:
                        try:
                            from ai_security_monitor.infrastructure.delivery.base import (
                                delivery_registry,
                            )

                            tg_delivery = delivery_registry.create(
                                "telegram",
                                {
                                    "bot_token": tg_token,
                                    "chat_id": tg_chat,
                                },
                            )
                            tg_res = await tg_delivery.send_newspaper_document(
                                pdf_path=pdf_path,
                                edition_number=edition_num,
                                lead_story=lead_story,
                                total_threats=stories_count,
                            )
                            if tg_res.success:
                                delivery_tracker.record_dispatch(
                                    channel="telegram",
                                    edition_number=edition_num,
                                    lead_story=lead_story,
                                )
                                logger.info(
                                    f"Auto-delivered Newspaper PDF Edition #{edition_num} to Telegram chat {tg_chat}"
                                )
                            else:
                                logger.warning(
                                    f"Telegram PDF delivery notice: {tg_res.error}"
                                )
                        except Exception as tg_err:
                            logger.warning(
                                f"Auto-telegram newspaper dispatch failed: {tg_err}"
                            )
                    else:
                        logger.info(f"Skipping scheduled Telegram dispatch: {reason}")
            except Exception as e:
                logger.error(f"Error in 5-hour newspaper compilation loop: {e}")

            await asyncio.sleep(five_hours_seconds)

    async def _backup_loop(self) -> None:
        """Automated SQLite database backup every 12 hours with 7-version retention."""
        import shutil
        from pathlib import Path

        # Initial delay before first backup to let server start and database populate
        await asyncio.sleep(120)
        interval = getattr(settings.database, "backup_interval_hours", 12) * 3600
        retention_limit = getattr(settings.database, "backup_retention_copies", 60)

        while self._running:
            try:
                db_url = settings.database.url
                db_path_str = (
                    db_url.replace("sqlite+aiosqlite:///", "")
                    .replace("sqlite:///", "")
                    .split("?")[0]
                )
                db_file = Path(db_path_str)
                if db_file.exists() and db_file.is_file():
                    backup_dir = db_file.parent / "backups"
                    backup_dir.mkdir(parents=True, exist_ok=True)

                    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                    dest_file = backup_dir / f"monitor_backup_{timestamp}.db"

                    shutil.copy2(db_file, dest_file)
                    size_kb = dest_file.stat().st_size / 1024.0
                    logger.info(
                        f"Automated SQLite backup created: {dest_file.name} "
                        f"({size_kb:.1f} KB)"
                    )

                    # Retain rolling backups according to retention policy
                    existing_backups = sorted(
                        backup_dir.glob("monitor_backup_*.db"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    from ai_security_monitor.core.diagnostics import diagnostics

                    diagnostics.record_backup_completed(
                        filename=dest_file.name,
                        size_kb=size_kb,
                        retained_count=min(len(existing_backups), retention_limit),
                    )
                    for old_backup in existing_backups[retention_limit:]:
                        try:
                            old_backup.unlink()
                            logger.debug(
                                f"Pruned older database backup: {old_backup.name}"
                            )
                        except Exception:
                            pass
            except asyncio.CancelledError:
                break
            except Exception as backup_err:
                logger.warning(f"Automated database backup error: {backup_err}")

            await asyncio.sleep(interval)
