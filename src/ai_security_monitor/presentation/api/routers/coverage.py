"""
Coverage and Frontier AI Lab Intelligence router.
Provides measurable regional coverage analysis, lab telemetry, and gap diagnostics.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ai_security_monitor.application.services.coverage_service import coverage_service
from ai_security_monitor.core.auth import require_admin_auth
from ai_security_monitor.infrastructure.database.connection import get_db_session

coverage_router = APIRouter(prefix="/coverage", tags=["Coverage & Lab Intelligence"])


@coverage_router.get("")
async def get_coverage_report(
    region: str | None = Query(
        None, description="Filter report by region (e.g. 'china', 'us', 'europe')"
    ),
    format: str | None = Query(
        "json", description="Output format: 'json' or 'markdown'"
    ),
    backfill: bool = Query(
        True, description="Automatically backfill lab detection on untagged entries"
    ),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """
    Get comprehensive intelligence coverage report per region, per lab, and gap lists.
    """
    report = await coverage_service.generate_coverage_report(
        session=session,
        target_region=region,
        auto_backfill=backfill,
    )
    if format == "markdown":
        return PlainTextResponse(report["markdown_table"])

    return JSONResponse(report)


@coverage_router.post("/backfill")
async def trigger_lab_backfill(
    limit: int = Query(2000, description="Max untagged entries to scan and tag"),
    session: AsyncSession = Depends(get_db_session),
    _admin: bool = Depends(require_admin_auth),
) -> dict[str, Any]:
    """
    Manually trigger lab detection and subject_region tagging on database entries.
    """
    tagged = await coverage_service.backfill_entry_labs(session=session, limit=limit)
    await session.commit()
    return {
        "status": "success",
        "tagged_count": tagged,
        "tagged_entries_count": tagged,
    }
