"""
Statistics API router.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ai_security_monitor.application.services.monitor_service import MonitorService
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

stats_router = APIRouter(prefix="/stats")


def get_monitor_service() -> MonitorService:
    return MonitorService(lambda: SqlAlchemyUnitOfWork())


@stats_router.get("")
@stats_router.get("/")
async def get_system_stats(service: MonitorService = Depends(get_monitor_service)):
    """Retrieve overall system telemetry, counts, and category statistics."""
    return await service.get_stats()


@stats_router.get("/sweep-status")
async def get_sweep_status(service: MonitorService = Depends(get_monitor_service)):
    """Return live sweep freshness: last sweep time, next sweep ETA, per-source last-fetched timestamps."""
    return await service.get_sweep_status()


@stats_router.post("/purge")
async def purge_stale_entries(
    days: int = Query(default=30, ge=1, le=365, description="Delete entries older than this many days"),
    service: MonitorService = Depends(get_monitor_service),
):
    """Manually trigger data hygiene: delete all entries older than `days` days."""
    return await service.purge_stale_entries(older_than_days=days)
