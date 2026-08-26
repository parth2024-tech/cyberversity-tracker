"""
Digest API router.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import yaml
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import Digest
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.infrastructure.delivery.base import delivery_registry

digest_router = APIRouter(prefix="/digest")


class TelegramDigestRequest(BaseModel):
    schedule: str = "daily"
    bot_token: str | None = None
    chat_id: str | None = None


def _get_telegram_credentials(req: TelegramDigestRequest) -> tuple[str, str]:
    """Retrieve Telegram credentials from request, settings, or sources.yaml."""
    bot_token = req.bot_token or settings.delivery.telegram_bot_token
    chat_id = req.chat_id or settings.delivery.telegram_chat_id

    if not bot_token or not chat_id:
        yaml_path = Path("config/sources.yaml")
        if yaml_path.exists():
            try:
                data = yaml.safe_load(yaml_path.read_text()) or {}
                tg = data.get("delivery", {}).get("telegram", {})
                bot_token = bot_token or tg.get("bot_token")
                chat_id = chat_id or str(tg.get("chat_id", ""))
            except Exception:
                pass

    return bot_token or "", chat_id or ""


@digest_router.post("")
@digest_router.post("/")
@digest_router.post("/telegram")
async def dispatch_telegram_digest(req: TelegramDigestRequest):
    """Dispatch compiled intelligence digest to Telegram."""
    bot_token, chat_id = _get_telegram_credentials(req)

    if not bot_token or not chat_id:
        raise HTTPException(
            status_code=400,
            detail="Telegram bot_token and chat_id are required (provide in request or config)."
        )

    telegram_delivery = delivery_registry.create("telegram", {
        "bot_token": bot_token,
        "chat_id": chat_id
    })

    days = 1 if req.schedule == "daily" else 7
    period_start = datetime.utcnow() - timedelta(days=days)
    period_end = datetime.utcnow()

    async with SqlAlchemyUnitOfWork() as uow:
        recent_entries = await uow.entries.list()

    entries_with_analysis = [(e, e.analysis) for e in recent_entries]
    entries_by_cat = {}
    for e in recent_entries:
        c = e.category.value
        if c not in entries_by_cat:
            entries_by_cat[c] = []
        entries_by_cat[c].append(str(e.id))

    digest = Digest(
        schedule=req.schedule,
        entries_by_category=entries_by_cat,
        total_entries=len(recent_entries),
        period_start=period_start,
        period_end=period_end,
        delivery_channels=["telegram"],
    )

    result = await telegram_delivery.send_digest(digest, entries_with_analysis)

    if result.success:
        return {
            "status": "success",
            "message": f"Telegram {req.schedule} threat digest dispatched successfully ({len(recent_entries)} entries analyzed)!"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to deliver Telegram digest: {result.error}"
        )

