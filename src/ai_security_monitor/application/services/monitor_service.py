"""
Application monitor service - orchestrates fetching, analyzing, and dispatching.
"""
from __future__ import annotations

import asyncio
import os
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
                    cfg_dict = dict(s_cfg.config or {})
                    cfg_dict['region'] = getattr(s_cfg, 'region', 'global')
                    cfg_dict['country'] = getattr(s_cfg, 'country', 'GLOBAL')
                    new_source = Source(
                        name=s_cfg.name,
                        category=Category(s_cfg.category) if isinstance(s_cfg.category, str) else s_cfg.category,
                        type=SourceType(s_cfg.type) if isinstance(s_cfg.type, str) else s_cfg.type,
                        url=s_cfg.url or "",
                        query=s_cfg.query,
                        rate_limit_seconds=s_cfg.rate_limit_seconds,
                        enabled=s_cfg.enabled,
                        config=cfg_dict
                    )
                    await uow.sources.add(new_source)
                    count += 1
                else:
                    changed = False
                    if s_cfg.url and existing.url != s_cfg.url:
                        existing.url = s_cfg.url
                        changed = True
                    if s_cfg.query and existing.query != s_cfg.query:
                        existing.query = s_cfg.query
                        changed = True
                    if existing.enabled != s_cfg.enabled:
                        existing.enabled = s_cfg.enabled
                        changed = True
                    if existing.config.get('region') != s_cfg.region:
                        existing.config['region'] = s_cfg.region
                        changed = True
                    if existing.config.get('country') != s_cfg.country:
                        existing.config['country'] = s_cfg.country
                        changed = True
                    if changed:
                        await uow.sources.update(existing)
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
                        # Stamp sovereign region and country from source config
                        entry.metadata = entry.metadata or {}
                        entry.metadata['region'] = source.config.get('region', 'global')
                        entry.metadata['country'] = source.config.get('country', 'GLOBAL')

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
                            weaponization_potential=analysis_res.weaponization_potential or blast_res.weaponization_potential,
                            mitre_attack_id=analysis_res.mitre_attack_id,
                            mitre_technique=analysis_res.mitre_technique,
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
                                        "region": source.config.get('region', 'global'),
                                        "country": source.config.get('country', 'GLOBAL'),
                                        "published_at": added_entry.published_at.isoformat(),
                                        "tags": added_entry.tags,
                                        "analysis": {
                                            "threat_velocity": analysis.threat_velocity,
                                            "severity_index": analysis.severity_index,
                                            "blast_radius_score": analysis.blast_radius_score,
                                            "affected_ecosystem": analysis.affected_ecosystem,
                                            "is_pre_cve_warning": analysis.is_pre_cve_warning,
                                            "attack_archetype": analysis.attack_archetype,
                                            "weaponization_potential": analysis.weaponization_potential,
                                            "mitre_attack_id": analysis.mitre_attack_id,
                                            "mitre_technique": analysis.mitre_technique,
                                            "attack_vector": analysis.attack_vector,
                                            "risk_assessment": analysis.risk_assessment,
                                            "mitigation": analysis.mitigation,
                                        }
                                    }
                                })
                            except Exception as ws_err:
                                logger.warn(f"WebSocket broadcast error: {ws_err}")

                        # Auto-enqueue high-priority entries into Autonomous LLM Triage Queue
                        if settings.analyzer.autonomous_triage_enabled:
                            if (analysis.threat_velocity >= settings.analyzer.triage_velocity_threshold
                                    or analysis.is_pre_cve_warning):
                                try:
                                    from ai_security_monitor.application.services.autonomous_triage_service import get_triage_service
                                    await get_triage_service().enqueue(added_entry.id)
                                except Exception as triage_err:
                                    logger.warn(f"Failed to auto-enqueue entry for LLM triage: {triage_err}")

                        # Autonomous Emergency Push Alert (Telegram & Event Broadcast)
                        if analysis.threat_velocity >= 80 or analysis.is_pre_cve_warning:
                            if self._broadcast_callback:
                                try:
                                    self._broadcast_callback({
                                        "type": "emergency_threat_alert",
                                        "data": {
                                            "id": str(added_entry.id),
                                            "title": added_entry.title,
                                            "url": added_entry.url,
                                            "velocity": analysis.threat_velocity,
                                            "is_pre_cve": analysis.is_pre_cve_warning,
                                            "archetype": analysis.attack_archetype,
                                            "source_name": source.name
                                        }
                                    })
                                except Exception:
                                    pass

                            # Dispatch Telegram Emergency Alert if credentials present
                            try:
                                tg_token = getattr(settings, 'telegram_bot_token', None) or os.getenv('TELEGRAM_BOT_TOKEN')
                                tg_chat = getattr(settings, 'telegram_chat_id', None) or os.getenv('TELEGRAM_CHAT_ID')
                                if tg_token and tg_chat:
                                    from ai_security_monitor.infrastructure.delivery.telegram_delivery import TelegramDelivery
                                    tg_delivery = TelegramDelivery({'bot_token': tg_token, 'chat_id': tg_chat})
                                    asyncio.create_task(tg_delivery.send_alert(added_entry, analysis))
                            except Exception as tg_err:
                                logger.debug(f"Telegram auto-alert error: {tg_err}")

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

    async def purge_stale_entries(self, older_than_days: int = 30) -> dict:
        """Remove entries older than `older_than_days` days to keep the database fresh.

        Returns a summary dict with the count of purged entries.
        """
        async with self._uow_factory() as uow:
            purged = await uow.entries.purge_old_entries(older_than_days=older_than_days)
            await uow.commit()

        logger.info(f"Data hygiene purge complete: removed {purged} entries older than {older_than_days} days")
        return {"purged": purged, "older_than_days": older_than_days}

    async def get_sweep_status(self) -> dict:
        """Return live sweep freshness data: last sweep time, next sweep ETA, per-source freshness."""
        from ai_security_monitor.application.services.scheduler_service import _last_sweep_at

        now = datetime.utcnow()
        interval_minutes = settings.scheduler.fetch_interval_minutes

        last_sweep_iso = _last_sweep_at.isoformat() + "Z" if _last_sweep_at else None
        seconds_since = int((now - _last_sweep_at).total_seconds()) if _last_sweep_at else None
        next_sweep_in = max(0, interval_minutes * 60 - seconds_since) if seconds_since is not None else None

        async with self._uow_factory() as uow:
            sources = await uow.sources.list(enabled_only=True)

        source_freshness = []
        for src in sources:
            last = src.last_fetched_at
            age_seconds = int((now - last).total_seconds()) if last else None
            source_freshness.append({
                "name": src.name,
                "last_fetched_at": last.isoformat() + "Z" if last else None,
                "age_seconds": age_seconds,
                "status": src.last_status.value if src.last_status else "never",
                "last_new": src.last_entries_new or 0,
            })

        # Sort: stale sources (longest since last fetch) first
        source_freshness.sort(key=lambda x: x["age_seconds"] if x["age_seconds"] is not None else 999999999, reverse=True)

        return {
            "last_sweep_at": last_sweep_iso,
            "seconds_since_last_sweep": seconds_since,
            "next_sweep_in_seconds": next_sweep_in,
            "sweep_interval_minutes": interval_minutes,
            "total_sources": len(sources),
            "sources": source_freshness,
        }


    async def get_stats(self) -> dict:
        """Get aggregate system metrics and stats."""
        async with self._uow_factory() as uow:
            total_entries = await uow.entries.count()
            total_sources = len(await uow.sources.list(enabled_only=True))
            high_velocity = await uow.analyses.count_high_velocity(70)
            pre_cve_warnings = await uow.analyses.count_pre_cve_warnings()
            watchlist_rules = len(await uow.watchlist.list())

            cats = {}
            for cat in Category:
                c_count = await uow.entries.count(EntryFilters(category=cat))
                cats[cat.value] = c_count

            recent_logs = await uow.fetch_logs.get_recent(hours=24, limit=15)

            # Compute real affected AI framework exposures from database
            framework_exposure = []
            try:
                import json
                from sqlalchemy import text
                stmt = text(
                    "SELECT affected_ecosystem, blast_radius_score "
                    "FROM entry_analysis WHERE affected_ecosystem IS NOT NULL AND affected_ecosystem != '[]'"
                )
                raw_rows = (await uow.session.execute(stmt)).fetchall()
                f_stats: dict[str, dict[str, float]] = {}
                for eco_json, blast in raw_rows:
                    try:
                        ecos = json.loads(eco_json) if isinstance(eco_json, str) else eco_json
                        if isinstance(ecos, list):
                            for e in ecos:
                                e_clean = str(e).strip()
                                if not e_clean:
                                    continue
                                if e_clean not in f_stats:
                                    f_stats[e_clean] = {"count": 0, "total_blast": 0}
                                f_stats[e_clean]["count"] += 1
                                f_stats[e_clean]["total_blast"] += (blast or 0)
                    except Exception:
                        pass

                for name, data in sorted(f_stats.items(), key=lambda x: x[1]["count"], reverse=True)[:5]:
                    cnt = int(data["count"])
                    avg_b = round(data["total_blast"] / cnt, 1) if cnt > 0 else 0.0
                    risk_label = "HIGH RISK" if avg_b >= 75 else ("ELEVATED" if avg_b >= 60 else ("MODERATE" if avg_b >= 35 else "MONITORED"))
                    framework_exposure.append({
                        "name": name,
                        "count": cnt,
                        "avg_blast": avg_b,
                        "risk_level": risk_label
                    })
            except Exception as e:
                pass

            return {
                "total_entries": total_entries,
                "total_sources": total_sources,
                "high_velocity_entries": high_velocity,
                "pre_cve_warnings": pre_cve_warnings,
                "watchlist_rules": watchlist_rules,
                "by_category": cats,
                "framework_exposure": framework_exposure,
                "recent_fetches": [
                    {
                        "source_name": log_item.source_name,
                        "status": log_item.status.value,
                        "entries_new": log_item.entries_new,
                        "fetched_at": log_item.fetched_at.strftime("%Y-%m-%d %H:%M:%S")
                    } for log_item in recent_logs
                ]
            }
