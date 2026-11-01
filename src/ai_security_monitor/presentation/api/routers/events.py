"""
Canonical Cross-Lingual Events Router.

Provides language-independent canonical event feeds, dossiers with evidentiary role
partitioning (primary, corroborating, derivative), and claim evidence spans.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from ai_security_monitor.application.services.cross_lingual_event_service import (
    event_service,
)
from ai_security_monitor.infrastructure.database.models import (
    EventDocumentModel,
    EventModel,
)
from ai_security_monitor.infrastructure.database.unit_of_work import (
    UnitOfWork,
    get_unit_of_work,
)

events_router = APIRouter(prefix="/events", tags=["Cross-Lingual Events"])


class EventSummaryResponse(BaseModel):
    id: str
    type: str
    title: str
    version_tag: str | None
    canonical_entity_ids: list[str]
    first_seen_at: str
    first_seen_lang: str
    status: str
    documents_count: int
    languages_covered: list[str]
    claims_count: int
    key_claims: list[dict[str, Any]]


class EventListResponse(BaseModel):
    events: list[EventSummaryResponse]
    total: int
    limit: int
    offset: int


class ClusterResponse(BaseModel):
    status: str
    clustered_count: int


@events_router.get("", response_model=EventListResponse)
async def list_events(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    event_type: str | None = Query(default=None, alias="type"),
    entity_id: str | None = Query(default=None),
    days: int = Query(default=14, ge=1, le=30, description="Freshness window in days"),
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> EventListResponse:
    """
    List language-independent canonical events within the freshness window (max 14 days),
    enriched with cross-lingual document counts and key extracted claims.
    """
    since = datetime.now(UTC) - timedelta(days=days)

    query = (
        select(EventModel)
        .where(
            EventModel.first_seen_at >= since,
            EventModel.status == "active",
        )
        .options(
            selectinload(EventModel.documents).selectinload(
                EventDocumentModel.document
            ),
            selectinload(EventModel.claims),
        )
    )

    if event_type:
        query = query.where(EventModel.type == event_type)

    # Order by first seen descending (newest first)
    query = query.order_by(desc(EventModel.first_seen_at))

    # Fetch total count
    count_query = select(func.count(EventModel.id)).where(
        EventModel.first_seen_at >= since,
        EventModel.status == "active",
    )
    if event_type:
        count_query = count_query.where(EventModel.type == event_type)

    total_count = (await uow.session.execute(count_query)).scalar() or 0

    results = (
        (await uow.session.execute(query.offset(offset).limit(limit))).scalars().all()
    )

    items: list[EventSummaryResponse] = []
    for ev in results:
        # Filter by entity_id if provided
        if entity_id and entity_id not in ev.canonical_entity_ids:
            continue

        langs = list({ed.document.lang for ed in ev.documents if ed.document})
        key_claims = [
            {
                "field": c.field,
                "normalized_value": c.normalized_value,
                "unit": c.unit,
                "confidence": c.confidence,
            }
            for c in ev.claims[:5]
        ]

        items.append(
            EventSummaryResponse(
                id=ev.id,
                type=ev.type,
                title=ev.title,
                version_tag=ev.version_tag,
                canonical_entity_ids=ev.canonical_entity_ids,
                first_seen_at=ev.first_seen_at.isoformat(),
                first_seen_lang=ev.first_seen_lang,
                status=ev.status,
                documents_count=len(ev.documents),
                languages_covered=langs,
                claims_count=len(ev.claims),
                key_claims=key_claims,
            )
        )

    return EventListResponse(
        events=items,
        total=total_count,
        limit=limit,
        offset=offset,
    )


@events_router.get("/{event_id}")
async def get_event_dossier(
    event_id: str,
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> dict[str, Any]:
    """
    Get full cross-lingual event dossier:
    - Language-independent canonical metadata
    - Partitioned documents by evidentiary role (primary, corroborating, derivative)
    - Structured claims with character offset spans in original native text
    - Language parity latency delta between Chinese and English sources
    """
    dossier = await event_service.get_event_dossier(uow.session, event_id)
    if not dossier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )
    return dossier


@events_router.post("/cluster", response_model=ClusterResponse)
async def cluster_documents(
    limit: int = Query(default=100, ge=1, le=500),
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> ClusterResponse:
    """Trigger cross-lingual event clustering pass on unclustered native documents."""
    count = await event_service.cluster_unclustered_documents(uow.session, limit=limit)
    await uow.commit()
    return ClusterResponse(status="success", clustered_count=count)
