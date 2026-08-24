# Health check endpoints.

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_security_monitor.infrastructure.database.connection import db_manager, get_db_session
from ai_security_monitor.core.metrics import update_business_metrics

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/")
async def health_check():
    """Basic health check."""
    return {
        "status": "healthy",
        "service": "ai-security-monitor",
    }


@router.get("/ready")
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


@router.get("/live")
async def liveness_check():
    """Liveness check - always returns healthy if process is running."""
    return {"status": "alive"}


@router.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint - delegates to core.metrics."""
    from ai_security_monitor.core.metrics import metrics_endpoint
    from starlette.requests import Request
    # Create a mock request
    class MockRequest:
        pass
    return await metrics_endpoint(MockRequest())


@router.post("/metrics/update")
async def update_metrics(
    entries_by_category: dict[str, int] = None,
    high_vel_count: int = None,
    pre_cve_count: int = None,
):
    """Update business metrics (called by background jobs)."""
    update_business_metrics(entries_by_category, high_vel_count, pre_cve_count)
    return {"status": "updated"}
