"""
Sources API router.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

sources_router = APIRouter(prefix="/sources")


class SourceToggleRequest(BaseModel):
    enabled: bool


@sources_router.get("")
@sources_router.get("/")
async def list_sources(all_sources: bool = True):
    """List all configured intelligence sources."""
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
                    "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
                    "last_status": s.last_status.value if s.last_status else None,
                    "last_entries_new": s.last_entries_new
                } for s in sources
            ]
        }


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

        return {"status": "success", "source_id": str(source.id), "enabled": source.enabled}
