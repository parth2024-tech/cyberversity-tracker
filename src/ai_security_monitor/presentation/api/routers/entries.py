"""
Entries API router.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from ai_security_monitor.domain.entities import Category
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

entries_router = APIRouter(prefix="/entries")


@entries_router.get("")
@entries_router.get("/")
async def list_entries(
    category: str | None = Query(None),
    search: str | None = Query(None),
    pre_cve: bool | None = Query(False),
    high_velocity: bool | None = Query(False),
    hours: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """Query intelligence entries with pagination, search, and feature filters."""
    since = None
    if hours:
        since = datetime.utcnow() - timedelta(hours=hours)

    cat_enum = None
    if category and category != "all":
        try:
            cat_enum = Category(category)
        except ValueError:
            pass

    filters = EntryFilters(
        category=cat_enum,
        search=search,
        pre_cve_only=pre_cve or False,
        high_velocity_only=high_velocity or False,
        since=since
    )
    pagination = PaginationParams(limit=limit, offset=offset)

    async with SqlAlchemyUnitOfWork() as uow:
        entries = await uow.entries.list(filters=filters, pagination=pagination)
        total = await uow.entries.count(filters=filters)

        serialized_entries = []
        for e in entries:
            analysis_dict = None
            if e.analysis:
                analysis_dict = {
                    "attack_vector": e.analysis.attack_vector,
                    "risk_assessment": e.analysis.risk_assessment,
                    "mitigation": e.analysis.mitigation,
                    "threat_velocity": e.analysis.threat_velocity,
                    "severity_index": e.analysis.severity_index,
                    "blast_radius_score": e.analysis.blast_radius_score,
                    "affected_ecosystem": e.analysis.affected_ecosystem,
                    "is_pre_cve_warning": e.analysis.is_pre_cve_warning,
                    "attack_archetype": e.analysis.attack_archetype,
                    "weaponization_potential": e.analysis.weaponization_potential,
                    "model": e.analysis.model.value
                }

            serialized_entries.append({
                "id": str(e.id),
                "source_id": str(e.source_id),
                "title": e.title,
                "url": e.url,
                "content_hash": e.content_hash,
                "summary": e.summary,
                "published_at": e.published_at.isoformat() if e.published_at else None,
                "fetched_at": e.fetched_at.isoformat() if e.fetched_at else None,
                "category": e.category.value,
                "tags": e.tags,
                "metadata": e.metadata,
                "analysis": analysis_dict
            })

        return {
            "entries": serialized_entries,
            "total": total,
            "limit": limit,
            "offset": offset
        }
