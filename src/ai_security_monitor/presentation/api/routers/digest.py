"""
Digest API router.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_security_monitor.config.settings import settings
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.infrastructure.delivery.base import delivery_registry

digest_router = APIRouter(prefix="/digest")


class TelegramDigestRequest(BaseModel):
    schedule: str = "daily"
    bot_token: str | None = None
    chat_id: str | None = None


@digest_router.post("/telegram")
async def dispatch_telegram_digest(req: TelegramDigestRequest):
    """Dispatch compiled intelligence digest to Telegram."""
    bot_token = req.bot_token or settings.delivery.telegram_bot_token
    chat_id = req.chat_id or settings.delivery.telegram_chat_id

    if not bot_token or not chat_id:
        raise HTTPException(
            status_code=400,
            detail="Telegram bot_token and chat_id are required (provide in request or config)."
        )

    telegram_delivery = delivery_registry.create("telegram", {
        "bot_token": bot_token,
        "chat_id": chat_id
    })

    async with SqlAlchemyUnitOfWork() as uow:
        recent_entries = await uow.entries.list()

    entries_by_cat = {}
    for e in recent_entries[:15]:
        c = e.category.value
        if c not in entries_by_cat:
            entries_by_cat[c] = []
        entries_by_cat[c].append(e)

    success = await telegram_delivery.send(
        subject=f"AetherGuard Security Digest ({req.schedule})",
        content="Autonomous Intelligence Sweep Summary",
        entries_by_category=entries_by_cat
    )

    if success:
        return {"status": "success", "message": "Telegram digest dispatched successfully!"}
    else:
        raise HTTPException(status_code=500, detail="Failed to deliver Telegram digest. Check bot permissions.")
