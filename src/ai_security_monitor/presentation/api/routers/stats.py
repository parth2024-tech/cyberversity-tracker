"""
Statistics API router — with response caching.

Stats are cached for 30 seconds to prevent DB hammering
when the frontend polls every 60 seconds (or user refreshes quickly).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ai_security_monitor.application.services.monitor_service import MonitorService
from ai_security_monitor.infrastructure.cache import response_cache
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

stats_router = APIRouter(prefix="/stats")


def get_monitor_service() -> MonitorService:
    return MonitorService(lambda: SqlAlchemyUnitOfWork())


@stats_router.get("")
@stats_router.get("/")
async def get_system_stats(service: MonitorService = Depends(get_monitor_service)):
    """Retrieve overall system telemetry, counts, and category statistics — cached 30s."""
    data = await response_cache.get_or_set(
        "stats_totals",
        30.0,
        lambda: service.get_stats(),
    )
    headers = {"Cache-Control": "public, max-age=30, stale-while-revalidate=60"}
    return JSONResponse(content=data, headers=headers)


@stats_router.get("/sweep-status")
async def get_sweep_status(service: MonitorService = Depends(get_monitor_service)):
    """Return live sweep freshness: last sweep time, next sweep ETA, per-source last-fetched timestamps."""
    data = await response_cache.get_or_set(
        "sweep_status",
        15.0,
        lambda: service.get_sweep_status(),
    )
    return JSONResponse(content=data, headers={"Cache-Control": "public, max-age=15"})


@stats_router.post("/purge")
async def purge_stale_entries(
    days: int = Query(default=30, ge=1, le=365, description="Delete entries older than this many days"),
    service: MonitorService = Depends(get_monitor_service),
):
    """Manually trigger data hygiene: delete all entries older than `days` days."""
    result = await service.purge_stale_entries(older_than_days=days)
    # Invalidate stats cache after purge
    response_cache.invalidate("stats_totals")
    return result
