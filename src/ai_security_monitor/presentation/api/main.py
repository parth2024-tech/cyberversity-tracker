"""
FastAPI application factory with lifespan management.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.health import router as health_router
from ai_security_monitor.core.logging import get_logger, setup_logging
from ai_security_monitor.core.metrics import metrics_middleware
from ai_security_monitor.infrastructure.database.connection import db_manager
from ai_security_monitor.presentation.api.limiter import limiter
from ai_security_monitor.presentation.api.routers import (
    analysis_router,
    audio_router,
    backup_router,
    china_router,
    clusters_router,
    council_router,
    digest_router,
    entities_router,
    entries_router,
    events_router,
    feed_router,
    newspaper_router,
    parity_router,
    sources_router,
    stats_router,
    telegram_router,
    translation_router,
    triage_router,
    vault_router,
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

        # Cache warming on startup to prevent cold-start latency
        try:
            from ai_security_monitor.application.services.vault_feedback_service import (
                vault_feedback_service,
            )
            from ai_security_monitor.infrastructure.cache import response_cache

            logger.info("Warming hot response caches on startup...")
            await response_cache.get_or_set(
                "stats_totals", 30.0, lambda: monitor_service.get_stats()
            )
            await response_cache.get_or_set(
                "sweep_status", 15.0, lambda: monitor_service.get_sweep_status()
            )
            await vault_feedback_service.refresh_profile()
            logger.info(
                "Hot response caches successfully warmed (stats_totals, sweep_status, vault_profile)"
            )
        except Exception as warm_err:
            logger.warning(f"Cache warming notice (non-fatal): {warm_err}")
    except Exception as seed_err:
        logger.warning(f"Failed to auto-seed sources: {seed_err}")

    # Shared WebSocket broadcast callback for scheduler + triage worker
    from ai_security_monitor.presentation.api.websocket.manager import (
        manager as _ws_manager,
    )

    def _broadcast_to_ws(msg: dict) -> None:
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                asyncio.create_task(_ws_manager.broadcast(msg))
        except RuntimeError:
            pass
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
        logger.info(
            "Background scheduler started with WebSocket live telemetry broadcast"
        )

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

    # Start Telegram ChatOps long-polling worker (if enabled and mode is 'poll')
    if settings.delivery.telegram_enabled and settings.delivery.telegram_mode == "poll":
        from ai_security_monitor.application.services.telegram_chatops_service import (
            telegram_chatops_service,
        )

        await telegram_chatops_service.start_polling()
        app.state.telegram_chatops = telegram_chatops_service
        logger.info("Telegram ChatOps long-polling worker started in background")

    yield

    # Shutdown
    logger.info("Shutting down AI Security Monitor API")

    # Stop Telegram ChatOps polling worker
    if hasattr(app.state, "telegram_chatops"):
        await app.state.telegram_chatops.stop_polling()
        logger.info("Telegram ChatOps polling worker stopped")

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

    # Attach rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

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

    # HTTP Security Headers Middleware (Clickjacking, MIME sniffing, and Referrer leakage prevention)
    @app.middleware("http")
    async def security_headers_middleware(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=()"
        )
        response.headers["X-XSS-Protection"] = "1; mode=block"
        if request.url.scheme == "https" and request.url.hostname not in (
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "test",
        ):
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: https: http:; "
            "media-src 'self' data: blob: https:; "
            "connect-src 'self' ws: wss: http: https:; "
            "frame-ancestors 'self'; "
            "frame-src 'self';"
        )
        return response

    # Include routers under /api and /api/v1 for clean versioning
    for api_prefix in ("/api", "/api/v1"):
        app.include_router(health_router, prefix=api_prefix, tags=["Health"])
        app.include_router(stats_router, prefix=api_prefix, tags=["Statistics"])
        app.include_router(entries_router, prefix=api_prefix, tags=["Entries"])
        app.include_router(sources_router, prefix=api_prefix, tags=["Sources"])
        app.include_router(vault_router, prefix=api_prefix, tags=["Vault"])
        app.include_router(analysis_router, prefix=api_prefix, tags=["Analysis"])
        app.include_router(digest_router, prefix=api_prefix, tags=["Digest"])
        app.include_router(watchlist_router, prefix=api_prefix, tags=["Watchlist"])
        app.include_router(triage_router, prefix=api_prefix, tags=["Autonomous Triage"])
        app.include_router(newspaper_router, prefix=api_prefix, tags=["Newspaper"])
        app.include_router(audio_router, prefix=api_prefix, tags=["Audio"])
        app.include_router(translation_router, prefix=api_prefix, tags=["Translation"])
        app.include_router(
            backup_router, prefix=api_prefix, tags=["Backup & Portability"]
        )
        app.include_router(china_router, prefix=api_prefix, tags=["China Corridor"])
        app.include_router(feed_router, prefix=api_prefix, tags=["Syndication Feeds"])
        app.include_router(
            telegram_router, prefix=api_prefix, tags=["Telegram ChatOps"]
        )
        app.include_router(entities_router, prefix=api_prefix, tags=["Knowledge Graph"])
        app.include_router(
            council_router, prefix=api_prefix, tags=["Multi-Agent Council"]
        )
        app.include_router(
            clusters_router, prefix=api_prefix, tags=["Semantic Clusters"]
        )
        app.include_router(
            parity_router, prefix=api_prefix, tags=["Language Parity SLO"]
        )
        app.include_router(
            events_router, prefix=api_prefix, tags=["Cross-Lingual Events"]
        )

    # Top-level syndication feed route for standard RSS reader auto-discovery
    app.include_router(feed_router, tags=["Syndication Feeds"])
    # Top-level Telegram webhook route
    app.include_router(telegram_router, tags=["Telegram ChatOps"])

    app.include_router(websocket_router, prefix="/ws", tags=["WebSocket"])

    # Quick sweep route alias
    from ai_security_monitor.presentation.api.routers.sources import trigger_fetch_sweep

    app.post("/api/fetch", tags=["Sources"])(trigger_fetch_sweep)
    app.post("/api/v1/fetch", tags=["Sources"])(trigger_fetch_sweep)

    # Serve static web UI & dedicated gazette page
    import os

    web_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "web")
    )
    if os.path.exists(web_dir):

        @app.get("/gazette", include_in_schema=False)
        @app.get("/gazette/", include_in_schema=False)
        async def serve_gazette():
            gazette_path = os.path.join(web_dir, "gazette.html")
            if os.path.exists(gazette_path):
                return FileResponse(gazette_path, media_type="text/html")
            return FileResponse(
                os.path.join(web_dir, "index.html"), media_type="text/html"
            )

        @app.get("/clusters", include_in_schema=False)
        @app.get("/clusters/", include_in_schema=False)
        async def serve_clusters():
            clusters_path = os.path.join(web_dir, "clusters.html")
            if os.path.exists(clusters_path):
                return FileResponse(clusters_path, media_type="text/html")
            return FileResponse(
                os.path.join(web_dir, "index.html"), media_type="text/html"
            )

        @app.get("/privacy", include_in_schema=False)
        @app.get("/privacy/", include_in_schema=False)
        async def serve_privacy():
            privacy_path = os.path.join(web_dir, "privacy.html")
            if os.path.exists(privacy_path):
                return FileResponse(privacy_path, media_type="text/html")
            return FileResponse(
                os.path.join(web_dir, "index.html"), media_type="text/html"
            )

        @app.get("/terms", include_in_schema=False)
        @app.get("/terms/", include_in_schema=False)
        async def serve_terms():
            terms_path = os.path.join(web_dir, "terms.html")
            if os.path.exists(terms_path):
                return FileResponse(terms_path, media_type="text/html")
            return FileResponse(
                os.path.join(web_dir, "index.html"), media_type="text/html"
            )

        @app.get("/favicon.ico", include_in_schema=False)
        async def serve_favicon():
            fav_path = os.path.join(web_dir, "favicon.ico")
            if os.path.exists(fav_path):
                return FileResponse(fav_path, media_type="image/x-icon")
            return Response(status_code=404)

        @app.get("/icon.svg", include_in_schema=False)
        async def serve_icon_svg():
            svg_path = os.path.join(web_dir, "icon.svg")
            if os.path.exists(svg_path):
                return FileResponse(svg_path, media_type="image/svg+xml")
            return Response(status_code=404)

        @app.get("/apple-touch-icon.png", include_in_schema=False)
        async def serve_apple_touch_icon():
            png_path = os.path.join(web_dir, "apple-touch-icon.png")
            if os.path.exists(png_path):
                return FileResponse(png_path, media_type="image/png")
            return Response(status_code=404)

        @app.get("/manifest.json", include_in_schema=False)
        async def serve_manifest():
            manifest_path = os.path.join(web_dir, "manifest.json")
            if os.path.exists(manifest_path):
                return FileResponse(
                    manifest_path, media_type="application/manifest+json"
                )
            return Response(status_code=404)

        @app.get("/sw.js", include_in_schema=False)
        async def serve_service_worker():
            sw_path = os.path.join(web_dir, "sw.js")
            if os.path.exists(sw_path):
                return FileResponse(
                    sw_path,
                    media_type="application/javascript",
                    headers={"Service-Worker-Allowed": "/"},
                )
            return Response(status_code=404)

        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app


# Create app instance for uvicorn
app = create_app()
