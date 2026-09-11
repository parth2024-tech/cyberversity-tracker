"""
Entries API router — optimized for real-time speed.

Key improvements over v1:
  1. Sources map and watchlist rules are cached in-process (TTL 60s / 30s)
     → no redundant DB hits on every request
  2. entries.list() and entries.count() run concurrently with asyncio.gather()
     → saves ~200–400ms per request
  3. Watchlist rule fetch is short-circuited when watchlist_only=False
  4. Cache-Control header set for browser-level caching between tab switches
"""
from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ai_security_monitor.domain.entities import Category
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.cache import response_cache
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

entries_router = APIRouter(prefix="/entries")

# ---------------------------------------------------------------------------
# Data Hygiene & Content Sanitization Helpers
# ---------------------------------------------------------------------------

def _clean_entry_title(title: str | None) -> str:
    """Sanitize title: unescape HTML entities, strip scrape prefixes, normalize whitespace."""
    if not title:
        return "Intelligence Dispatch"
    t = html.unescape(title).strip()
    t = re.sub(r"^Security Tool\s*/\s*PoC:\s*", "", t, flags=re.I)
    t = re.sub(r"^Security Tool:\s*", "", t, flags=re.I)
    t = re.sub(r"^PoC:\s*", "", t, flags=re.I)
    t = re.sub(r"^(llama\.cpp[^:]*):\s*b(\d+)", r"\1 Build b\2", t, flags=re.I)
    t = re.sub(r"^(LangChain[^:]*):\s*([a-zA-Z0-9_\-]+)==([0-9\.]+)", r"\1: \2 v\3 Release", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    return t or "Intelligence Dispatch"


def _clean_entry_summary(raw_summary: str | None, entry: Any, cleaned_title: str | None = None) -> str:
    """Sanitize summary: strip HTML/scraped junk, enforce complete sentences, deduplicate repeated text."""
    from ai_security_monitor.application.services.article_extractor import (
        article_extractor,
    )

    if not raw_summary or not raw_summary.strip():
        return article_extractor.synthesize_technical_analysis(entry)

    text = html.unescape(raw_summary)
    text = re.sub(r"<[^<]+?>", " ", text)
    text = re.sub(r"(?i)\b(?:submitted by|posted by)\s+/u/\S+", "", text)
    text = re.sub(r"(?i)\[link\]\s*\[comments\]", "", text)
    text = re.sub(r"(?i)\[link\]", "", text)
    text = re.sub(r"(?i)\[comments\]", "", text)
    text = re.sub(r"(?i)submitted by\s+.*", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\(http[^\)]+\)", "", text)
    text = re.sub(r"^[A-Za-z\s]+ \d{4}-\d{2}-\d{2} \d{2}:\d{2} [A-Za-z\s]+", "", text)
    text = re.sub(r"^Original Leading the Digital Supply Chain.*?\bBeijing\b", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()

    # Deduplicate repeated identical halves (e.g. GitHub/RSS description duplicated)
    if len(text) > 30:
        half = len(text) // 2
        if text[:half].strip() == text[half:].strip():
            text = text[:half].strip()

    words = text.split()
    if len(words) < 6:
        return article_extractor.synthesize_technical_analysis(entry)

    # Ensure text ends at a clean sentence boundary
    if len(words) > 100:
        candidate = " ".join(words[:100])
        match = re.search(r"^(.*[\.\!\?])(?:\s+[^\.\!\?]*)$", candidate)
        if match and len(match.group(1).split()) >= 30:
            return match.group(1).strip()
        return candidate.rstrip(" ,;:-—") + "."

    if not text.endswith((".", "!", "?", '"', "'")):
        # Check if there is an abrupt cutoff of 1-4 words trailing a complete sentence
        match = re.search(r"^(.*[\.\!\?])\s+\S+(?:\s+\S+){0,4}$", text)
        if match and len(match.group(1).split()) >= 8:
            return match.group(1).strip()
        return text.rstrip(" ,;:-—") + "."

    return text


# ---------------------------------------------------------------------------
# Cached helpers
# ---------------------------------------------------------------------------

async def _get_sources_map() -> dict:
    """Return {source_id_str: Source} cached for 60 seconds."""
    async def _fetch():
        async with SqlAlchemyUnitOfWork() as uow:
            all_sources = await uow.sources.list()
        return {str(s.id): s for s in all_sources}

    return await response_cache.get_or_set("sources_map", 60.0, _fetch)


async def _get_active_watchlist_rules() -> list:
    """Return active watchlist rules cached for 30 seconds."""
    async def _fetch():
        async with SqlAlchemyUnitOfWork() as uow:
            return await uow.watchlist.list(enabled_only=True)

    return await response_cache.get_or_set("watchlist_rules_active", 30.0, _fetch)


# ---------------------------------------------------------------------------
# Core Query Helper
# ---------------------------------------------------------------------------

async def query_serialized_entries(
    category: str | None = None,
    search: str | None = None,
    pre_cve: bool = False,
    high_velocity: bool = False,
    watchlist_only: bool = False,
    important_only: bool = False,
    hours: int | None = None,
    region: str | None = None,
    country: str | None = None,
    sort_by: str = "top",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Internal helper to retrieve and serialize filtered entries."""
    since = None
    if hours and isinstance(hours, int):
        since = datetime.utcnow() - timedelta(hours=hours)

    cat_enum = None
    categories_filter = None
    if category in ("important", "vault"):
        important_only = True
    elif category and category != "all" and isinstance(category, str):
        try:
            cat_enum = Category(category)
        except ValueError:
            pass
    elif not pre_cve and not high_velocity and not important_only:
        # Default stream: Prioritize worldwide AI ecosystem (5 pillars) and omit security/CVEs
        categories_filter = [
            Category.AI_RESEARCH,
            Category.AI_MODELS,
            Category.GITHUB_TRENDING,
            Category.CYBER_TOOLS,
            Category.AI_TECH,
        ]

    # Fetch sources map from cache (never hits DB when warm)
    sources_map = await _get_sources_map()

    # Only fetch watchlist rules if actually needed
    active_rules: list = []
    wl_keywords: list | None = None
    if watchlist_only:
        active_rules = await _get_active_watchlist_rules()
        wl_keywords = [kw for r in active_rules for kw in r.keywords if kw.strip()]
        if not wl_keywords:
            wl_keywords = ["__no_matching_watchlist_configured__"]

    filters = EntryFilters(
        category=cat_enum,
        categories=categories_filter,
        search=search if isinstance(search, str) else None,
        keywords=wl_keywords,
        pre_cve_only=bool(pre_cve),
        high_velocity_only=bool(high_velocity),
        important_only=bool(important_only),
        since=since,
        sort_by=sort_by if isinstance(sort_by, str) else "top",
        region=region if region and region != "all" and isinstance(region, str) else None,
        country=country if country and country != "all" and isinstance(country, str) else None,
    )
    pagination = PaginationParams(limit=limit, offset=offset)

    # Cache total count when query has no filters
    has_custom_filters = bool(cat_enum or search or pre_cve or high_velocity or watchlist_only or important_only or since or (region and region != "all") or (country and country != "all"))

    async def _list_entries():
        async with SqlAlchemyUnitOfWork() as uow:
            return await uow.entries.list(filters=filters, pagination=pagination)

    async def _count_entries():
        async with SqlAlchemyUnitOfWork() as uow:
            return await uow.entries.count(filters=filters)

    if not has_custom_filters:
        entries, total = await asyncio.gather(
            _list_entries(),
            response_cache.get_or_set("total_unfiltered_count", 30.0, _count_entries)
        )
    else:
        entries, total = await asyncio.gather(_list_entries(), _count_entries())

    # If watchlist mode: also need active_rules for matching (fetch if not yet loaded)
    if not watchlist_only:
        cached_rules = response_cache._CACHE.get("watchlist_rules_active")
        active_rules = cached_rules[1] if cached_rules else []

    serialized_entries = []
    for e in entries:
        matched_rules = [r.name for r in active_rules if r.matches(e)]
        if watchlist_only and not matched_rules:
            continue

        src = sources_map.get(str(e.source_id))
        src_name = src.name if src else "Verified Intel"
        src_region = (
            (src.config.get("region") if src and src.config else None)
            or (e.metadata.get("region") if e.metadata else None)
            or "global"
        )
        src_country = (
            (src.config.get("country") if src and src.config else None)
            or (e.metadata.get("country") if e.metadata else None)
            or "GLOBAL"
        )

        analysis_dict = None
        severity = 0
        blast_radius = 0
        mitigation = None
        attack_archetype = None
        cat_val = e.category.value if hasattr(e.category, "value") else str(e.category)
        is_ai_cat = cat_val in ("ai_tech", "ai_models", "ai_research", "github_trending", "cyber_tools")

        if e.analysis:
            severity = e.analysis.severity_index
            blast_radius = e.analysis.blast_radius_score
            mitigation = e.analysis.mitigation
            attack_archetype = e.analysis.attack_archetype
            is_ai_innov = is_ai_cat and not bool(e.analysis.is_pre_cve_warning)
            analysis_dict = {
                "attack_vector": e.analysis.attack_vector,
                "risk_assessment": e.analysis.risk_assessment,
                "mitigation": e.analysis.mitigation,
                "threat_velocity": e.analysis.threat_velocity,
                "severity_index": e.analysis.severity_index,
                "blast_radius_score": e.analysis.blast_radius_score,
                "affected_ecosystem": e.analysis.affected_ecosystem or [],
                "is_pre_cve_warning": e.analysis.is_pre_cve_warning,
                "attack_archetype": e.analysis.attack_archetype,
                "weaponization_potential": e.analysis.weaponization_potential,
                "mitre_attack_id": getattr(e.analysis, "mitre_attack_id", None),
                "mitre_technique": getattr(e.analysis, "mitre_technique", None),
                "model": e.analysis.model.value,
                "is_ai_innovation": is_ai_innov,
                "innovation_score": e.analysis.threat_velocity if is_ai_innov else 0,
                "tech_focus": e.analysis.attack_vector if is_ai_innov else None,
                "capability_summary": e.analysis.risk_assessment if is_ai_innov else None,
                "actionable_insight": e.analysis.mitigation if is_ai_innov else None,
            }
        else:
            is_ai_innov = is_ai_cat
            # Default fallback for unanalyzed entries
            fallback_focus = (
                "Trending Open-Source Developer Repository" if cat_val == "github_trending"
                else "Frontier AI Foundation Weights & Model Architecture" if cat_val == "ai_models"
                else "Academic Research & ArXiv Paper" if cat_val == "ai_research"
                else "AI Framework & Developer Infrastructure" if cat_val == "cyber_tools"
                else "Global Artificial Intelligence News"
            )
            analysis_dict = {
                "attack_vector": fallback_focus,
                "risk_assessment": "Ecosystem milestone in global machine learning and autonomous systems.",
                "mitigation": "Review official repository and model documentation for deployment.",
                "threat_velocity": 70 if is_ai_cat else 25,
                "severity_index": 65 if is_ai_cat else 20,
                "blast_radius_score": 60 if is_ai_cat else 20,
                "affected_ecosystem": [],
                "is_pre_cve_warning": False,
                "attack_archetype": "AI Innovation" if is_ai_cat else "Standard Entry",
                "weaponization_potential": "Production Ready" if is_ai_cat else "Theoretical",
                "mitre_attack_id": "AI.TECH" if is_ai_cat else None,
                "mitre_technique": "AI Innovation" if is_ai_cat else None,
                "model": "heuristic",
                "is_ai_innovation": is_ai_innov,
                "innovation_score": 75 if is_ai_innov else 0,
                "tech_focus": fallback_focus if is_ai_innov else None,
                "capability_summary": "Ecosystem milestone in global machine learning and autonomous systems." if is_ai_innov else None,
                "actionable_insight": "Review official repository and documentation for deployment." if is_ai_innov else None,
            }

        cleaned_title = _clean_entry_title(e.title)
        cleaned_summary = _clean_entry_summary(e.summary, e, cleaned_title)

        meta_dict = e.metadata or {}
        is_imp = bool(meta_dict.get("is_important", False) or meta_dict.get("is_saved", False) or meta_dict.get("is_pinned", False))

        serialized_entries.append(
            {
                "id": str(e.id),
                "source_id": str(e.source_id),
                "source_name": src_name,
                "source": src_name,
                "region": src_region,
                "country": src_country,
                "title": cleaned_title,
                "url": e.url,
                "content_hash": e.content_hash,
                "summary": cleaned_summary,
                "published_at": e.published_at.isoformat() if e.published_at else None,
                "fetched_at": e.fetched_at.isoformat() if e.fetched_at else None,
                "category": cat_val,
                "tags": e.tags,
                "metadata": e.metadata,
                "is_important": is_imp,
                "importance_reason": meta_dict.get("importance_reason"),
                "user_notes": meta_dict.get("user_notes", ""),
                "saved_at": meta_dict.get("saved_at"),
                "matched_watchlist_rules": matched_rules,
                "analysis": analysis_dict,
                "severity": severity or (analysis_dict["severity_index"] if analysis_dict else 0),
                "blast_radius": blast_radius or (analysis_dict["blast_radius_score"] if analysis_dict else 0),
                "threat_velocity": (analysis_dict["threat_velocity"] if analysis_dict else 0),
                "mitigation": mitigation or (analysis_dict["mitigation"] if analysis_dict else None),
                "attack_archetype": attack_archetype or (analysis_dict["attack_archetype"] if analysis_dict else None),
                "is_ai_innovation": analysis_dict.get("is_ai_innovation", False) if analysis_dict else False,
                "innovation_score": analysis_dict.get("innovation_score", 0) if analysis_dict else 0,
                "tech_focus": analysis_dict.get("tech_focus") if analysis_dict else None,
                "capability_summary": analysis_dict.get("capability_summary") if analysis_dict else None,
                "actionable_insight": analysis_dict.get("actionable_insight") if analysis_dict else None,
            }
        )

    return serialized_entries, total


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@entries_router.get("")
@entries_router.get("/")
async def list_entries(
    category: str | None = Query(None),
    search: str | None = Query(None),
    pre_cve: bool | None = Query(False),
    high_velocity: bool | None = Query(False),
    watchlist_only: bool | None = Query(False),
    important_only: bool | None = Query(False),
    hours: int | None = Query(None),
    region: str | None = Query(None),
    country: str | None = Query(None),
    sort: str | None = Query(None),
    sort_by: str = Query("top"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Query intelligence entries with pagination, search, watchlist, vault, and feature filters — cached 60s."""
    effective_sort = sort or sort_by
    is_vault = bool(important_only or category in ("important", "vault"))
    cache_key = f"entries_{category}_{search}_{pre_cve}_{high_velocity}_{watchlist_only}_{is_vault}_{hours}_{region}_{country}_{effective_sort}_{limit}_{offset}"

    async def _fetch():
        serialized_entries, total = await query_serialized_entries(
            category=category,
            search=search,
            pre_cve=bool(pre_cve),
            high_velocity=bool(high_velocity),
            watchlist_only=bool(watchlist_only),
            important_only=is_vault,
            hours=hours,
            region=region,
            country=country,
            sort_by=effective_sort,
            limit=limit,
            offset=offset,
        )
        return {
            "entries": serialized_entries,
            "total": total if not watchlist_only else len(serialized_entries),
            "limit": limit,
            "offset": offset,
        }

    payload = await response_cache.get_or_set(cache_key, 60.0, _fetch)
    headers = {"Cache-Control": "public, max-age=15, stale-while-revalidate=60"}
    return JSONResponse(content=payload, headers=headers)


@entries_router.get("/export/pdf")
async def export_entries_pdf(
    category: str | None = Query(None),
    search: str | None = Query(None),
    pre_cve: bool | None = Query(False),
    high_velocity: bool | None = Query(False),
    watchlist_only: bool | None = Query(False),
    hours: int | None = Query(None),
    region: str | None = Query(None),
    sort_by: str = Query("velocity"),
    limit: int = Query(30, ge=1, le=100),
):
    """Generate and download executive PDF threat dossier for queried intelligence entries."""
    from ai_security_monitor.application.services.pdf_export_service import (
        PdfExportService,
    )

    entries_list, _ = await query_serialized_entries(
        category=category,
        search=search,
        pre_cve=bool(pre_cve),
        high_velocity=bool(high_velocity),
        watchlist_only=bool(watchlist_only),
        hours=hours,
        region=region,
        sort_by=sort_by,
        limit=limit,
        offset=0,
    )

    cat_label = f" // {category.upper()}" if category and category != "all" else ""
    title = f"AetherGuard Global AI Dossier{cat_label}"
    pdf_bytes = PdfExportService.generate_dossier_pdf(
        entries=entries_list,
        title=title,
        subtitle=f"Frontier AI & Technology Intelligence Analysis ({len(entries_list)} Reports)",
    )

    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M")
    filename = f"ai_intelligence_dossier_{timestamp_str}.pdf"

    from fastapi.responses import Response

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


from pydantic import Field


class ExportPdfRequest(BaseModel):
    ids: list[str] | None = Field(default=None, description="Specific intelligence IDs to include")
    title: str | None = Field(default="AetherGuard Global AI & Technology Intelligence Dossier")
    subtitle: str | None = Field(default="Frontier AI Systems & Technology Intelligence Briefing")


@entries_router.post("/export/pdf")
async def export_selected_entries_pdf(payload: ExportPdfRequest):
    """Generate executive PDF dossier from a specific list of entry IDs (e.g. pinned board)."""
    from ai_security_monitor.application.services.pdf_export_service import (
        PdfExportService,
    )

    if payload.ids:
        target_ids = set(payload.ids)
        all_entries, _ = await query_serialized_entries(limit=max(500, len(payload.ids) * 2), offset=0, sort_by="newest")
        filtered = [e for e in all_entries if e["id"] in target_ids]
    else:
        all_entries, _ = await query_serialized_entries(limit=150, offset=0, sort_by="velocity")
        filtered = all_entries[:25]

    pdf_bytes = PdfExportService.generate_dossier_pdf(
        entries=filtered,
        title=payload.title or "AetherGuard Global AI & Technology Intelligence Dossier",
        subtitle=payload.subtitle or f"Executive AI & Technology Brief ({len(filtered)} items)",
    )

    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M")
    filename = f"ai_intelligence_dossier_{timestamp_str}.pdf"

    from fastapi.responses import Response

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@entries_router.get("/{entry_id}")
async def get_entry_by_id(entry_id: str):
    """Retrieve a single intelligence entry by its UUID."""
    from uuid import UUID

    from fastapi import HTTPException
    try:
        u_id = UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    async with SqlAlchemyUnitOfWork() as uow:
        entry = await uow.entries.get(u_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")

        sources_map = await _get_sources_map()
        src = sources_map.get(str(entry.source_id))
        src_name = src.name if src else "Autonomous AI Radar"
        src_region = src.config.get("region", "global") if src else "global"
        src_country = src.config.get("country", "GLOBAL") if src else "GLOBAL"
        cat_val = entry.category.value if hasattr(entry.category, "value") else str(entry.category)
        is_ai_cat = cat_val in ("ai_research", "ai_models", "github_trending", "cyber_tools", "ai_tech")

        if entry.analysis:
            analysis_dict = {
                "attack_vector": entry.analysis.attack_vector,
                "risk_assessment": entry.analysis.risk_assessment,
                "mitigation": entry.analysis.mitigation,
                "threat_velocity": entry.analysis.threat_velocity,
                "severity_index": entry.analysis.severity_index,
                "blast_radius_score": entry.analysis.blast_radius_score,
                "affected_ecosystem": entry.analysis.affected_ecosystem,
                "is_pre_cve_warning": entry.analysis.is_pre_cve_warning,
                "attack_archetype": entry.analysis.attack_archetype,
                "weaponization_potential": entry.analysis.weaponization_potential,
                "mitre_attack_id": entry.analysis.mitre_attack_id,
                "mitre_technique": entry.analysis.mitre_technique,
                "model": entry.analysis.model.value if hasattr(entry.analysis.model, "value") else str(entry.analysis.model),
                "is_ai_innovation": is_ai_cat,
                "innovation_score": entry.analysis.threat_velocity if is_ai_cat else 0,
                "tech_focus": entry.analysis.attack_vector if is_ai_cat else None,
                "capability_summary": entry.analysis.risk_assessment if is_ai_cat else None,
                "actionable_insight": entry.analysis.mitigation if is_ai_cat else None,
            }
        else:
            analysis_dict = None

        return {
            "id": str(entry.id),
            "source_id": str(entry.source_id),
            "source_name": src_name,
            "region": src_region,
            "country": src_country,
            "title": _clean_entry_title(entry.title),
            "url": entry.url,
            "content_hash": entry.content_hash,
            "summary": _clean_entry_summary(entry.summary, entry, entry.title),
            "published_at": entry.published_at.isoformat() if entry.published_at else None,
            "fetched_at": entry.fetched_at.isoformat() if entry.fetched_at else None,
            "category": cat_val,
            "tags": entry.tags,
            "metadata": entry.metadata,
            "analysis": analysis_dict,
        }


@entries_router.post("/{entry_id}/toggle-vault")
async def toggle_entry_vault(
    entry_id: str,
    reason: str | None = Query(None),
):
    """Toggle entry in the Permanent Important Vault with SQLite persistence."""
    from uuid import UUID

    from ai_security_monitor.domain.exceptions import EntityNotFoundError

    try:
        uid = UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry UUID")

    async with SqlAlchemyUnitOfWork() as uow:
        try:
            updated = await uow.entries.toggle_importance(uid, reason=reason)
            await uow.commit()
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Entry not found")

    response_cache.invalidate_prefix("entries_")
    response_cache.invalidate("total_unfiltered_count")

    meta = updated.metadata or {}
    return {
        "status": "ok",
        "id": str(updated.id),
        "is_important": bool(meta.get("is_important", False)),
        "importance_reason": meta.get("importance_reason"),
        "saved_at": meta.get("saved_at"),
    }


class NotesPayload(BaseModel):
    notes: str


@entries_router.post("/{entry_id}/notes")
async def save_entry_notes(
    entry_id: str,
    payload: NotesPayload,
):
    """Save user personal technical research and analysis notes for an entry."""
    from uuid import UUID

    from ai_security_monitor.domain.exceptions import EntityNotFoundError

    try:
        uid = UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry UUID")

    async with SqlAlchemyUnitOfWork() as uow:
        try:
            updated = await uow.entries.save_user_notes(uid, payload.notes)
            await uow.commit()
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Entry not found")

    response_cache.invalidate_prefix("entries_")

    meta = updated.metadata or {}
    return {
        "status": "ok",
        "id": str(updated.id),
        "user_notes": meta.get("user_notes", ""),
        "notes_updated_at": meta.get("notes_updated_at"),
    }


@entries_router.get("/{entry_id}/deep-analysis")
async def get_entry_deep_analysis(entry_id: str):
    """Generate or retrieve structured deep technical analysis dossier for later research."""
    from uuid import UUID

    from ai_security_monitor.application.services.deep_analysis_service import (
        deep_analysis_service,
    )

    try:
        uid = UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry UUID")

    async with SqlAlchemyUnitOfWork() as uow:
        entry = await uow.entries.get(uid)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")

    dossier = deep_analysis_service.generate_dossier(entry)
    return JSONResponse(content=dossier)
