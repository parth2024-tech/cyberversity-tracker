"""
Watchlist and Custom AI Ecosystem Alert Rules API router (Feature 11).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ai_security_monitor.application.services.watchlist_alert_service import (
    WatchlistAlertService,
)
from ai_security_monitor.domain.entities import Category
from ai_security_monitor.domain.watchlist import WatchlistRule
from ai_security_monitor.infrastructure.database.unit_of_work import (
    UnitOfWork,
    get_unit_of_work,
)

watchlist_router = APIRouter(prefix="/watchlist", tags=["Watchlist"])
_alert_service = WatchlistAlertService()


class WatchlistRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Rule name")
    keywords: list[str] = Field(
        default=[], description="Keywords or framework identifiers to track"
    )
    categories: list[str] = Field(default=[], description="Category filters (optional)")
    min_threat_velocity: int = Field(
        default=0, ge=0, le=100, description="Minimum threat velocity threshold"
    )
    enabled: bool = Field(default=True, description="Rule active status")

    # Feature 11 Multi-Attribute Rules & Alert Channels
    lab: str | None = Field(
        default=None, description="Target AI lab (e.g. DeepSeek, Meta, OpenAI)"
    )
    model_family: str | None = Field(
        default=None, description="Model family (e.g. Qwen, Llama, Claude)"
    )
    region: str | None = Field(
        default=None, description="Geographic region (e.g. china, us, europe)"
    )
    min_score: float | None = Field(
        default=None, ge=0, le=100, description="Minimum AI Newsworthiness score"
    )
    channel: str = Field(
        default="telegram",
        description="Alert channel (telegram, slack, discord, email, console)",
    )
    channel_config: dict[str, Any] = Field(
        default={}, description="Channel-specific configuration"
    )


class WatchlistRuleResponse(BaseModel):
    id: str
    name: str
    keywords: list[str]
    categories: list[str]
    min_threat_velocity: int
    enabled: bool
    created_at: str
    lab: str | None = None
    model_family: str | None = None
    region: str | None = None
    min_score: float | None = None
    channel: str = "telegram"
    channel_config: dict[str, Any] = {}
    rules_json: dict[str, Any] = {}


class ToggleRuleRequest(BaseModel):
    enabled: bool


class EvaluateEntryRequest(BaseModel):
    entry_id: UUID
    story_id: UUID | None = None
    bypass_quiet_hours: bool = False
    max_per_hour: int | None = None


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
                "categories": [
                    c.value if hasattr(c, "value") else str(c) for c in r.categories
                ],
                "min_threat_velocity": r.min_threat_velocity,
                "enabled": r.enabled,
                "created_at": r.created_at.isoformat(),
                "lab": r.lab,
                "model_family": r.model_family,
                "region": r.region,
                "min_score": r.min_score,
                "channel": r.channel,
                "channel_config": r.channel_config,
                "rules_json": r.rules_json,
            }
            for r in rules
        ],
        "total": len(rules),
    }


@watchlist_router.post(
    "", response_model=WatchlistRuleResponse, status_code=status.HTTP_201_CREATED
)
async def create_watchlist_rule(
    payload: WatchlistRuleCreate, uow: UnitOfWork = Depends(get_unit_of_work)
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
        lab=payload.lab.strip() if payload.lab else None,
        model_family=payload.model_family.strip() if payload.model_family else None,
        region=payload.region.strip() if payload.region else None,
        min_score=payload.min_score,
        channel=payload.channel.strip().lower(),
        channel_config=payload.channel_config,
    )
    saved = await uow.watchlist.add(rule)
    await uow.commit()

    return WatchlistRuleResponse(
        id=str(saved.id),
        name=saved.name,
        keywords=saved.keywords,
        categories=[
            c.value if hasattr(c, "value") else str(c) for c in saved.categories
        ],
        min_threat_velocity=saved.min_threat_velocity,
        enabled=saved.enabled,
        created_at=saved.created_at.isoformat(),
        lab=saved.lab,
        model_family=saved.model_family,
        region=saved.region,
        min_score=saved.min_score,
        channel=saved.channel,
        channel_config=saved.channel_config,
        rules_json=saved.rules_json,
    )


@watchlist_router.delete("/{rule_id}")
async def delete_watchlist_rule(
    rule_id: UUID, uow: UnitOfWork = Depends(get_unit_of_work)
):
    """Delete a watchlist rule."""
    success = await uow.watchlist.delete(rule_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist rule not found"
        )
    await uow.commit()
    return {"message": "Watchlist rule deleted successfully"}


@watchlist_router.post("/{rule_id}/toggle")
async def toggle_watchlist_rule(
    rule_id: UUID,
    payload: ToggleRuleRequest,
    uow: UnitOfWork = Depends(get_unit_of_work),
):
    """Enable or disable a watchlist rule."""
    try:
        updated = await uow.watchlist.toggle(rule_id, payload.enabled)
        await uow.commit()
        return {
            "message": f"Watchlist rule {'enabled' if updated.enabled else 'disabled'}",
            "enabled": updated.enabled,
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@watchlist_router.get("/alerts")
async def list_recent_alerts(
    watch_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    uow: UnitOfWork = Depends(get_unit_of_work),
):
    """List dispatched alerts across watchlist rules."""
    alerts = await uow.watchlist.list_alerts_sent(watch_id=watch_id, limit=limit)
    return {"alerts": alerts, "count": len(alerts)}


@watchlist_router.get("/{rule_id}/alerts")
async def list_rule_alerts(
    rule_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    uow: UnitOfWork = Depends(get_unit_of_work),
):
    """List sent alerts for a specific watchlist rule."""
    rule = await uow.watchlist.get(rule_id)
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist rule not found"
        )
    alerts = await uow.watchlist.list_alerts_sent(watch_id=rule_id, limit=limit)
    return {
        "rule_id": str(rule_id),
        "rule_name": rule.name,
        "alerts": alerts,
        "count": len(alerts),
    }


@watchlist_router.post("/evaluate")
async def evaluate_entry_for_alerts(
    payload: EvaluateEntryRequest,
    uow: UnitOfWork = Depends(get_unit_of_work),
):
    """Evaluate an entry against active rules and dispatch pending alerts."""
    entry = await uow.entries.get(payload.entry_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found"
        )

    eval_results = await _alert_service.evaluate_entry(
        uow=uow,
        entry=entry,
        story_id=payload.story_id,
        bypass_quiet_hours=payload.bypass_quiet_hours,
        max_per_hour=payload.max_per_hour,
    )
    await uow.commit()
    return {"entry_id": str(payload.entry_id), "results": eval_results}
