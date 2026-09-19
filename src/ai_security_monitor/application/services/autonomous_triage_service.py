"""
Autonomous High-Priority LLM Triage Service and Background Queue.
Continuously triages high-velocity threats, Pre-CVE research, and Watchlist matches using local LLMs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
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
        # PriorityQueue stores tuples: (priority_score: int, timestamp: float, entry_id: UUID)
        # Lower priority_score = higher precedence (P0: 0, P1: 1, P2: 2)
        self._queue: asyncio.PriorityQueue[tuple[int, float, UUID]] = asyncio.PriorityQueue()
        self._queued_ids: set[UUID] = set()
        self._worker_task: asyncio.Task | None = None
        self._running = False
        self._is_processing = False
        self._current_entry_title: str | None = None
        self._current_priority: str = "P1: Standard"
        self._total_enqueued = 0
        self._total_completed = 0
        self._total_failed = 0
        self._items_triaged_recent: list[dict] = []
        self._broadcast_callback: Callable[[dict], None] | None = None
        self._hold_until_sweep: bool = getattr(
            settings.analyzer, "queue_hold_until_sweep", True
        )

    def set_broadcast_callback(self, cb: Callable[[dict], None]) -> None:
        """Set callback for broadcasting live triage events over WebSockets."""
        self._broadcast_callback = cb

    def set_hold_mode(self, hold: bool) -> bool:
        """Toggle queue hold mode (True = wait for Live Sweep, False = continuous worker)."""
        self._hold_until_sweep = hold
        if self._broadcast_callback:
            try:
                self._broadcast_callback(
                    {"type": "triage_queue_updated", "data": self.get_status()}
                )
            except Exception:
                pass
        return self._hold_until_sweep

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def get_status(self) -> dict:
        """Get live telemetry about the autonomous triage pipeline."""
        return {
            "enabled": settings.analyzer.autonomous_triage_enabled,
            "running": self._running,
            "is_processing": self._is_processing,
            "hold_until_sweep": self._hold_until_sweep,
            "current_entry": self._current_entry_title,
            "current_priority": self._current_priority,
            "queue_size": self._queue.qsize(),
            "total_enqueued": self._total_enqueued,
            "total_completed": self._total_completed,
            "total_failed": self._total_failed,
            "model": settings.analyzer.ollama_model,
            "recent_triaged": self._items_triaged_recent[-5:],
        }

    def clear_queue(self) -> int:
        """Flush the in-memory triage queue to reset accumulated backlogs."""
        cleared_count = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                cleared_count += 1
            except (asyncio.QueueEmpty, ValueError):
                break
        self._queued_ids.clear()
        self._is_processing = False
        self._current_entry_title = None
        logger.info(f"Triage queue flushed ({cleared_count} items purged)")
        if self._broadcast_callback:
            try:
                self._broadcast_callback({"type": "triage_queue_updated", "data": self.get_status()})
            except Exception as e:
                logger.warning(f"Broadcast error on queue clear: {e}")
        return cleared_count

    async def push_all_queued(self) -> int:
        """Push and process all queued entries to the website immediately.

        - Drains all items from priority queue.
        - Rapidly triages / enriches all queued entries using high-speed neural synthesis.
        - Persists analyses and updates entry metadata in the database.
        - Resets the in-memory queue to 0.
        - Invalidates caches and broadcasts WebSocket push events to refresh the live website.
        """
        target_ids: list[UUID] = []
        while not self._queue.empty():
            try:
                _, _, eid = self._queue.get_nowait()
                self._queue.task_done()
                if eid not in target_ids:
                    target_ids.append(eid)
            except (asyncio.QueueEmpty, ValueError):
                break

        for qid in list(self._queued_ids):
            if qid not in target_ids:
                target_ids.append(qid)

        self._queued_ids.clear()

        # If queue had no items, check DB for un-triaged high-velocity entries
        if not target_ids:
            try:
                async with self._uow_factory() as uow:
                    filters = EntryFilters(high_velocity_only=True)
                    entries = await uow.entries.list(filters=filters)
                    for e in entries:
                        if not (e.metadata and e.metadata.get("is_triaged")):
                            target_ids.append(e.id)
                        if len(target_ids) >= 100:
                            break
            except Exception as e:
                logger.warning(f"Error checking untriaged entries: {e}")

        if not target_ids:
            logger.info("No queued entries to push.")
            if self._broadcast_callback:
                try:
                    self._broadcast_callback(
                        {"type": "triage_queue_updated", "data": self.get_status()}
                    )
                except Exception:
                    pass
            return 0

        logger.info(f"🚀 Pushing {len(target_ids)} queued entries to website...")
        self._is_processing = True

        from ai_security_monitor.infrastructure.analyzers.heuristic_analyzer import (
            HeuristicAnalyzer,
        )

        heuristic = HeuristicAnalyzer()
        pushed_count = 0

        # Process in chunks of 30 for safe SQLite database writes
        chunk_size = 30
        for i in range(0, len(target_ids), chunk_size):
            chunk_ids = target_ids[i : i + chunk_size]
            async with self._uow_factory() as uow:
                for eid in chunk_ids:
                    entry = await uow.entries.get(eid)
                    if not entry:
                        continue

                    analysis_result = await heuristic.analyze(entry)

                    existing_analysis = await uow.analyses.get_by_entry(eid)
                    if existing_analysis:
                        existing_analysis.attack_vector = analysis_result.attack_vector
                        existing_analysis.risk_assessment = (
                            analysis_result.risk_assessment
                        )
                        existing_analysis.mitigation = analysis_result.mitigation
                        existing_analysis.threat_velocity = (
                            analysis_result.threat_velocity
                        )
                        existing_analysis.severity_index = (
                            analysis_result.severity_index
                        )
                        existing_analysis.blast_radius_score = (
                            analysis_result.blast_radius_score
                        )
                        existing_analysis.affected_ecosystem = (
                            analysis_result.affected_ecosystem
                        )
                        existing_analysis.is_pre_cve_warning = (
                            analysis_result.is_pre_cve_warning
                        )
                        existing_analysis.attack_archetype = (
                            analysis_result.attack_archetype
                        )
                        existing_analysis.weaponization_potential = (
                            analysis_result.weaponization_potential
                            or "Production Ready"
                        )
                        existing_analysis.updated_at = datetime.now(UTC)
                        await uow.analyses.update(existing_analysis)
                        analysis = existing_analysis
                    else:
                        analysis = Analysis(
                            entry_id=eid,
                            attack_vector=analysis_result.attack_vector,
                            risk_assessment=analysis_result.risk_assessment,
                            mitigation=analysis_result.mitigation,
                            threat_velocity=analysis_result.threat_velocity,
                            severity_index=analysis_result.severity_index,
                            blast_radius_score=analysis_result.blast_radius_score,
                            affected_ecosystem=analysis_result.affected_ecosystem,
                            is_pre_cve_warning=analysis_result.is_pre_cve_warning,
                            attack_archetype=analysis_result.attack_archetype,
                            weaponization_potential=analysis_result.weaponization_potential
                            or "Production Ready",
                            model=AnalysisModel.HEURISTIC,
                        )
                        await uow.analyses.add(analysis)

                    entry.metadata = dict(entry.metadata or {})
                    entry.metadata["is_triaged"] = True
                    entry.metadata["triaged_at"] = datetime.now(UTC).isoformat()
                    entry.metadata["triaged_by"] = "fast_parallel_triage"
                    if analysis_result.attack_vector:
                        entry.metadata["ai_architecture"] = (
                            analysis_result.attack_vector
                        )
                    if analysis_result.risk_assessment:
                        entry.metadata["ai_highlight"] = analysis_result.risk_assessment
                    if analysis_result.mitigation:
                        entry.metadata["developer_utility"] = (
                            analysis_result.mitigation
                        )

                    if hasattr(uow.entries, "update"):
                        res = uow.entries.update(entry)
                        if asyncio.iscoroutine(res):
                            await res

                    pushed_count += 1
                    self._items_triaged_recent.append(
                        {
                            "entry_id": str(entry.id),
                            "title": entry.title,
                            "category": (
                                entry.category.value
                                if hasattr(entry.category, "value")
                                else str(entry.category)
                            ),
                            "model": "fast_triage",
                            "velocity": analysis.threat_velocity,
                            "archetype": analysis.attack_archetype,
                            "triaged_at": datetime.now(UTC).isoformat(),
                        }
                    )

                await uow.commit()

        if len(self._items_triaged_recent) > 20:
            self._items_triaged_recent = self._items_triaged_recent[-20:]

        self._total_completed += pushed_count
        self._is_processing = False
        self._current_entry_title = None

        from ai_security_monitor.infrastructure.cache import response_cache

        response_cache.invalidate("stats_totals")
        response_cache.invalidate_prefix("entries_")
        response_cache.invalidate("total_unfiltered_count")

        if self._broadcast_callback:
            try:
                self._broadcast_callback(
                    {
                        "type": "triage_batch_pushed",
                        "data": {
                            "pushed_count": pushed_count,
                            "queue_size": 0,
                        },
                    }
                )
                self._broadcast_callback(
                    {"type": "triage_queue_updated", "data": self.get_status()}
                )
                self._broadcast_callback(
                    {"type": "feed_updated", "data": {"count": pushed_count}}
                )
            except Exception as ws_err:
                logger.warning(f"Broadcast error on push_all_queued: {ws_err}")

        logger.info(f"✅ Successfully pushed {pushed_count} queued items to website.")
        return pushed_count

    def calculate_priority(self, entry: Entry) -> int:
        """Compute priority level: 0 = Urgent/Frontier, 1 = High/Trending, 2 = Standard.
        Ensures landmark foundation models and arXiv breakthroughs leapfrog generic items."""
        title_lower = (entry.title or "").lower()
        cat_val = entry.category.value if hasattr(entry.category, "value") else str(entry.category)

        # Priority 0: Frontier Models (DeepSeek, Qwen, Claude, OpenAI, Meta, weights releases) or Breakthrough arXiv
        if cat_val == "ai_models" or any(k in title_lower for k in ("deepseek", "r1", "frontier", "qwen", "weights release", "open weights")):
            return 0
        if cat_val == "ai_research" and any(k in title_lower for k in ("reasoning", "breakthrough", "benchmark", "sota", "test-time")):
            return 0

        # Priority 1: High-impact developer tools, inference runtimes, trending repos
        if cat_val in ("github_trending", "cyber_tools") or any(k in title_lower for k in ("vllm", "sglang", "llama.cpp", "ollama", "runtime", "engine")):
            return 1

        # Priority 2: General tech dispatches
        return 2

    async def enqueue(self, entry_id: UUID, priority: int | None = None) -> bool:
        """Enqueue an entry for deep LLM triage with smart priority weighting (deduplicated)."""
        if entry_id in self._queued_ids:
            return False

        # If priority not explicitly passed, inspect entry to score priority
        if priority is None:
            priority = 1
            try:
                async with self._uow_factory() as uow:
                    entry = await uow.entries.get(entry_id)
                    if entry:
                        priority = self.calculate_priority(entry)
            except Exception:
                priority = 1

        import time
        self._queued_ids.add(entry_id)
        await self._queue.put((priority, time.time(), entry_id))
        self._total_enqueued += 1
        logger.info(
            f"Enqueued entry {entry_id} with P{priority} for autonomous LLM triage (queue depth: {self._queue.qsize()})"
        )

        # Broadcast queue update
        if self._broadcast_callback:
            try:
                self._broadcast_callback(
                    {"type": "triage_queue_updated", "data": self.get_status()}
                )
            except Exception as e:
                logger.warning(f"WebSocket broadcast error: {e}")

        return True

    async def backfill_high_priority(self, limit: int = 25) -> int:
        """Find highest-velocity un-triaged entries in DB and enqueue them with priority ranking."""
        async with self._uow_factory() as uow:
            # Query top unanalyzed or heuristic high-velocity entries
            filters = EntryFilters(high_velocity_only=True)
            entries = await uow.entries.list(filters=filters)

        # Sort so frontier models & trending repos lead the backfill
        entries.sort(key=lambda e: self.calculate_priority(e))

        enqueued_count = 0
        for entry in entries:
            # If already triaged by real LLM, skip
            if entry.analysis and entry.analysis.model != AnalysisModel.HEURISTIC:
                continue

            p = self.calculate_priority(entry)
            if await self.enqueue(entry.id, priority=p):
                enqueued_count += 1
                if enqueued_count >= limit:
                    break

        logger.info(
            f"Backfill enqueued {enqueued_count} high-priority entries for LLM triage."
        )
        return enqueued_count

    async def start(self, auto_hydrate: bool = True) -> None:
        """Start the background triage worker with automatic startup queue hydration."""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Autonomous High-Priority LLM Triage Worker started.")

        if auto_hydrate:
            asyncio.create_task(self._safe_startup_hydrate())

    async def _safe_startup_hydrate(self) -> None:
        """Hydrate priority queue on boot so pending entries survive server restarts."""
        try:
            await asyncio.sleep(2)
            if self._queue.empty():
                await self.backfill_high_priority(limit=15)
        except Exception as e:
            logger.debug(f"Startup triage hydration skipped: {e}")

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
        """Worker loop processing entries by priority score from the queue."""
        analyzer = LLMAnalyzer(config={"provider": "ollama"})

        while self._running:
            try:
                # If hold_until_sweep is enabled, do not auto-consume queue items in background.
                # Items wait in queue until explicitly pushed via Live Sweep (or push_all_queued).
                if self._hold_until_sweep:
                    await asyncio.sleep(1.0)
                    continue

                priority, enqueued_at, entry_id = await self._queue.get()
                self._is_processing = True
                self._current_priority = f"P{priority}: {'Urgent Frontier' if priority == 0 else ('High' if priority == 1 else 'Standard')}"

                try:
                    await self._process_entry(entry_id, analyzer)
                    self._total_completed += 1
                except Exception as proc_err:
                    logger.error(
                        f"Error processing autonomous triage for {entry_id}: {proc_err}"
                    )
                    self._total_failed += 1
                finally:
                    self._queued_ids.discard(entry_id)
                    self._queue.task_done()
                    self._is_processing = False
                    self._current_entry_title = None

                    # Broadcast status update
                    if self._broadcast_callback:
                        try:
                            self._broadcast_callback(
                                {
                                    "type": "triage_queue_updated",
                                    "data": self.get_status(),
                                }
                            )
                        except Exception as _bc_err:
                            logger.debug(
                                f"Triage broadcast callback error (non-critical): {_bc_err}"
                            )

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
                logger.warning(f"Entry {entry_id} not found for triage.")
                return

            self._current_entry_title = entry.title
            logger.info(
                f"🤖 Autonomous LLM Triage executing for: {entry.title[:60]}..."
            )

            # Run LLM analysis with per-call timeout safety
            try:
                analysis_result = await asyncio.wait_for(
                    analyzer.analyze(entry), timeout=35.0
                )
            except TimeoutError:
                logger.warning(
                    f"LLM triage timed out after 35s for {entry.title[:50]}... skipping"
                )
                return

            # Check if analysis record exists
            existing_analysis = await uow.analyses.get_by_entry(entry_id)

            if existing_analysis:
                existing_analysis.attack_vector = analysis_result.attack_vector
                existing_analysis.risk_assessment = analysis_result.risk_assessment
                existing_analysis.mitigation = analysis_result.mitigation
                existing_analysis.threat_velocity = analysis_result.threat_velocity
                existing_analysis.severity_index = analysis_result.severity_index
                existing_analysis.blast_radius_score = (
                    analysis_result.blast_radius_score
                )
                existing_analysis.affected_ecosystem = (
                    analysis_result.affected_ecosystem
                )
                existing_analysis.is_pre_cve_warning = (
                    analysis_result.is_pre_cve_warning
                )
                existing_analysis.attack_archetype = analysis_result.attack_archetype
                existing_analysis.weaponization_potential = (
                    analysis_result.weaponization_potential or "Production Ready"
                )
                existing_analysis.model = AnalysisModel.OLLAMA
                existing_analysis.updated_at = datetime.now(UTC)
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
                    weaponization_potential=analysis_result.weaponization_potential
                    or "Production Ready",
                    model=AnalysisModel.OLLAMA,
                )
                await uow.analyses.add(analysis)

            # Persist rich AI triage intelligence directly into entry.metadata for instant retrieval
            entry.metadata = dict(entry.metadata or {})
            entry.metadata["is_triaged"] = True
            entry.metadata["triaged_at"] = datetime.now(UTC).isoformat()
            entry.metadata["triaged_by"] = analysis.model.value
            if analysis_result.attack_vector:
                entry.metadata["ai_architecture"] = analysis_result.attack_vector
            if analysis_result.risk_assessment:
                entry.metadata["ai_highlight"] = analysis_result.risk_assessment
            if analysis_result.mitigation:
                entry.metadata["developer_utility"] = analysis_result.mitigation
            if hasattr(uow.entries, "update"):
                res = uow.entries.update(entry)
                if asyncio.iscoroutine(res):
                    await res

            await uow.commit()
            logger.info(
                f"✅ LLM Triage complete for {entry.title[:50]} (Model: {analysis.model.value})"
            )

            # Record in recent telemetry
            self._items_triaged_recent.append({
                "entry_id": str(entry.id),
                "title": entry.title,
                "category": entry.category.value if hasattr(entry.category, "value") else str(entry.category),
                "model": analysis.model.value if hasattr(analysis.model, "value") else str(analysis.model),
                "velocity": analysis.threat_velocity,
                "archetype": analysis.attack_archetype,
                "triaged_at": datetime.now(UTC).isoformat(),
            })
            if len(self._items_triaged_recent) > 20:
                self._items_triaged_recent = self._items_triaged_recent[-20:]

            # Broadcast real-time triage update over WebSockets
            if self._broadcast_callback:
                try:
                    self._broadcast_callback(
                        {
                            "type": "triage_completed",
                            "data": {
                                "entry_id": str(entry.id),
                                "title": entry.title,
                                "category": entry.category.value if hasattr(entry.category, "value") else str(entry.category),
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
                                "ai_architecture": analysis_result.attack_vector,
                                "ai_highlight": analysis_result.risk_assessment,
                                "developer_utility": analysis_result.mitigation,
                                "is_pre_cve_warning": analysis.is_pre_cve_warning,
                            },
                        }
                    )
                except Exception as ws_err:
                    logger.warning(f"WebSocket broadcast error: {ws_err}")

            # Send Telegram Alert if critical or Pre-CVE
            if settings.delivery.telegram_enabled and (
                analysis.threat_velocity >= 70 or analysis.is_pre_cve_warning
            ):
                try:
                    telegram_delivery = delivery_registry.create(
                        "telegram",
                        {
                            "bot_token": settings.delivery.telegram_bot_token,
                            "chat_id": settings.delivery.telegram_chat_id,
                        },
                    )
                    await telegram_delivery.send_alert(entry, analysis)
                    logger.info(
                        f"Telegram alert dispatched for autonomous triage of {entry.title[:40]}"
                    )
                except Exception as tg_err:
                    logger.warning(
                        f"Failed to dispatch Telegram alert for triage: {tg_err}"
                    )


# Global Singleton Instance
_triage_service_instance: AutonomousTriageService | None = None


def get_triage_service() -> AutonomousTriageService:
    """Get or initialize global AutonomousTriageService instance."""
    global _triage_service_instance
    if _triage_service_instance is None:
        _triage_service_instance = AutonomousTriageService()
    return _triage_service_instance
