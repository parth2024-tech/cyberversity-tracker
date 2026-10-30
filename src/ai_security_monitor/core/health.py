# Health check endpoints.

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_security_monitor.core.metrics import update_business_metrics
from ai_security_monitor.infrastructure.database.connection import (
    get_db_session,
)

router = APIRouter(tags=["Health"])


@router.get("/health")
@router.get("/health/")
async def health_check():
    """Basic health check."""
    return {
        "status": "healthy",
        "service": "ai-security-monitor",
    }


@router.get("/health/ready")
async def readiness_check(session: AsyncSession = Depends(get_db_session)):
    """Readiness check - verifies database connectivity."""
    try:
        await session.execute(text("SELECT 1"))
        db_healthy = True
    except Exception:
        db_healthy = False

    return {
        "status": "ready" if db_healthy else "not ready",
        "checks": {
            "database": "healthy" if db_healthy else "unhealthy",
        },
    }


@router.get("/health/live")
async def liveness_check():
    """Liveness check - always returns healthy if process is running."""
    return {"status": "alive"}


@router.get("/health/metrics")
async def metrics():
    """Prometheus metrics endpoint - delegates to core.metrics."""
    from ai_security_monitor.core.metrics import metrics_endpoint

    return await metrics_endpoint()


@router.post("/metrics/update")
async def update_metrics(
    entries_by_category: dict[str, int] | None = None,
    high_vel_count: int | None = None,
    pre_cve_count: int | None = None,
):
    """Update business metrics (called by background jobs)."""
    update_business_metrics(entries_by_category, high_vel_count, pre_cve_count)
    return {"status": "updated"}


@router.get("/health/sources")
async def get_source_health_dashboard(
    state: str | None = None,
    region: str | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    """Source health dashboard endpoint reporting deterministic source health states.
    Sorted worst-first (BLOCKED > REDIRECTED > DEAD > STALE > OK).
    """
    from ai_security_monitor.infrastructure.database.repositories import (
        SQLAlchemySourceHealthRepository,
    )

    repo = SQLAlchemySourceHealthRepository(session)
    results = await repo.list(state=state, region=region)
    return {
        "total": len(results),
        "filter": {"state": state, "region": region},
        "sources": results,
    }


@router.post("/health/sources/sync")
async def sync_source_health_dashboard(
    session: AsyncSession = Depends(get_db_session),
):
    """Trigger an explicit synchronization of all source health states from database history."""
    from ai_security_monitor.application.services.source_health_service import (
        source_health_service,
    )

    summary = await source_health_service.sync_all_from_db(session)
    await session.commit()
    return {"status": "synchronized", "summary": summary}

