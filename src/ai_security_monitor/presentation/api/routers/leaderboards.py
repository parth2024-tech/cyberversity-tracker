"""Leaderboards API router (Feature 8).

Endpoints for managing AI benchmark leaderboards, inspecting historical snapshots,
and triggering polling sweeps.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ai_security_monitor.application.services.leaderboard_service import (
    LeaderboardService,
)
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork

router = APIRouter(prefix="/api/leaderboards", tags=["leaderboards"])


def get_uow() -> UnitOfWork:
    return UnitOfWork()


def get_leaderboard_service(uow: UnitOfWork = Depends(get_uow)) -> LeaderboardService:
    return LeaderboardService(uow_factory=lambda: uow)


@router.get("", response_model=list[dict[str, Any]])
async def list_leaderboards(
    enabled_only: bool = Query(False, description="Filter only enabled leaderboards"),
    uow: UnitOfWork = Depends(get_uow),
) -> list[dict[str, Any]]:
    """List all tracked AI benchmark leaderboards."""
    async with uow:
        leaderboards = await uow.leaderboards.list(enabled_only=enabled_only)
        return [
            {
                "id": str(lb.id),
                "name": lb.name,
                "url": lb.url,
                "parser": lb.parser,
                "category": lb.category,
                "enabled": lb.enabled,
                "status": lb.status,
                "last_snapshot_at": (
                    lb.last_snapshot_at.isoformat() if lb.last_snapshot_at else None
                ),
            }
            for lb in leaderboards
        ]


@router.get("/{leaderboard_id}/snapshots", response_model=list[dict[str, Any]])
async def get_leaderboard_snapshots(
    leaderboard_id: UUID,
    limit: int = Query(10, ge=1, le=100),
    uow: UnitOfWork = Depends(get_uow),
) -> list[dict[str, Any]]:
    """Get recent point-in-time ranking snapshots and diff events for a leaderboard."""
    async with uow:
        lb = await uow.leaderboards.get(leaderboard_id)
        if not lb:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Leaderboard {leaderboard_id} not found",
            )
        snapshots = await uow.leaderboards.list_snapshots(leaderboard_id, limit=limit)
        return [
            {
                "id": str(s.id),
                "leaderboard_id": str(s.leaderboard_id),
                "taken_at": s.taken_at.isoformat(),
                "row_count": s.row_count,
                "diff_events": s.diff_events,
                "top_5": s.rows[:5],
            }
            for s in snapshots
        ]


@router.post("/seed", response_model=list[dict[str, Any]])
async def seed_leaderboards(
    service: LeaderboardService = Depends(get_leaderboard_service),
) -> list[dict[str, Any]]:
    """Seed standard default industry leaderboards (LMSYS Chatbot Arena, Open LLM)."""
    seeded = await service.seed_default_leaderboards()
    return [
        {
            "id": str(lb.id),
            "name": lb.name,
            "url": lb.url,
            "parser": lb.parser,
            "status": lb.status,
        }
        for lb in seeded
    ]


@router.post("/{leaderboard_id}/poll", response_model=dict[str, Any])
async def poll_leaderboard_endpoint(
    leaderboard_id: UUID,
    service: LeaderboardService = Depends(get_leaderboard_service),
) -> dict[str, Any]:
    """Trigger an on-demand poll and snapshot diff for a specific leaderboard."""
    try:
        snapshot, events = await service.poll_leaderboard(leaderboard_id)
        return {
            "snapshot_id": str(snapshot.id),
            "row_count": snapshot.row_count,
            "events_detected": len(events),
            "events": [
                {
                    "event_type": e.event_type,
                    "model": e.model,
                    "rank_delta": e.rank_delta,
                    "summary": e.summary,
                    "severity": e.severity,
                }
                for e in events
            ],
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
