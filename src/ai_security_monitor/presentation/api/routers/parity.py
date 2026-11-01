"""
Language-Parity SLO Router.

Surfaces language-parity metrics, Chinese vs English capture ratios,
ingestion latency distribution, and executive markdown reports.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ai_security_monitor.application.services.language_parity_service import (
    language_parity_service,
)
from ai_security_monitor.infrastructure.database.unit_of_work import (
    UnitOfWork,
    get_unit_of_work,
)

parity_router = APIRouter(prefix="/parity", tags=["Language Parity SLO"])


class ParityReportResponse(BaseModel):
    markdown: str
    period_days: int
    data_source: str
    slo_latency_met: bool
    slo_capture_active: bool


@parity_router.get("/metrics")
async def get_parity_metrics(
    days: int = Query(default=7, ge=1, le=90, description="Trailing window in days"),
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> dict[str, Any]:
    """Get language-parity telemetry metrics (capture counts, median latency, ratios)."""
    metrics = await language_parity_service.compute_parity_metrics(uow.session, days=days)
    return metrics.to_dict()


@parity_router.get("/report", response_model=ParityReportResponse)
async def get_parity_report(
    days: int = Query(default=7, ge=1, le=90, description="Trailing window in days"),
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> ParityReportResponse:
    """Generate executive markdown report for language-parity SLO compliance."""
    metrics = await language_parity_service.compute_parity_metrics(uow.session, days=days)
    report_md = language_parity_service.format_markdown_report(metrics)
    return ParityReportResponse(
        markdown=report_md,
        period_days=days,
        data_source=metrics.data_source,
        slo_latency_met=metrics.slo_latency_met,
        slo_capture_active=metrics.slo_capture_active,
    )


@parity_router.post("/snapshot")
async def take_parity_snapshot(
    days: int = Query(default=7, ge=1, le=90),
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> dict[str, Any]:
    """Calculate and persist a historical language-parity snapshot to the database."""
    metrics = await language_parity_service.compute_parity_metrics(uow.session, days=days)
    snapshot = await language_parity_service.record_snapshot(uow.session, metrics)
    return {
        "status": "success",
        "snapshot_id": snapshot.id,
        "timestamp": snapshot.timestamp.isoformat(),
        "zh_count": snapshot.zh_count_7d,
        "en_count": snapshot.en_count_7d,
        "latency_ratio": snapshot.latency_ratio,
    }
