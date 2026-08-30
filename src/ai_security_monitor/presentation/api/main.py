"""
FastAPI application factory with lifespan management.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.health import router as health_router
from ai_security_monitor.core.logging import get_logger, setup_logging
from ai_security_monitor.core.metrics import metrics_middleware
from ai_security_monitor.infrastructure.database.connection import db_manager
from ai_security_monitor.presentation.api.routers import (
    analysis_router,
    audio_router,
    digest_router,
    entries_router,
    newspaper_router,
    sources_router,
    stats_router,
    translation_router,
    triage_router,
    watchlist_router,
)
from ai_security_monitor.presentation.api.websocket.manager import websocket_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager - startup and shutdown."""
    # Startup
    logger.info("Starting AI Security Monitor API", version=settings.app_version)

    # Initialize database
    await db_manager.init_db()
    logger.info("Database initialized")

    # Verify database connectivity
    healthy = await db_manager.health_check()
    if not healthy:
        logger.error("Database health check failed")
    else:
        logger.info("Database health check passed")

    # Auto-seed sources from configuration
    try:
        from ai_security_monitor.application.services.monitor_service import MonitorService
        monitor_service = MonitorService()
        await monitor_service.init_sources()
        logger.info("Sources configuration synchronized with database")
    except Exception as seed_err:
        logger.warn(f"Failed to auto-seed sources: {seed_err}")

    # Start background scheduler (if enabled)
    if settings.scheduler.enabled:
        from ai_security_monitor.application.services.scheduler_service import (
            SchedulerService,
        )
        scheduler = SchedulerService()
        await scheduler.start()
        app.state.scheduler = scheduler
        logger.info("Background scheduler started")

    # Start Autonomous LLM Triage Worker (if enabled)
    if settings.analyzer.autonomous_triage_enabled:
        import asyncio
        from ai_security_monitor.application.services.autonomous_triage_service import (
            get_triage_service,
        )
        from ai_security_monitor.presentation.api.websocket.manager import manager

        triage_service = get_triage_service()

        def _broadcast_to_ws(msg: dict):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(manager.broadcast(msg))
            except Exception:
                pass

        triage_service.set_broadcast_callback(_broadcast_to_ws)
        await triage_service.start()
        app.state.triage_service = triage_service
        logger.info("Autonomous High-Priority LLM Triage Worker started in background")

    yield

    # Shutdown
    logger.info("Shutting down AI Security Monitor API")

    # Stop triage worker
    if hasattr(app.state, "triage_service"):
        await app.state.triage_service.stop()
        logger.info("Autonomous High-Priority LLM Triage Worker stopped")

    # Stop scheduler
    if hasattr(app.state, "scheduler"):
        await app.state.scheduler.stop()
        logger.info("Background scheduler stopped")

    # Close database connections
    await db_manager.close()
    logger.info("Database connections closed")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    # Setup logging first
    setup_logging()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Zero-cost autonomous monitoring for AI technology launches and cybersecurity threats",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Metrics middleware
    app.middleware("http")(metrics_middleware)

    # Include routers
    app.include_router(health_router, prefix="/api", tags=["Health"])
    app.include_router(stats_router, prefix="/api", tags=["Statistics"])
    app.include_router(entries_router, prefix="/api", tags=["Entries"])
    app.include_router(sources_router, prefix="/api", tags=["Sources"])
    app.include_router(analysis_router, prefix="/api", tags=["Analysis"])
    app.include_router(digest_router, prefix="/api", tags=["Digest"])
    app.include_router(digest_router, prefix="/api/telegram", tags=["Telegram"])
    app.include_router(watchlist_router, prefix="/api", tags=["Watchlist"])
    app.include_router(triage_router, prefix="/api", tags=["Autonomous Triage"])
    app.include_router(newspaper_router, prefix="/api", tags=["Newspaper"])
    app.include_router(audio_router, prefix="/api", tags=["Audio"])
    app.include_router(translation_router, prefix="/api", tags=["Translation"])
    app.include_router(websocket_router, prefix="/ws", tags=["WebSocket"])

    # Quick sweep route alias
    from ai_security_monitor.presentation.api.routers.sources import trigger_fetch_sweep
    app.post("/api/fetch", tags=["Sources"])(trigger_fetch_sweep)

    # Serve static web UI
    import os
    web_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "web"))
    if os.path.exists(web_dir):
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app


# Create app instance for uvicorn
app = create_app()
