"""
Filter Log API router.
Provides inspection endpoints and audit trail for items rejected by the No-Slop Ingestion Filter.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ai_security_monitor.application.services.no_slop_filter import no_slop_filter
from ai_security_monitor.core.auth import require_admin_auth
from ai_security_monitor.infrastructure.database.connection import get_db_session

filter_log_router = APIRouter(prefix="/filter-log", tags=["No-Slop Ingestion Filter"])


class EvaluateFilterRequest(BaseModel):
    title: str = Field(..., description="Title of candidate article or release")
    summary: str = Field("", description="Summary or excerpt text")
    url: str = Field("", description="Article URL")


@filter_log_router.get("")
async def get_filter_log(
    limit: int = Query(100, ge=1, le=500, description="Max entries to return"),
    reason: str | None = Query(None, description="Filter by rejection reason"),
    source_id: str | None = Query(None, description="Filter by source ID"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Retrieve recent items dropped by the no-slop filter for human audit.
    """
    return await no_slop_filter.get_filter_log(
        session=session,
        limit=limit,
        reason=reason,
        source_id=source_id,
    )


@filter_log_router.get("/stats")
async def get_filter_stats(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Get aggregate rejection statistics and breakdown by reason.
    """
    return await no_slop_filter.get_filter_stats(session=session)


@filter_log_router.post("/evaluate")
async def evaluate_text_filter(
    payload: EvaluateFilterRequest,
) -> dict[str, Any]:
    """
    Evaluate candidate text in real time against no-slop filter rules.
    """
    decision = no_slop_filter.evaluate(
        title=payload.title,
        summary=payload.summary,
        url=payload.url,
    )
    return {
        "is_slop": decision.is_slop,
        "reason": decision.reason,
        "matched_pattern": decision.matched_pattern,
    }


@filter_log_router.post("/purge")
async def purge_expired_filter_entries(
    days: int = Query(7, ge=1, description="Retention window in days (default 7)"),
    session: AsyncSession = Depends(get_db_session),
    _admin: bool = Depends(require_admin_auth),
) -> dict[str, Any]:
    """
    Purge expired audit entries older than retention window.
    """
    deleted = await no_slop_filter.purge_expired_filtered_entries(
        session=session, days=days
    )
    await session.commit()
    return {"status": "success", "purged_count": deleted, "retention_days": days}
