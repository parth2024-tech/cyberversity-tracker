"""
Telegram ChatOps API router.
Provides webhook receiver and transport telemetry for two-way Telegram inline callbacks.
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from ai_security_monitor.application.services.telegram_chatops_service import (
    telegram_chatops_service,
)
from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)

telegram_router = APIRouter(prefix="/telegram")


@telegram_router.post("/webhook")
async def telegram_webhook_endpoint(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
) -> dict[str, Any]:
    """Receive and process incoming Telegram webhook updates.
    Verifies X-Telegram-Bot-Api-Secret-Token header when secret is configured.
    """
    configured_secret = settings.delivery.telegram_webhook_secret
    if configured_secret:
        if not x_telegram_bot_api_secret_token or not hmac.compare_digest(
            x_telegram_bot_api_secret_token, configured_secret
        ):
            logger.warning("Rejected Telegram webhook: Invalid secret token")
            raise HTTPException(
                status_code=403, detail="Invalid Telegram webhook secret token"
            )

    try:
        update_data = await request.json()
    except Exception as e:
        logger.warning(f"Malformed Telegram webhook JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    result = await telegram_chatops_service.handle_update(update_data)
    return {"ok": True, "result": result}


@telegram_router.get("/status")
async def telegram_chatops_status() -> dict[str, Any]:
    """Get current Telegram ChatOps transport mode and configuration status."""
    return {
        "enabled": settings.delivery.telegram_enabled,
        "mode": settings.delivery.telegram_mode,
        "polling_active": telegram_chatops_service._polling_active,
        "last_update_id": telegram_chatops_service._last_update_id,
        "allowed_user_id_configured": bool(settings.delivery.telegram_allowed_user_id),
        "webhook_secret_configured": bool(settings.delivery.telegram_webhook_secret),
    }
