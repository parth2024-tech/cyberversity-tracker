"""
API router for Structured AI Entity & Benchmark Knowledge Graph (Pillar 4).
Enables querying model timelines, benchmark trajectories, and entity frequency
across the strict 14-day freshness window.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from ai_security_monitor.application.services.entity_rollup_service import (
    EntityRollupService,
)
from ai_security_monitor.infrastructure.cache import response_cache
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

entities_router = APIRouter(prefix="/entities", tags=["Knowledge Graph"])
rollup_service = EntityRollupService()


@entities_router.get("/momentum")
async def get_entity_momentum(
    entity_type: str | None = Query(
        None,
        description="Optional entity type filter (model, repository, benchmark, organization, hardware, arxiv)",
    ),
    limit: int = Query(20, ge=1, le=100, description="Max entities to return"),
    min_3d_mentions: int = Query(
        1, ge=0, le=100, description="Minimum mentions in the last 3 days"
    ),
) -> dict[str, Any]:
    """
    Retrieve AI ecosystem entity momentum z-scores comparing 3-day volume against
    a 28-day historical baseline, complete with 14-day sparklines (Workstream B1).
    """
    cache_key = f"entities_momentum_{entity_type}_{limit}_{min_3d_mentions}"

    async def _fetch() -> dict[str, Any]:
        items = await rollup_service.calculate_momentum_z_scores(
            entity_type=entity_type,
            limit=limit,
            min_3d_mentions=min_3d_mentions,
        )
        return {
            "entity_type": entity_type,
            "limit": limit,
            "count": len(items),
            "as_of_date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "items": items,
        }

    return await response_cache.get_or_set(cache_key, 60.0, _fetch)


@entities_router.post("/rollup/refresh")
async def refresh_entity_rollups(
    days: int = Query(
        30, ge=1, le=90, description="Number of historical days to aggregate"
    ),
) -> dict[str, Any]:
    """
    Refresh daily entity mention rollups and invalidate the momentum response cache.
    """
    updated_count = await rollup_service.aggregate_daily_counts(days=days)
    response_cache.invalidate_prefix("entities_")
    return {
        "status": "ok",
        "records_updated": updated_count,
        "refreshed_at": datetime.now(UTC).isoformat(),
    }


@entities_router.get("/timeline")
async def get_entity_timeline(
    name: str = Query(
        ...,
        description="Entity name or query string (e.g. 'vLLM', 'DeepSeek-R1', 'SWE-bench')",
    ),
    entity_type: str | None = Query(
        None,
        description="Optional entity type filter (model, repository, benchmark, organization, hardware, arxiv)",
    ),
    days: int = Query(14, ge=1, le=14, description="Freshness window in days (max 14)"),
    limit: int = Query(50, ge=1, le=100, description="Max timeline records to return"),
) -> dict[str, Any]:
    """Retrieve chronological timeline of mentions and benchmark metrics for an AI entity."""
    async with SqlAlchemyUnitOfWork() as uow:
        timeline = await uow.entities.query_timeline(
            name=name, entity_type=entity_type, days=days, limit=limit
        )
        return {
            "query": name,
            "entity_type": entity_type,
            "days": days,
            "count": len(timeline),
            "timeline": timeline,
        }


@entities_router.get("/top")
async def get_top_entities(
    entity_type: str | None = Query(
        None,
        description="Optional entity type filter (model, repository, benchmark, organization, hardware)",
    ),
    days: int = Query(14, ge=1, le=14, description="Freshness window in days (max 14)"),
    limit: int = Query(20, ge=1, le=50, description="Max entities to return"),
) -> dict[str, Any]:
    """Retrieve top referenced entities ranked by citation frequency in the past 14 days."""
    async with SqlAlchemyUnitOfWork() as uow:
        top_list = await uow.entities.get_top_entities(
            entity_type=entity_type, days=days, limit=limit
        )
        return {
            "entity_type": entity_type,
            "days": days,
            "count": len(top_list),
            "entities": top_list,
        }


@entities_router.get("/entry/{entry_id}")
async def get_entities_for_entry(entry_id: UUID) -> dict[str, Any]:
    """Retrieve all structured entities extracted for a specific intelligence entry."""
    async with SqlAlchemyUnitOfWork() as uow:
        entities = await uow.entities.get_by_entry(entry_id)
        return {
            "entry_id": str(entry_id),
            "count": len(entities),
            "entities": [
                {
                    "id": str(e.id),
                    "entity_type": e.entity_type.value
                    if hasattr(e.entity_type, "value")
                    else str(e.entity_type),
                    "name": e.name,
                    "display_name": e.display_name,
                    "metric_value": e.metric_value,
                    "context": e.context,
                    "confidence": e.confidence,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in entities
            ],
        }
