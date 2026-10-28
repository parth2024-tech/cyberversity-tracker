"""
Digest API router.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import Digest, Entry
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
            detail="Telegram bot_token and chat_id are required (provide in request or config).",
        )

    telegram_delivery = delivery_registry.create(
        "telegram", {"bot_token": bot_token, "chat_id": chat_id}
    )

    days = 1 if req.schedule == "daily" else 7
    period_start = datetime.now(UTC) - timedelta(days=days)
    period_end = datetime.now(UTC)

    async with SqlAlchemyUnitOfWork() as uow:
        recent_entries = await uow.entries.list()

    entries_with_analysis = [(e, e.analysis) for e in recent_entries]
    entries_by_cat: dict[str, list[Entry]] = {}
    for e in recent_entries:
        c = e.category.value
        if c not in entries_by_cat:
            entries_by_cat[c] = []
        entries_by_cat[c].append(e)

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
            "message": f"Telegram {req.schedule} threat digest dispatched successfully ({len(recent_entries)} entries analyzed)!",
        }
    else:
        raise HTTPException(
            status_code=500, detail=f"Failed to deliver Telegram digest: {result.error}"
        )


@digest_router.get("/markdown")
async def get_markdown_digest(
    days: int = Query(
        default=1, ge=1, le=14, description="Days of intelligence to include"
    ),
    min_velocity: int = Query(
        default=30, ge=0, le=100, description="Minimum velocity threshold"
    ),
    category: str | None = Query(default=None, description="Optional category filter"),
    download: bool = Query(
        default=False, description="Set attachment header for direct file download"
    ),
) -> Response:
    """Generate a clean, structured Markdown intelligence briefing of worldwide AI breakthroughs."""
    from ai_security_monitor.domain.entities import Category
    from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams

    cat_enum = None
    if category and category != "all":
        try:
            cat_enum = Category(category)
        except ValueError:
            pass

    since = datetime.now(UTC) - timedelta(days=days)
    async with SqlAlchemyUnitOfWork() as uow:
        filters = EntryFilters(
            category=cat_enum,
            since=since,
            sort_by="velocity",
        )
        pagination = PaginationParams(limit=100, offset=0)
        entries = await uow.entries.list(filters=filters, pagination=pagination)

    filtered_entries = []
    for e in entries:
        vel = getattr(e.analysis, "threat_velocity", 0) if e.analysis else 0
        if vel >= min_velocity:
            filtered_entries.append(e)

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    period_label = f"Past {days} Day{'s' if days > 1 else ''}"

    groups: dict[str, list[Entry]] = {
        "Frontier Foundation Models": [],
        "Trending Open-Source Repositories & Agents": [],
        "AI Research Papers & Preprints": [],
        "Inference Engines & Developer Infrastructure": [],
        "Global & Sovereign AI Ecosystems": [],
    }

    for e in filtered_entries:
        cat = e.category.value if hasattr(e.category, "value") else str(e.category)
        if cat == "ai_models":
            groups["Frontier Foundation Models"].append(e)
        elif cat == "github_trending":
            groups["Trending Open-Source Repositories & Agents"].append(e)
        elif cat == "ai_research":
            groups["AI Research Papers & Preprints"].append(e)
        elif cat == "cyber_tools":
            groups["Inference Engines & Developer Infrastructure"].append(e)
        else:
            groups["Global & Sovereign AI Ecosystems"].append(e)

    lines = [
        f"# AETHERGUARD: Worldwide AI Intelligence Briefing ({date_str})",
        f"*Coverage Window: {period_label} | Total Breakthroughs: {len(filtered_entries)} | Min Velocity: {min_velocity}*",
        "",
        "---",
        "",
    ]

    has_items = False
    for group_name, items in groups.items():
        if not items:
            continue
        has_items = True
        lines.append(f"## {group_name} ({len(items)})")
        lines.append("")
        for it in items[:15]:
            pub_date = (
                it.published_at.strftime("%b %d, %Y") if it.published_at else "Recent"
            )
            vel = getattr(it.analysis, "threat_velocity", 0) if it.analysis else 0
            lines.append(f"### [{it.title}]({it.url})")
            lines.append(f"**Velocity**: `{vel}/100` | **Published**: {pub_date}")
            if it.summary:
                clean_sum = it.summary.strip().replace("\n", " ")
                lines.append(f"> {clean_sum}")
            if it.analysis:
                focus = getattr(it.analysis, "attack_vector", None)
                cap = getattr(it.analysis, "risk_assessment", None)
                if focus:
                    lines.append(f"- **Tech Focus**: {focus}")
                if cap:
                    lines.append(f"- **Advancement**: {cap}")
            lines.append("")

    if not has_items:
        lines.append(
            "_No entries matched the velocity threshold for this time window._"
        )
        lines.append("")

    lines.append("---")
    lines.append(
        f"*Generated automatically by AETHERGUARD at {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}*"
    )

    md_text = "\n".join(lines)

    headers = {"Cache-Control": "public, max-age=60"}
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="aetherguard-briefing-{date_str}.md"'
        )

    return Response(
        content=md_text, media_type="text/markdown; charset=utf-8", headers=headers
    )
