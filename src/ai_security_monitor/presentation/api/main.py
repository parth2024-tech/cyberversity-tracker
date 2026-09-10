"""
FastAPI application factory with lifespan management.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
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
        from ai_security_monitor.application.services.monitor_service import (
            MonitorService,
        )
        monitor_service = MonitorService()
        await monitor_service.init_sources()
        logger.info("Sources configuration synchronized with database")

        # Ensure all 5 AI ecosystem pillars are primed if empty on startup
        async def _prime_critical_feeds():
            try:
                stats = await monitor_service.get_stats()
                by_cat = stats.get("by_category", {})
                ai_pillars = ("ai_research", "ai_models", "github_trending", "cyber_tools", "ai_tech")
                missing_pillars = [c for c in ai_pillars if by_cat.get(c, 0) == 0]
                if missing_pillars:
                    logger.info(f"Priming missing AI ecosystem categories on boot: {missing_pillars}...")
                    from ai_security_monitor.infrastructure.database.unit_of_work import (
                        SqlAlchemyUnitOfWork,
                    )
                    async with SqlAlchemyUnitOfWork() as uow:
                        all_srcs = await uow.sources.list(enabled_only=True)
                    targets = [s for s in all_srcs if s.category.value in missing_pillars]
                    sem = asyncio.Semaphore(3)

                    async def _fetch_target(s):
                        async with sem:
                            try:
                                await asyncio.wait_for(monitor_service.fetch_source(s), timeout=25.0)
                            except Exception as src_err:
                                logger.warning(f"Error priming source {s.name}: {src_err}")
                            finally:
                                await asyncio.sleep(0.05)

                    await asyncio.gather(*[_fetch_target(s) for s in targets], return_exceptions=True)
                    from ai_security_monitor.infrastructure.cache import response_cache
                    response_cache.invalidate("stats_totals")
                    response_cache.invalidate_prefix("entries_")
                    logger.info("Critical AI feeds successfully primed on boot")
            except Exception as prime_err:
                logger.warning(f"Error priming critical feeds: {prime_err}")

        asyncio.create_task(_prime_critical_feeds())
    except Exception as seed_err:
        logger.warning(f"Failed to auto-seed sources: {seed_err}")

    # Shared WebSocket broadcast callback for scheduler + triage worker
    from ai_security_monitor.presentation.api.websocket.manager import (
        manager as _ws_manager,
    )

    def _broadcast_to_ws(msg: dict) -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_ws_manager.broadcast(msg))
        except Exception:
            pass

    # Start background scheduler (if enabled)
    if settings.scheduler.enabled:
        from ai_security_monitor.application.services.scheduler_service import (
            SchedulerService,
        )

        monitor_service.set_broadcast_callback(_broadcast_to_ws)
        scheduler = SchedulerService(monitor_service=monitor_service)
        await scheduler.start()
        app.state.scheduler = scheduler
        logger.info("Background scheduler started with WebSocket live telemetry broadcast")

    # Start Autonomous LLM Triage Worker (if enabled)
    if settings.analyzer.autonomous_triage_enabled:
        from ai_security_monitor.application.services.autonomous_triage_service import (
            get_triage_service,
        )

        triage_service = get_triage_service()
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

    # GZip compression for fast cloud-hosted transfer
    app.add_middleware(GZipMiddleware, minimum_size=1000)

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

    # Serve static web UI & dedicated gazette page
    import os
    web_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "web"))
    if os.path.exists(web_dir):
        @app.get("/gazette", include_in_schema=False)
        @app.get("/gazette/", include_in_schema=False)
        async def serve_gazette():
            gazette_path = os.path.join(web_dir, "gazette.html")
            if os.path.exists(gazette_path):
                return FileResponse(gazette_path, media_type="text/html")
            return FileResponse(os.path.join(web_dir, "index.html"), media_type="text/html")

        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app


# Create app instance for uvicorn
app = create_app()
