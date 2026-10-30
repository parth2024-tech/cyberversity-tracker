"""
Missed-Story Audit API router.
Provides intelligence capture rate, median lag telemetry, and diagnostic blind spot reports.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ai_security_monitor.application.services.audit_service import audit_service
from ai_security_monitor.core.auth import require_admin_auth
from ai_security_monitor.infrastructure.database.connection import get_db_session

audit_router = APIRouter(prefix="/audit", tags=["Missed-Story Audit & Telemetry"])


@audit_router.get("")
async def get_audit_report(
    since: str | None = Query(
        None, description="ISO date or YYYY-MM-DD filter for release dates"
    ),
    region: str | None = Query(
        None, description="Filter audit by region (e.g. 'china', 'us', 'europe')"
    ),
    window_days: int = Query(7, description="Match window in days (+/- release date)"),
    format: str | None = Query(
        "json", description="Output format: 'json' or 'markdown'"
    ),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """
    Get missed-story audit evaluation report against ground-truth AI releases.
    """
    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            pass

    report = await audit_service.run_audit(
        session=session,
        since=since_dt,
        region=region,
        window_days=window_days,
    )
    if format == "markdown":
        return PlainTextResponse(report["markdown_report"])

    return JSONResponse(report)


@audit_router.post("/run")
async def trigger_audit_evaluation(
    since: str | None = Query(None, description="ISO date or YYYY-MM-DD filter"),
    region: str | None = Query(None, description="Filter audit by region"),
    window_days: int = Query(7, description="Match window in days"),
    session: AsyncSession = Depends(get_db_session),
    _admin: bool = Depends(require_admin_auth),
) -> dict[str, Any]:
    """
    Trigger immediate audit evaluation run and persist results.
    """
    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            pass

    report = await audit_service.run_audit(
        session=session,
        since=since_dt,
        region=region,
        window_days=window_days,
    )
    await session.commit()
    return report
