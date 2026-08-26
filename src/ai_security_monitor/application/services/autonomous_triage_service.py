"""
Autonomous High-Priority LLM Triage Service and Background Queue.
Continuously triages high-velocity threats, Pre-CVE research, and Watchlist matches using local LLMs.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Analysis, AnalysisModel, Entry
from ai_security_monitor.domain.repositories import EntryFilters
from ai_security_monitor.infrastructure.analyzers.llm_analyzer import LLMAnalyzer
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.infrastructure.delivery.base import delivery_registry

logger = get_logger(__name__)


class AutonomousTriageService:
    """Manages the autonomous LLM triage priority queue and worker daemon."""

    def __init__(self, uow_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None):
        self._uow_factory = uow_factory or (lambda: SqlAlchemyUnitOfWork())
        self._queue: asyncio.Queue[UUID] = asyncio.Queue()
        self._queued_ids: set[UUID] = set()
        self._worker_task: asyncio.Task | None = None
        self._running = False
        self._is_processing = False
        self._current_entry_title: str | None = None
        self._total_enqueued = 0
        self._total_completed = 0
        self._total_failed = 0
        self._broadcast_callback: Callable[[dict], None] | None = None

    def set_broadcast_callback(self, cb: Callable[[dict], None]) -> None:
        """Set callback for broadcasting live triage events over WebSockets."""
        self._broadcast_callback = cb

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def get_status(self) -> dict:
        """Get live telemetry about the autonomous triage pipeline."""
        return {
            "enabled": settings.analyzer.autonomous_triage_enabled,
            "running": self._running,
            "is_processing": self._is_processing,
            "current_entry": self._current_entry_title,
            "queue_size": self._queue.qsize(),
            "total_enqueued": self._total_enqueued,
            "total_completed": self._total_completed,
            "total_failed": self._total_failed,
            "model": settings.analyzer.ollama_model,
        }

    async def enqueue(self, entry_id: UUID) -> bool:
        """Enqueue an entry for deep LLM triage (deduplicated)."""
        if entry_id in self._queued_ids:
            return False

        self._queued_ids.add(entry_id)
        await self._queue.put(entry_id)
        self._total_enqueued += 1
        logger.info(f"Enqueued entry {entry_id} for autonomous LLM triage (queue depth: {self._queue.qsize()})")

        # Broadcast queue update
        if self._broadcast_callback:
            try:
                self._broadcast_callback({
                    "type": "triage_queue_updated",
                    "data": self.get_status()
                })
            except Exception as e:
                logger.warn(f"WebSocket broadcast error: {e}")

        return True

    async def backfill_high_priority(self, limit: int = 15) -> int:
        """Find highest-velocity un-triaged entries in DB and enqueue them."""
        async with self._uow_factory() as uow:
            # Query top unanalyzed or heuristic high-velocity entries
            filters = EntryFilters(high_velocity_only=True)
            entries = await uow.entries.list(filters=filters)

        enqueued_count = 0
        for entry in entries:
            # If already triaged by real LLM, skip
            if entry.analysis and entry.analysis.model != AnalysisModel.HEURISTIC:
                continue

            if await self.enqueue(entry.id):
                enqueued_count += 1
                if enqueued_count >= limit:
                    break

        logger.info(f"Backfill enqueued {enqueued_count} high-priority entries for LLM triage.")
        return enqueued_count

    async def start(self) -> None:
        """Start the background triage worker."""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Autonomous High-Priority LLM Triage Worker started.")

    async def stop(self) -> None:
        """Stop the background triage worker."""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Autonomous High-Priority LLM Triage Worker stopped.")

    async def _worker_loop(self) -> None:
        """Worker loop processing entries one by one from the queue."""
        analyzer = LLMAnalyzer(config={"provider": "ollama"})

        while self._running:
            try:
                entry_id = await self._queue.get()
                self._is_processing = True

                try:
                    await self._process_entry(entry_id, analyzer)
                    self._total_completed += 1
                except Exception as proc_err:
                    logger.error(f"Error processing autonomous triage for {entry_id}: {proc_err}")
                    self._total_failed += 1
                finally:
                    self._queued_ids.discard(entry_id)
                    self._queue.task_done()
                    self._is_processing = False
                    self._current_entry_title = None

                    # Broadcast status update
                    if self._broadcast_callback:
                        try:
                            self._broadcast_callback({
                                "type": "triage_queue_updated",
                                "data": self.get_status()
                            })
                        except Exception:
                            pass

                # Delay between inference jobs to protect hardware
                await asyncio.sleep(settings.analyzer.triage_interval_seconds)

            except asyncio.CancelledError:
                break
            except Exception as loop_err:
                logger.error(f"Triage worker unexpected loop error: {loop_err}")
                await asyncio.sleep(2)

    async def _process_entry(self, entry_id: UUID, analyzer: LLMAnalyzer) -> None:
        """Execute deep LLM analysis and persist results."""
        async with self._uow_factory() as uow:
            entry = await uow.entries.get(entry_id)
            if not entry:
                logger.warn(f"Entry {entry_id} not found for triage.")
                return

            self._current_entry_title = entry.title
            logger.info(f"🤖 Autonomous LLM Triage executing for: {entry.title[:60]}...")

            # Run LLM analysis
            analysis_result = await analyzer.analyze(entry)

            # Check if analysis record exists
            existing_analysis = await uow.analyses.get_by_entry(entry_id)

            if existing_analysis:
                existing_analysis.attack_vector = analysis_result.attack_vector
                existing_analysis.risk_assessment = analysis_result.risk_assessment
                existing_analysis.mitigation = analysis_result.mitigation
                existing_analysis.threat_velocity = analysis_result.threat_velocity
                existing_analysis.severity_index = analysis_result.severity_index
                existing_analysis.blast_radius_score = analysis_result.blast_radius_score
                existing_analysis.affected_ecosystem = analysis_result.affected_ecosystem
                existing_analysis.is_pre_cve_warning = analysis_result.is_pre_cve_warning
                existing_analysis.attack_archetype = analysis_result.attack_archetype
                existing_analysis.weaponization_potential = analysis_result.weaponization_potential
                existing_analysis.model = AnalysisModel.OLLAMA
                existing_analysis.updated_at = datetime.utcnow()
                await uow.analyses.update(existing_analysis)
                analysis = existing_analysis
            else:
                analysis = Analysis(
                    entry_id=entry_id,
                    attack_vector=analysis_result.attack_vector,
                    risk_assessment=analysis_result.risk_assessment,
                    mitigation=analysis_result.mitigation,
                    threat_velocity=analysis_result.threat_velocity,
                    severity_index=analysis_result.severity_index,
                    blast_radius_score=analysis_result.blast_radius_score,
                    affected_ecosystem=analysis_result.affected_ecosystem,
                    is_pre_cve_warning=analysis_result.is_pre_cve_warning,
                    attack_archetype=analysis_result.attack_archetype,
                    weaponization_potential=analysis_result.weaponization_potential,
                    model=AnalysisModel.OLLAMA,
                )
                await uow.analyses.add(analysis)

            await uow.commit()
            logger.info(f"✅ LLM Triage complete for {entry.title[:50]} (Model: {analysis.model.value})")

            # Broadcast real-time triage update over WebSockets
            if self._broadcast_callback:
                try:
                    self._broadcast_callback({
                        "type": "triage_completed",
                        "data": {
                            "entry_id": str(entry.id),
                            "title": entry.title,
                            "model": analysis.model.value,
                            "threat_velocity": analysis.threat_velocity,
                            "severity_index": analysis.severity_index,
                            "blast_radius_score": analysis.blast_radius_score,
                            "affected_ecosystem": analysis.affected_ecosystem,
                            "attack_archetype": analysis.attack_archetype,
                            "weaponization_potential": analysis.weaponization_potential,
                            "attack_vector": analysis.attack_vector,
                            "risk_assessment": analysis.risk_assessment,
                            "mitigation": analysis.mitigation,
                            "is_pre_cve_warning": analysis.is_pre_cve_warning,
                        }
                    })
                except Exception as ws_err:
                    logger.warn(f"WebSocket broadcast error: {ws_err}")

            # Send Telegram Alert if critical or Pre-CVE
            if settings.delivery.telegram_enabled and (analysis.threat_velocity >= 70 or analysis.is_pre_cve_warning):
                try:
                    telegram_delivery = delivery_registry.create("telegram", {
                        "bot_token": settings.delivery.telegram_bot_token,
                        "chat_id": settings.delivery.telegram_chat_id,
                    })
                    await telegram_delivery.send_alert(entry, analysis)
                    logger.info(f"Telegram alert dispatched for autonomous triage of {entry.title[:40]}")
                except Exception as tg_err:
                    logger.warn(f"Failed to dispatch Telegram alert for triage: {tg_err}")


# Global Singleton Instance
_triage_service_instance: AutonomousTriageService | None = None


def get_triage_service() -> AutonomousTriageService:
    """Get or initialize global AutonomousTriageService instance."""
    global _triage_service_instance
    if _triage_service_instance is None:
        _triage_service_instance = AutonomousTriageService()
    return _triage_service_instance
