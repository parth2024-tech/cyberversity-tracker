"""
Statistics API router.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

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
