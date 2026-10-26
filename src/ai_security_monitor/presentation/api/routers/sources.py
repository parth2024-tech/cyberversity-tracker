"""
Sources API router.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ai_security_monitor.core.auth import require_admin_auth
from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.cache import response_cache
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.presentation.api.limiter import limiter

sources_router = APIRouter(prefix="/sources")


class SourceToggleRequest(BaseModel):
    enabled: bool


class SourceCreateRequest(BaseModel):
    name: str
    url: str
    category: str = "github_trending"
    type: str = "rss"
    rate_limit_seconds: int = 300
    enabled: bool = True
    query: str | None = None
    config: dict = {}


@sources_router.get("")
@sources_router.get("/")
async def list_sources(all_sources: bool = True):
    """List all configured intelligence sources — cached for 30s."""
    cache_key = f"sources_list_all_{all_sources}"

    async def _fetch():
        async with SqlAlchemyUnitOfWork() as uow:
            sources = await uow.sources.list(enabled_only=not all_sources)
            return {
                "sources": [
                    {
                        "id": str(s.id),
                        "name": s.name,
                        "category": s.category.value,
                        "type": s.type.value,
                        "url": s.url,
                        "enabled": s.enabled,
                        "rate_limit_seconds": s.rate_limit_seconds,
                        "last_fetched_at": s.last_fetched_at.isoformat()
                        if s.last_fetched_at
                        else None,
                        "last_status": s.last_status.value if s.last_status else None,
                        "last_entries_new": s.last_entries_new,
                        "config": s.config,
                    }
                    for s in sources
                ]
            }

    data = await response_cache.get_or_set(cache_key, 30.0, _fetch)
    return JSONResponse(content=data, headers={"Cache-Control": "public, max-age=30"})


@sources_router.get("/health")
async def get_sources_health():
    """Retrieve operational telemetry and diagnostic health for all configured intelligence sources."""
    from ai_security_monitor.application.services.source_health_service import (
        source_health_service,
    )

    report = source_health_service.get_health_report()
    return JSONResponse(content=report)


@sources_router.post("/{source_id}/toggle")
async def toggle_source(source_id: str, req: SourceToggleRequest):
    """Enable or disable a specific intelligence source."""
    async with SqlAlchemyUnitOfWork() as uow:
        try:
            s_uuid = UUID(source_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid source UUID")

        source = await uow.sources.get(s_uuid)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        source.enabled = req.enabled
        await uow.sources.update(source)
        await uow.commit()

        return {
            "status": "success",
            "source_id": str(source.id),
            "enabled": source.enabled,
        }


@sources_router.post("/fetch")
@limiter.limit("5/minute")
async def trigger_fetch_sweep(
    request: Request,
    _admin: bool = Depends(require_admin_auth),
):
    """Trigger an immediate radar sweep across all sources and push all queued entries."""
    from ai_security_monitor.application.services.autonomous_triage_service import (
        get_triage_service,
    )
    from ai_security_monitor.application.services.monitor_service import MonitorService

    service = MonitorService()
    results = await service.fetch_all()

    # Automatically push and process all queued entries to website
    triage_svc = get_triage_service()
    queued_pushed = await triage_svc.push_all_queued()

    return {
        "status": "success",
        "results": results,
        "queued_pushed": queued_pushed,
    }


@sources_router.post("")
@sources_router.post("/")
async def create_source(
    req: SourceCreateRequest,
    _admin: bool = Depends(require_admin_auth),
):
    """Add a new intelligence source to the registry."""
    try:
        cat_enum = Category(req.category)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{req.category}'. Allowed: {[c.value for c in Category]}",
        )

    try:
        type_enum = SourceType(req.type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source type '{req.type}'. Allowed: {[t.value for t in SourceType]}",
        )

    async with SqlAlchemyUnitOfWork() as uow:
        existing = await uow.sources.get_by_name(req.name)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"A source with name '{req.name}' already exists",
            )

        new_source = Source(
            name=req.name,
            url=req.url,
            category=cat_enum,
            type=type_enum,
            rate_limit_seconds=req.rate_limit_seconds,
            enabled=req.enabled,
            query=req.query,
            config=req.config,
        )
        created = await uow.sources.add(new_source)
        await uow.commit()

    response_cache.invalidate_prefix("sources_")
    return {
        "status": "success",
        "id": str(created.id),
        "name": created.name,
        "category": created.category.value,
        "type": created.type.value,
        "enabled": created.enabled,
    }


@sources_router.delete("/{source_id}")
async def delete_source(
    source_id: str,
    _admin: bool = Depends(require_admin_auth),
):
    """Delete an intelligence source from the registry."""
    try:
        s_uuid = UUID(source_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid source UUID")

    async with SqlAlchemyUnitOfWork() as uow:
        deleted = await uow.sources.delete(s_uuid)
        if not deleted:
            raise HTTPException(status_code=404, detail="Source not found")
        await uow.commit()

    response_cache.invalidate_prefix("sources_")
    return {
        "status": "success",
        "deleted_id": source_id,
        "message": "Source successfully deleted",
    }
