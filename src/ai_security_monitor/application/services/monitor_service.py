"""
Application monitor service - orchestrates fetching, analyzing, and dispatching.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from ai_security_monitor.config.settings import settings
from ai_security_monitor.config.sources import load_sources_from_yaml
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import (
    Analysis,
    AnalysisModel,
    Category,
    Entry,
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

_consecutive_failures: dict[str, int] = {}


async def send_source_failure_alert(
    source_name: str, count: int, error_msg: str | None = None
) -> bool:
    """Send alert via Telegram when an intelligence source fails consecutive sweeps."""
    try:
        tg_token = (
            getattr(settings.delivery, "telegram_bot_token", None)
            or getattr(settings, "telegram_bot_token", None)
            or os.getenv("TELEGRAM_BOT_TOKEN")
        )
        tg_chat = (
            getattr(settings.delivery, "telegram_chat_id", None)
            or getattr(settings, "telegram_chat_id", None)
            or os.getenv("TELEGRAM_CHAT_ID")
        )
        if not tg_token or not tg_chat:
            return False

        err_snippet = (
            f"\n<b>Error:</b> <code>{error_msg[:200]}</code>" if error_msg else ""
        )
        text = (
            f"⚠️ <b>AETHERGUARD SOURCE HEALTH ALERT</b>\n\n"
            f"Source: <b>{source_name}</b>\n"
            f"Status: Failed <b>{count}</b> consecutive fetch sweeps{err_snippet}\n\n"
            f"<i>Timestamp: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"
        )
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                json={
                    "chat_id": tg_chat,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        if resp.status_code == 200:
            from ai_security_monitor.core.diagnostics import diagnostics

            diagnostics.record_failure_alert(source_name, count)
            return True
        return False
    except Exception as e:
        logger.warning(f"Failed to dispatch Telegram consecutive failure alert: {e}")
        return False


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
                    cfg_dict["region"] = getattr(s_cfg, "region", "global")
                    cfg_dict["country"] = getattr(s_cfg, "country", "GLOBAL")
                    new_source = Source(
                        name=s_cfg.name,
                        category=Category(s_cfg.category)
                        if isinstance(s_cfg.category, str)
                        else s_cfg.category,
                        type=SourceType(s_cfg.type)
                        if isinstance(s_cfg.type, str)
                        else s_cfg.type,
                        url=s_cfg.url or "",
                        query=s_cfg.query,
                        rate_limit_seconds=s_cfg.rate_limit_seconds,
                        enabled=s_cfg.enabled,
                        config=cfg_dict,
                    )
                    await uow.sources.add(new_source)
                    count += 1
                else:
                    changed = False
                    if s_cfg.url and existing.url != s_cfg.url:
                        existing.url = s_cfg.url
                        changed = True
                    if s_cfg.category and existing.category.value != s_cfg.category:
                        existing.category = (
                            Category(s_cfg.category)
                            if isinstance(s_cfg.category, str)
                            else s_cfg.category
                        )
                        changed = True
                    if s_cfg.type and existing.type.value != s_cfg.type:
                        existing.type = (
                            SourceType(s_cfg.type)
                            if isinstance(s_cfg.type, str)
                            else s_cfg.type
                        )
                        changed = True
                    if (
                        s_cfg.rate_limit_seconds
                        and existing.rate_limit_seconds != s_cfg.rate_limit_seconds
                    ):
                        existing.rate_limit_seconds = s_cfg.rate_limit_seconds
                        changed = True
                    if s_cfg.query and existing.query != s_cfg.query:
                        existing.query = s_cfg.query
                        changed = True
                    if existing.enabled != s_cfg.enabled:
                        existing.enabled = s_cfg.enabled
                        changed = True
                    # Fully synchronize config dictionary including frequency and filter_mode
                    new_cfg = dict(s_cfg.config or {})
                    if getattr(s_cfg, "since", None):
                        new_cfg["frequency"] = s_cfg.since
                    new_cfg["region"] = getattr(s_cfg, "region", "global")
                    new_cfg["country"] = getattr(s_cfg, "country", "GLOBAL")
                    if existing.config != new_cfg:
                        existing.config = {**(existing.config or {}), **new_cfg}
                        changed = True
                    if changed:
                        await uow.sources.update(existing)
                        count += 1
            await uow.commit()

        logger.info(f"Initialized {count} sources from configuration")
        return count

    async def fetch_source(self, source: Source) -> FetchLog:
        """Fetch intelligence from a single source and analyze newly ingested entries."""
        start_time = datetime.now(UTC)
        new_entries_count = 0
        entries_total = 0
        status = FetchStatus.SUCCESS
        error_msg = None

        logger.info(f"Fetching from {source.name} ({source.type.value})")

        try:
            fetcher_cls = fetcher_registry.get(source.type.value)
            fetcher = fetcher_cls(source)
            fetch_result = await fetcher.fetch()
            entries_total = fetch_result.entries_total

            analyzer = analyzer_registry.create(settings.analyzer.default_model)
            blast_engine = analyzer_registry.create("blast_radius")

            # 1. Batch Deduplication: pre-fetch existing hashes in single query
            candidate_hashes = [
                e.content_hash for e in fetch_result.entries if e.content_hash
            ]
            existing_hashes: set[str] = set()
            if candidate_hashes:
                async with self._uow_factory() as uow:
                    existing_hashes = await uow.entries.get_existing_hashes(
                        candidate_hashes
                    )

            new_raw_entries = [
                e for e in fetch_result.entries if e.content_hash not in existing_hashes
            ]

            # Ingestion Freshness Guard: Skip historical archive dumps from feeds (> max_ingest_age_days, max 14d)
            max_age_days = getattr(settings.database, "max_ingest_age_days", 14)
            if max_age_days and max_age_days > 0:
                cutoff_ingest = datetime.now(UTC) - timedelta(days=max_age_days)
                fresh_entries = []
                for e in new_raw_entries:
                    pub_at = e.published_at
                    if pub_at is not None:
                        if pub_at.tzinfo is None:
                            pub_at = pub_at.replace(tzinfo=UTC)
                        if pub_at < cutoff_ingest:
                            logger.debug(
                                f"Skipping historical entry '{e.title}' published {e.published_at} (> {max_age_days}d ago)"
                            )
                            continue
                    fresh_entries.append(e)
                new_raw_entries = fresh_entries

            # 2. In-Memory Enrichment & Analysis (OUTSIDE write transaction)
            prepared_items: list[tuple[Entry, Analysis, bool, str, bool]] = []
            is_english_source = (
                source.type.value in ("arxiv", "hackernews", "github_trending")
                or source.config.get("country")
                in (
                    "US",
                    "GB",
                    "CA",
                    "AU",
                    "IE",
                    "IN",
                    "SG",
                    "GLOBAL",
                    "EU",
                )
                or source.config.get("language") == "en"
            )

            for entry in new_raw_entries:
                if not is_english_source:
                    try:
                        from ai_security_monitor.application.services.translation_service import (
                            translation_service,
                        )

                        await translation_service.translate_entry_async(entry)
                    except Exception as trans_e:
                        logger.debug(f"Translation skipped: {trans_e}")

                entry.metadata = entry.metadata or {}
                entry.metadata["region"] = source.config.get("region", "global")
                entry.metadata["country"] = source.config.get("country", "GLOBAL")
                default_prov = (
                    "model_release"
                    if source.category == Category.AI_MODELS
                    else "trending_repo"
                    if source.category == Category.GITHUB_TRENDING
                    else "ai_research"
                    if source.category == Category.AI_RESEARCH
                    else "developer_infra"
                    if source.category == Category.CYBER_TOOLS
                    else "ai_ecosystem"
                )
                entry.metadata["provenance_type"] = source.config.get(
                    "provenance_type", default_prov
                )

                # Heuristic & blast radius analysis
                analysis_res = await analyzer.analyze(entry)
                blast_res = await blast_engine.analyze(entry)

                import re

                has_cve = bool(
                    re.search(
                        r"\bcve-\d{4}-\d{4,}\b",
                        f"{entry.title} {entry.summary}".lower(),
                    )
                )
                is_security_cat = entry.category in (
                    Category.VULNERABILITIES,
                    Category.CYBERSECURITY,
                    Category.EXPLOITS_TRICKS,
                )
                is_ai_innovation = not has_cve and not is_security_cat

                if is_ai_innovation:
                    combined_ecosystem = sorted(
                        set(
                            (analysis_res.affected_ecosystem or [])
                            + (blast_res.affected_ecosystem or [])
                        )
                    )
                    analysis = Analysis(
                        entry_id=entry.id,
                        attack_vector=analysis_res.attack_vector
                        or blast_res.attack_vector
                        or "AI Architecture Specification",
                        risk_assessment=analysis_res.risk_assessment
                        or blast_res.risk_assessment
                        or "Production Capability & Performance",
                        mitigation=analysis_res.mitigation
                        or blast_res.mitigation
                        or "Integration & Deployment Guide",
                        threat_velocity=analysis_res.threat_velocity,
                        severity_index=analysis_res.severity_index,
                        blast_radius_score=0,
                        affected_ecosystem=combined_ecosystem,
                        is_pre_cve_warning=False,
                        attack_archetype=analysis_res.attack_archetype
                        or blast_res.attack_archetype
                        or "AI Ecosystem Development",
                        weaponization_potential=analysis_res.weaponization_potential
                        or "Production Ready",
                        mitre_attack_id=None,
                        mitre_technique=None,
                        model=AnalysisModel.HEURISTIC,
                    )
                else:
                    analysis = Analysis(
                        entry_id=entry.id,
                        attack_vector=analysis_res.attack_vector or "Standard vector",
                        risk_assessment=analysis_res.risk_assessment
                        or "Standard risk",
                        mitigation=analysis_res.mitigation or "Standard patch",
                        threat_velocity=analysis_res.threat_velocity,
                        severity_index=analysis_res.severity_index,
                        blast_radius_score=blast_res.blast_radius_score,
                        affected_ecosystem=blast_res.affected_ecosystem,
                        is_pre_cve_warning=blast_res.is_pre_cve_warning,
                        attack_archetype=blast_res.attack_archetype,
                        weaponization_potential=analysis_res.weaponization_potential
                        or blast_res.weaponization_potential,
                        mitre_attack_id=analysis_res.mitre_attack_id,
                        mitre_technique=analysis_res.mitre_technique,
                        model=AnalysisModel.HEURISTIC,
                    )

                title_lower = (entry.title or "").lower()
                cat_val = (
                    entry.category.value
                    if hasattr(entry.category, "value")
                    else str(entry.category)
                )
                is_landmark = (
                    analysis.threat_velocity >= 85
                    or any(
                        k in title_lower
                        for k in (
                            "deepseek",
                            "r1",
                            "frontier",
                            "qwen",
                            "llama",
                            "breakthrough",
                            "sota",
                            "vllm",
                            "sglang",
                            "reasoning",
                            "reasoner",
                        )
                    )
                    or (
                        cat_val == "ai_models"
                        and any(
                            k in title_lower
                            for k in (
                                "release",
                                "weights",
                                "checkpoint",
                                "model",
                                "moe",
                            )
                        )
                    )
                    or (
                        cat_val == "ai_research"
                        and analysis.threat_velocity >= 75
                    )
                )
                if is_landmark:
                    entry.metadata["is_important"] = True
                    entry.metadata["importance_reason"] = (
                        "Frontier Reasoning Architecture"
                        if any(
                            k in title_lower for k in ("reasoning", "deepseek", "r1")
                        )
                        else "Major Foundation Model Weights Release"
                        if cat_val == "ai_models"
                        else "Critical AI Developer Infrastructure"
                        if any(
                            k in title_lower
                            for k in ("vllm", "sglang", "runtime", "engine")
                        )
                        else "High-Impact Seminal Breakthrough"
                    )

                prepared_items.append(
                    (entry, analysis, is_landmark, cat_val, is_ai_innovation)
                )

            # 3. Atomic Database Commit (Very short transaction holding write lock)
            pending_broadcasts: list[dict] = []
            pending_triage_entries: list[tuple[UUID, Entry]] = []
            pending_telegram_alerts: list[tuple[Entry, Analysis]] = []

            async with self._uow_factory() as uow:
                for (
                    entry,
                    analysis,
                    is_landmark,
                    cat_name,
                    is_ai_innovation,
                ) in prepared_items:
                    try:
                        added_entry = await uow.entries.add(entry)
                        analysis.entry_id = added_entry.id
                        await uow.analyses.add(analysis)
                        added_entry.analysis = analysis
                        new_entries_count += 1

                        # Buffer WebSocket payload
                        pending_broadcasts.append(
                            {
                                "type": "new_entry",
                                "data": {
                                    "id": str(added_entry.id),
                                    "title": added_entry.title,
                                    "url": added_entry.url,
                                    "summary": added_entry.summary,
                                    "category": added_entry.category.value
                                    if hasattr(added_entry.category, "value")
                                    else str(added_entry.category),
                                    "source_name": source.name,
                                    "region": source.config.get("region", "global"),
                                    "country": source.config.get("country", "GLOBAL"),
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
                                    },
                                },
                            }
                        )

                        # Auto-triage qualification
                        if settings.analyzer.autonomous_triage_enabled:
                            should_auto_triage = (
                                is_landmark
                                or cat_name in ("ai_models", "ai_research")
                                or analysis.threat_velocity
                                >= settings.analyzer.triage_velocity_threshold
                            )
                            if should_auto_triage:
                                pending_triage_entries.append(
                                    (added_entry.id, added_entry)
                                )

                        # Autonomous Milestone / Emergency Broadcast
                        if (
                            analysis.threat_velocity >= 80
                            or analysis.is_pre_cve_warning
                            or is_landmark
                        ):
                            event_type = (
                                "landmark_ai_breakthrough"
                                if is_ai_innovation
                                else "emergency_threat_alert"
                            )
                            pending_broadcasts.append(
                                {
                                    "type": event_type,
                                    "data": {
                                        "id": str(added_entry.id),
                                        "title": added_entry.title,
                                        "url": added_entry.url,
                                        "velocity": analysis.threat_velocity,
                                        "is_pre_cve": analysis.is_pre_cve_warning,
                                        "archetype": analysis.attack_archetype,
                                        "source_name": source.name,
                                        "category": cat_name,
                                    },
                                }
                            )
                            pending_telegram_alerts.append((added_entry, analysis))

                    except DuplicateEntryError:
                        continue

                # Update source telemetry
                source.last_fetched_at = datetime.now(UTC)
                source.last_status = fetch_result.status
                source.last_entries_new = new_entries_count
                await uow.sources.update(source)
                await uow.commit()

            # 4. Post-Commit Safe Broadcasting & Triage Enqueue (Guaranteed No Phantom Entries)
            if self._broadcast_callback:
                for bc in pending_broadcasts:
                    try:
                        self._broadcast_callback(bc)
                    except Exception as ws_err:
                        logger.warning(f"WebSocket broadcast error: {ws_err}")

            if pending_triage_entries:
                try:
                    from ai_security_monitor.application.services.autonomous_triage_service import (
                        get_triage_service,
                    )

                    triage_svc = get_triage_service()
                    for entry_id, ent in pending_triage_entries:
                        p = triage_svc.calculate_priority(ent)
                        await triage_svc.enqueue(entry_id, priority=p)
                except Exception as triage_err:
                    logger.warning(
                        f"Failed to auto-enqueue entry for LLM triage: {triage_err}"
                    )

            # Telegram auto-alerts (post-commit)
            for alert_entry, alert_analysis in pending_telegram_alerts:
                try:
                    tg_token = getattr(settings, "telegram_bot_token", None) or os.getenv(
                        "TELEGRAM_BOT_TOKEN"
                    )
                    tg_chat = getattr(settings, "telegram_chat_id", None) or os.getenv(
                        "TELEGRAM_CHAT_ID"
                    )
                    if tg_token and tg_chat:
                        from ai_security_monitor.infrastructure.delivery.telegram_delivery import (
                            TelegramDelivery,
                        )

                        tg_delivery = TelegramDelivery(
                            {"bot_token": tg_token, "chat_id": tg_chat}
                        )
                        asyncio.create_task(
                            tg_delivery.send_alert(alert_entry, alert_analysis)
                        )
                except Exception as tg_err:
                    logger.debug(f"Telegram auto-alert error: {tg_err}")

        except Exception as e:
            logger.error(f"Error fetching from {source.name}: {e}")
            status = FetchStatus.ERROR
            error_msg = str(e)

        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

        log = FetchLog(
            source_id=source.id,
            source_name=source.name,
            status=status,
            entries_new=new_entries_count,
            entries_total=entries_total,
            error_message=error_msg,
            duration_ms=duration_ms,
            fetched_at=datetime.now(UTC),
        )

        async with self._uow_factory() as uow:
            await uow.fetch_logs.add(log)
            await uow.commit()

        return log

    async def fetch_all(
        self, force: bool = False, max_concurrency: int | None = None
    ) -> dict:
        """Fetch intelligence from all enabled sources with priority ordering and adaptive concurrency."""
        async with self._uow_factory() as uow:
            sources = await uow.sources.list(enabled_only=True)

        if not sources:
            await self.init_sources()
            async with self._uow_factory() as uow:
                sources = await uow.sources.list(enabled_only=True)

        # Priority queue ordering: Frontier Models -> AI Research -> GitHub Trending -> AI Tools -> Global Tech
        source_priority_order = {
            Category.AI_MODELS: 1,
            Category.AI_RESEARCH: 2,
            Category.GITHUB_TRENDING: 3,
            Category.CYBER_TOOLS: 4,
            Category.AI_TECH: 5,
        }
        sources.sort(key=lambda s: (source_priority_order.get(s.category, 99), s.name))

        # Respect source-level rate limits and cooldown unless force=True
        if not force:
            now_utc = datetime.now(UTC)
            eligible_sources = []
            for s in sources:
                last = s.last_fetched_at
                if last:
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=UTC)
                    limit_sec = s.rate_limit_seconds or settings.fetch.rate_limit_default
                    if (now_utc - last).total_seconds() < limit_sec:
                        continue
                eligible_sources.append(s)
            sources = eligible_sources

        # Adaptive concurrency: scales with source count, capped at configurable max_concurrency
        target_concurrency = (
            max_concurrency
            if max_concurrency is not None
            else settings.fetch.max_concurrency
        )
        concurrency = max(1, min(len(sources), target_concurrency)) if sources else 4
        sem = asyncio.Semaphore(concurrency)
        total_new = 0
        success = 0
        error = 0
        lock = asyncio.Lock()

        async def _worker(src: Source) -> None:
            nonlocal total_new, success, error
            async with sem:
                try:
                    # arXiv sources queue behind a class-level 3s pacing lock.
                    # With 14 regional arXiv fetchers, the last waits 39s+ before
                    # its HTTP request even starts.  Give arXiv sources 90s so
                    # all regional sources complete instead of timing out silently.
                    source_timeout = 90.0 if src.type.value == "arxiv" else 25.0
                    log = await asyncio.wait_for(
                        self.fetch_source(src), timeout=source_timeout
                    )
                    async with lock:
                        if log.status == FetchStatus.SUCCESS:
                            success += 1
                            total_new += log.entries_new
                            _consecutive_failures[src.name] = 0
                        else:
                            error += 1
                            failures = _consecutive_failures.get(src.name, 0) + 1
                            _consecutive_failures[src.name] = failures
                            threshold = settings.fetch.consecutive_failure_threshold
                            if failures == threshold or (
                                failures > threshold and failures % 5 == 0
                            ):
                                logger.warning(
                                    f"Source {src.name} has failed {failures} consecutive sweeps. Alerting."
                                )
                                asyncio.create_task(
                                    send_source_failure_alert(
                                        src.name, failures, log.error_message
                                    )
                                )
                except Exception as e:
                    async with lock:
                        error += 1
                        failures = _consecutive_failures.get(src.name, 0) + 1
                        _consecutive_failures[src.name] = failures
                        threshold = settings.fetch.consecutive_failure_threshold
                        if failures == threshold or (
                            failures > threshold and failures % 5 == 0
                        ):
                            logger.warning(
                                f"Source {src.name} has failed {failures} consecutive sweeps. Alerting."
                            )
                            asyncio.create_task(
                                send_source_failure_alert(src.name, failures, str(e))
                            )
                    logger.warning(f"Concurrent sweep error for {src.name}: {e}")
                finally:
                    # Balanced cooperative yield to keep SQLite and event loop fluid for user HTTP requests
                    await asyncio.sleep(0.02)

        # Execute all sources concurrently across the worker pool
        await asyncio.gather(*[_worker(src) for src in sources], return_exceptions=True)

        # Invalidate response caches so freshly ingested entries and updated stats are immediately visible on website
        from ai_security_monitor.infrastructure.cache import response_cache

        response_cache.invalidate_prefix("entries_")
        response_cache.invalidate_prefix("sources_list_all_")
        response_cache.invalidate("sources_map")
        response_cache.invalidate("total_unfiltered_count")
        response_cache.invalidate("stats_totals")
        response_cache.invalidate("sweep_status")

        return {
            "total_sources": len(sources),
            "success": success,
            "error": error,
            "total_new": total_new,
        }

    async def purge_stale_entries(
        self,
        older_than_days: int | None = None,
        hard_delete: bool = False,
        include_vaulted: bool = False,
    ) -> dict:
        """Remove entries, logs, and digests older than retention window (defaults to settings.database.retention_days = 7).

        - older_than_days: 0 means purge all active entries up to now.
        - hard_delete: If True, permanently removes matching records from SQLite disk.
        - include_vaulted: If True, overrides vault protection and purges all matching entries.

        Returns a summary dict with the count of purged items.
        """
        days = (
            older_than_days
            if older_than_days is not None
            else settings.database.retention_days
        )
        async with self._uow_factory() as uow:
            purged = await uow.entries.purge_old_entries(
                older_than_days=days,
                hard_delete=hard_delete,
                include_vaulted=include_vaulted,
            )
            # Hard-delete previously soft-purged records ONLY when the user explicitly
            # requests it via hard_delete=True. Never silently wipe records automatically.
            hard_purged = 0
            if hard_delete:
                hard_purged = await uow.entries.hard_delete_purged(grace_days=0)
            purged_logs = await uow.fetch_logs.purge_old_logs(older_than_days=days)
            purged_digests = await uow.digests.purge_old_digests(older_than_days=days)
            try:
                from sqlalchemy import text

                await uow.session.execute(text("PRAGMA optimize"))
            except Exception:
                pass
            await uow.commit()

        # Invalidate all caches after data hygiene purge
        from ai_security_monitor.infrastructure.cache import response_cache

        response_cache.clear()

        logger.info(
            f"Data hygiene purge complete: removed {purged} entries (hard_delete={hard_delete}, include_vaulted={include_vaulted}), "
            f"{purged_logs} logs, {purged_digests} digests older than {days} days"
        )
        return {
            "purged": purged,
            "purged_entries": purged,
            "hard_deleted_purged": hard_purged,
            "purged_logs": purged_logs,
            "purged_digests": purged_digests,
            "older_than_days": days,
            "hard_delete": hard_delete,
            "include_vaulted": include_vaulted,
        }

    async def restore_purged_entries(self) -> dict:
        """Restore all soft-purged entries back to active visibility and invalidate caches."""
        async with self._uow_factory() as uow:
            restored = await uow.entries.restore_purged_entries()
            await uow.commit()

        from ai_security_monitor.infrastructure.cache import response_cache

        response_cache.clear()

        logger.info(
            f"Manual restoration complete: restored {restored} previously soft-purged entries."
        )
        return {"restored": restored, "success": True}

    async def get_retention_status(
        self,
        older_than_days: int = 7,
        include_vaulted: bool = False,
    ) -> dict:
        """Retrieve retention policy and entry counts for manual cleanup planning."""
        async with self._uow_factory() as uow:
            counts = await uow.entries.get_retention_counts(
                older_than_days=older_than_days,
                include_vaulted=include_vaulted,
            )

        counts["auto_purge_enabled"] = getattr(
            settings.database, "auto_purge_enabled", False
        )
        counts["default_retention_days"] = settings.database.retention_days
        counts["max_ingest_age_days"] = getattr(
            settings.database, "max_ingest_age_days", 14
        )
        return counts

    async def get_sweep_status(self) -> dict:
        """Return live sweep freshness data: last sweep time, next sweep ETA, per-source freshness."""
        from ai_security_monitor.application.services.scheduler_service import (
            _last_sweep_at,
            _server_started_at,
            _sweep_count,
        )

        now = datetime.now(UTC)
        interval_minutes = settings.scheduler.fetch_interval_minutes

        def _to_utc(dt: datetime | None) -> datetime | None:
            if dt is None:
                return None
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)

        sweep_at = _to_utc(_last_sweep_at)
        started_at = _to_utc(_server_started_at) or now

        last_sweep_iso = sweep_at.isoformat() if sweep_at else None
        seconds_since = int((now - sweep_at).total_seconds()) if sweep_at else None
        next_sweep_in = (
            max(0, interval_minutes * 60 - seconds_since)
            if seconds_since is not None
            else None
        )
        server_uptime_seconds = int((now - started_at).total_seconds())

        async with self._uow_factory() as uow:
            sources = await uow.sources.list(enabled_only=True)

        source_freshness = []
        for src in sources:
            last = _to_utc(src.last_fetched_at)
            age_seconds = int((now - last).total_seconds()) if last else None
            source_freshness.append(
                {
                    "name": src.name,
                    "last_fetched_at": last.isoformat() if last else None,
                    "age_seconds": age_seconds,
                    "status": src.last_status.value if src.last_status else "never",
                    "last_new": src.last_entries_new or 0,
                }
            )

        # Sort: stale sources (longest since last fetch) first
        source_freshness.sort(
            key=lambda x: (
                x["age_seconds"] if x["age_seconds"] is not None else 999999999
            ),
            reverse=True,
        )

        from ai_security_monitor.core.diagnostics import diagnostics

        return {
            "last_sweep_at": last_sweep_iso,
            "seconds_since_last_sweep": seconds_since,
            "next_sweep_in_seconds": next_sweep_in,
            "sweep_interval_minutes": interval_minutes,
            "total_sources": len(sources),
            "sweep_count": _sweep_count,
            "server_uptime_seconds": server_uptime_seconds,
            "sources": source_freshness,
            "self_healing": diagnostics.get_summary(),
        }

    async def get_stats(self) -> dict:
        """Get aggregate system metrics and stats using high-performance scalar and group-by queries."""
        from sqlalchemy import func, select, text

        from ai_security_monitor.infrastructure.database.models import (
            AnalysisModel,
            EntryModel,
            SourceModel,
            WatchlistRuleModel,
        )

        async with self._uow_factory() as uow:
            # Fast scalar count queries (single table index scans, no entity conversions)
            total_entries = (
                await uow.session.execute(
                    select(func.count(EntryModel.id)).where(
                        EntryModel.is_purged.is_(False)
                    )
                )
            ).scalar() or 0
            total_sources = (
                await uow.session.execute(
                    select(func.count(SourceModel.id)).where(
                        SourceModel.enabled.is_(True)
                    )
                )
            ).scalar() or 0
            high_velocity = (
                await uow.session.execute(
                    select(func.count(AnalysisModel.id))
                    .join(EntryModel, AnalysisModel.entry_id == EntryModel.id)
                    .where(EntryModel.is_purged.is_(False))
                    .where(AnalysisModel.threat_velocity >= 70)
                )
            ).scalar() or 0
            pre_cve_warnings = (
                await uow.session.execute(
                    select(func.count(AnalysisModel.id))
                    .join(EntryModel, AnalysisModel.entry_id == EntryModel.id)
                    .where(EntryModel.is_purged.is_(False))
                    .where(AnalysisModel.is_pre_cve_warning.is_(True))
                )
            ).scalar() or 0
            watchlist_rules = (
                await uow.session.execute(select(func.count(WatchlistRuleModel.id)))
            ).scalar() or 0

            # Single group-by query for all categories (replaces 8 sequential table scans)
            cat_stmt = (
                select(EntryModel.category, func.count(EntryModel.id))
                .where(EntryModel.is_purged.is_(False))
                .group_by(EntryModel.category)
            )
            cat_rows = (await uow.session.execute(cat_stmt)).all()
            cats = {cat.value: 0 for cat in Category} | dict(cat_rows)

            recent_logs = await uow.fetch_logs.get_recent(hours=24, limit=15)

            # Compute affected AI framework exposures from database
            framework_exposure = []
            try:
                import json

                stmt = text(
                    "SELECT affected_ecosystem, blast_radius_score "
                    "FROM entry_analysis WHERE affected_ecosystem IS NOT NULL AND affected_ecosystem != '[]' "
                    "ORDER BY id DESC LIMIT 500"
                )
                raw_rows = (await uow.session.execute(stmt)).fetchall()
                f_stats: dict[str, dict[str, float]] = {}
                for eco_json, blast in raw_rows:
                    try:
                        ecos = (
                            json.loads(eco_json)
                            if isinstance(eco_json, str)
                            else eco_json
                        )
                        if isinstance(ecos, list):
                            for e in ecos:
                                e_clean = str(e).strip()
                                if not e_clean:
                                    continue
                                if e_clean not in f_stats:
                                    f_stats[e_clean] = {"count": 0, "total_blast": 0}
                                f_stats[e_clean]["count"] += 1
                                f_stats[e_clean]["total_blast"] += blast or 0
                    except Exception:
                        pass

                for name, data in sorted(
                    f_stats.items(), key=lambda x: x[1]["count"], reverse=True
                )[:5]:
                    cnt = int(data["count"])
                    avg_b = round(data["total_blast"] / cnt, 1) if cnt > 0 else 0.0
                    risk_label = (
                        "HIGH RISK"
                        if avg_b >= 75
                        else (
                            "ELEVATED"
                            if avg_b >= 60
                            else ("MODERATE" if avg_b >= 35 else "MONITORED")
                        )
                    )
                    framework_exposure.append(
                        {
                            "name": name,
                            "count": cnt,
                            "avg_blast": avg_b,
                            "risk_level": risk_label,
                        }
                    )
            except Exception:
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
                        "fetched_at": log_item.fetched_at.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    for log_item in recent_logs
                ],
            }
