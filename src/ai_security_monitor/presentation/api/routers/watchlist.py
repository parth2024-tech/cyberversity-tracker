"""
Watchlist and Custom Threat Hunting Rules API router.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ai_security_monitor.domain.entities import Category
from ai_security_monitor.domain.watchlist import WatchlistRule
from ai_security_monitor.infrastructure.database.unit_of_work import (
    UnitOfWork,
    get_unit_of_work,
)

watchlist_router = APIRouter(prefix="/watchlist", tags=["Watchlist"])


class WatchlistRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Rule name")
    keywords: list[str] = Field(..., min_length=1, description="Keywords or framework identifiers to track")
    categories: list[str] = Field(default=[], description="Category filters (optional)")
    min_threat_velocity: int = Field(default=0, ge=0, le=100, description="Minimum threat velocity threshold")
    enabled: bool = Field(default=True, description="Rule active status")


class WatchlistRuleResponse(BaseModel):
    id: str
    name: str
    keywords: list[str]
    categories: list[str]
    min_threat_velocity: int
    enabled: bool
    created_at: str


class ToggleRuleRequest(BaseModel):
    enabled: bool


@watchlist_router.get("", response_model=dict)
async def list_watchlist_rules(uow: UnitOfWork = Depends(get_unit_of_work)):
    """List all custom framework watchlist and threat hunting rules."""
    rules = await uow.watchlist.list()
    return {
        "rules": [
            {
                "id": str(r.id),
                "name": r.name,
                "keywords": r.keywords,
                "categories": [c.value if hasattr(c, "value") else str(c) for c in r.categories],
                "min_threat_velocity": r.min_threat_velocity,
                "enabled": r.enabled,
                "created_at": r.created_at.isoformat(),
            }
            for r in rules
        ],
        "total": len(rules)
    }


@watchlist_router.post("", response_model=WatchlistRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_watchlist_rule(
    payload: WatchlistRuleCreate,
    uow: UnitOfWork = Depends(get_unit_of_work)
):
    """Create a new custom framework watchlist rule."""
    cats = []
    for c in payload.categories:
        try:
            cats.append(Category(c))
        except ValueError:
            pass

    rule = WatchlistRule(
        name=payload.name,
        keywords=[k.strip() for k in payload.keywords if k.strip()],
        categories=cats,
        min_threat_velocity=payload.min_threat_velocity,
        enabled=payload.enabled,
    )
    saved = await uow.watchlist.add(rule)
    await uow.commit()

    return WatchlistRuleResponse(
        id=str(saved.id),
        name=saved.name,
        keywords=saved.keywords,
        categories=[c.value if hasattr(c, "value") else str(c) for c in saved.categories],
        min_threat_velocity=saved.min_threat_velocity,
        enabled=saved.enabled,
        created_at=saved.created_at.isoformat(),
    )


@watchlist_router.delete("/{rule_id}")
async def delete_watchlist_rule(
    rule_id: UUID,
    uow: UnitOfWork = Depends(get_unit_of_work)
):
    """Delete a watchlist rule."""
    success = await uow.watchlist.delete(rule_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist rule not found")
    await uow.commit()
    return {"message": "Watchlist rule deleted successfully"}


@watchlist_router.post("/{rule_id}/toggle")
async def toggle_watchlist_rule(
    rule_id: UUID,
    payload: ToggleRuleRequest,
    uow: UnitOfWork = Depends(get_unit_of_work)
):
    """Enable or disable a watchlist rule."""
    try:
        updated = await uow.watchlist.toggle(rule_id, payload.enabled)
        await uow.commit()
        return {
            "message": f"Watchlist rule {'enabled' if updated.enabled else 'disabled'}",
            "enabled": updated.enabled
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
