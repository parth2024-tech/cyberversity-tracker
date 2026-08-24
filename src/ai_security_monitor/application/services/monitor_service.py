"""
Application monitor service - orchestrates fetching, analyzing, and dispatching.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ai_security_monitor.config.settings import settings
from ai_security_monitor.config.sources import load_sources_from_yaml
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import (
    Analysis,
    AnalysisModel,
    Category,
    FetchLog,
    FetchStatus,
    Source,
    SourceType,
)
from ai_security_monitor.domain.exceptions import DuplicateEntryError
from ai_security_monitor.domain.repositories import EntryFilters
from ai_security_monitor.infrastructure.analyzers.base import analyzer_registry
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.infrastructure.fetchers.base import fetcher_registry

logger = get_logger(__name__)


class MonitorService:
    """Core application service managing the intelligence lifecycle."""

    def __init__(self, uow_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None):
        self._uow_factory = uow_factory or (lambda: SqlAlchemyUnitOfWork())
        self._broadcast_callback: Callable[[dict], None] | None = None

    def set_broadcast_callback(self, cb: Callable[[dict], None]) -> None:
        """Set WebSocket broadcast callback."""
        self._broadcast_callback = cb

    async def init_sources(self, config_path: str | None = None) -> int:
        """Initialize sources from YAML config into the database."""
        sources_cfg = load_sources_from_yaml(config_path)
        count = 0

        async with self._uow_factory() as uow:
            for s_cfg in sources_cfg:
                existing = await uow.sources.get_by_name(s_cfg.name)
                if not existing:
                    new_source = Source(
                        name=s_cfg.name,
                        category=Category(s_cfg.category) if isinstance(s_cfg.category, str) else s_cfg.category,
                        type=SourceType(s_cfg.type) if isinstance(s_cfg.type, str) else s_cfg.type,
                        url=s_cfg.url or "",
                        query=s_cfg.query,
                        rate_limit_seconds=s_cfg.rate_limit_seconds,
                        enabled=s_cfg.enabled,
                        config=s_cfg.config or {}
                    )
                    await uow.sources.add(new_source)
                    count += 1
            await uow.commit()

        logger.info(f"Initialized {count} sources from configuration")
        return count

    async def fetch_source(self, source: Source) -> FetchLog:
        """Fetch intelligence from a single source and analyze newly ingested entries."""
        start_time = datetime.utcnow()
        new_entries_count = 0
        status = FetchStatus.SUCCESS
        error_msg = None

        logger.info(f"Fetching from {source.name} ({source.type.value})")

        try:
            fetcher_cls = fetcher_registry.get(source.type.value)
            fetcher = fetcher_cls(source)
            fetch_result = await fetcher.fetch()

            analyzer = analyzer_registry.create(settings.analyzer.default_model)
            blast_engine = analyzer_registry.create("blast_radius")

            async with self._uow_factory() as uow:
                for entry in fetch_result.entries:
                    existing = await uow.entries.get_by_content_hash(entry.content_hash)
                    if existing:
                        continue

                    try:
                        added_entry = await uow.entries.add(entry)
                        new_entries_count += 1

                        # Auto-analyze entry
                        analysis_res = await analyzer.analyze(added_entry)
                        blast_res = await blast_engine.analyze(added_entry)

                        analysis = Analysis(
                            entry_id=added_entry.id,
                            attack_vector=analysis_res.attack_vector or "Standard vector",
                            risk_assessment=analysis_res.risk_assessment or "Standard risk",
                            mitigation=analysis_res.mitigation or "Standard patch",
                            threat_velocity=analysis_res.threat_velocity,
                            severity_index=analysis_res.severity_index,
                            blast_radius_score=blast_res.blast_radius_score,
                            affected_ecosystem=blast_res.affected_ecosystem,
                            is_pre_cve_warning=blast_res.is_pre_cve_warning,
                            attack_archetype=blast_res.attack_archetype,
                            weaponization_potential=blast_res.weaponization_potential,
                            model=AnalysisModel.HEURISTIC
                        )

                        await uow.analyses.add(analysis)
                        added_entry.analysis = analysis

                        # Real-time WebSocket Broadcast
                        if self._broadcast_callback:
                            try:
                                self._broadcast_callback({
                                    "type": "new_entry",
                                    "data": {
                                        "id": str(added_entry.id),
                                        "title": added_entry.title,
                                        "url": added_entry.url,
                                        "summary": added_entry.summary,
                                        "category": added_entry.category.value,
                                        "source_name": source.name,
                                        "published_at": added_entry.published_at.isoformat(),
                                        "tags": added_entry.tags,
                                        "analysis": {
                                            "threat_velocity": analysis.threat_velocity,
                                            "severity_index": analysis.severity_index,
                                            "blast_radius_score": analysis.blast_radius_score,
                                            "affected_ecosystem": analysis.affected_ecosystem,
                                            "is_pre_cve_warning": analysis.is_pre_cve_warning,
                                            "attack_vector": analysis.attack_vector,
                                            "risk_assessment": analysis.risk_assessment,
                                            "mitigation": analysis.mitigation,
                                        }
                                    }
                                })
                            except Exception as ws_err:
                                logger.warn(f"WebSocket broadcast error: {ws_err}")

                    except DuplicateEntryError:
                        continue

                # Update source telemetry
                source.last_fetched_at = datetime.utcnow()
                source.last_status = fetch_result.status
                source.last_entries_new = new_entries_count
                await uow.sources.update(source)
                await uow.commit()

        except Exception as e:
            logger.error(f"Error fetching from {source.name}: {e}")
            status = FetchStatus.ERROR
            error_msg = str(e)

        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        log = FetchLog(
            source_id=source.id,
            source_name=source.name,
            status=status,
            entries_new=new_entries_count,
            entries_total=0,
            error_message=error_msg,
            duration_ms=duration_ms,
            fetched_at=datetime.utcnow()
        )

        async with self._uow_factory() as uow:
            await uow.fetch_logs.add(log)
            await uow.commit()

        return log

    async def fetch_all(self, force: bool = False) -> dict:
        """Fetch intelligence from all enabled sources."""
        async with self._uow_factory() as uow:
            sources = await uow.sources.list(enabled_only=True)

        if not sources:
            await self.init_sources()
            async with self._uow_factory() as uow:
                sources = await uow.sources.list(enabled_only=True)

        total_new = 0
        success = 0
        error = 0

        for src in sources:
            log = await self.fetch_source(src)
            if log.status == FetchStatus.SUCCESS:
                success += 1
                total_new += log.entries_new
            else:
                error += 1

        return {
            "total_sources": len(sources),
            "success": success,
            "error": error,
            "total_new": total_new
        }

    async def get_stats(self) -> dict:
        """Get aggregate system metrics and stats."""
        async with self._uow_factory() as uow:
            total_entries = await uow.entries.count()
            total_sources = len(await uow.sources.list())
            high_velocity = await uow.analyses.count_high_velocity(70)
            pre_cve_warnings = await uow.analyses.count_pre_cve_warnings()

            cats = {}
            for cat in Category:
                c_count = await uow.entries.count(EntryFilters(category=cat))
                cats[cat.value] = c_count

            recent_logs = await uow.fetch_logs.get_recent(hours=24, limit=15)

            return {
                "total_entries": total_entries,
                "total_sources": total_sources,
                "high_velocity_entries": high_velocity,
                "pre_cve_warnings": pre_cve_warnings,
                "by_category": cats,
                "recent_fetches": [
                    {
                        "source_name": log_item.source_name,
                        "status": log_item.status.value,
                        "entries_new": log_item.entries_new,
                        "fetched_at": log_item.fetched_at.strftime("%Y-%m-%d %H:%M:%S")
                    } for log_item in recent_logs
                ]
            }
