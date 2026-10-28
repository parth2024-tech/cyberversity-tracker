"""
Statistics API router — with response caching.

Stats are cached for 30 seconds to prevent DB hammering
when the frontend polls every 60 seconds (or user refreshes quickly).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ai_security_monitor.application.services.monitor_service import MonitorService
from ai_security_monitor.core.auth import require_admin_auth
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


@stats_router.get("/retention")
async def get_retention_status(
    days: int = Query(
        default=7,
        ge=0,
        le=1825,
        description="Check purge candidates older than this many days (0 = all active data)",
    ),
    include_vaulted: bool = Query(
        default=False,
        description="Whether to include permanent vault / starred entries in purge candidates",
    ),
    categories: list[str] | None = Query(
        default=None,
        description="Filter candidate purge entries by categories",
    ),
    service: MonitorService = Depends(get_monitor_service),
):
    """Retrieve current retention policy, active vs soft-purged count, and candidate purge count."""
    return await service.get_retention_status(
        older_than_days=days,
        include_vaulted=include_vaulted,
        categories=categories,
    )


@stats_router.post("/purge")
async def purge_stale_entries(
    days: int = Query(
        default=7,
        ge=0,
        le=1825,
        description="Delete entries older than this many days (0 = all active data)",
    ),
    hard_delete: bool = Query(
        default=False,
        description="Permanently delete matching records from disk immediately (cannot be undone)",
    ),
    include_vaulted: bool = Query(
        default=False,
        description="Whether to also purge vault-protected and landmark entries",
    ),
    categories: list[str] | None = Query(
        default=None,
        description="Filter purged entries by categories",
    ),
    service: MonitorService = Depends(get_monitor_service),
    _admin: bool = Depends(require_admin_auth),
):
    """Manually trigger data hygiene: delete all entries older than `days` days."""
    result = await service.purge_stale_entries(
        older_than_days=days,
        hard_delete=hard_delete,
        include_vaulted=include_vaulted,
        categories=categories,
    )
    return result


@stats_router.post("/restore-purged")
async def restore_purged_entries(
    service: MonitorService = Depends(get_monitor_service),
    _admin: bool = Depends(require_admin_auth),
):
    """Manually restore all soft-purged entries back to active visibility in the dashboard."""
    return await service.restore_purged_entries()


@stats_router.get("/source-yield")
async def get_source_yield(
    days: int = Query(
        default=14,
        ge=1,
        le=30,
        description="Rolling window in days for computing source yield",
    ),
):
    """Calculate empirical intelligence yield (articles per day) per source over a rolling window."""
    from collections import defaultdict
    from datetime import UTC, datetime, timedelta

    from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams

    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with SqlAlchemyUnitOfWork() as uow:
        sources = await uow.sources.list()
        sources_map = {str(s.id): s.name for s in sources}

        source_counts: dict[str, int] = defaultdict(int)
        offset = 0
        batch_size = 200
        while True:
            pagination = PaginationParams(limit=batch_size, offset=offset)
            batch = await uow.entries.list(
                filters=EntryFilters(since=cutoff),
                pagination=pagination,
            )
            if not batch:
                break
            for e in batch:
                src_name = sources_map.get(str(e.source_id), "Unknown Source")
                source_counts[src_name] += 1
            if len(batch) < pagination.limit:
                break
            offset += len(batch)

    yield_data = []
    total_articles = sum(source_counts.values())
    for name, count in sorted(source_counts.items(), key=lambda x: x[1], reverse=True):
        yield_data.append(
            {
                "source_name": name,
                "total_articles": count,
                "articles_per_day": round(count / max(1, days), 2),
            }
        )

    return {
        "window_days": days,
        "total_sources_active": len(yield_data),
        "total_articles": total_articles,
        "overall_articles_per_day": round(total_articles / max(1, days), 2),
        "sources": yield_data,
    }
