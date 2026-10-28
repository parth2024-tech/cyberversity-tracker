"""
Outbound Syndication Feeds router.
Provides RSS 2.0 (XML) and JSON Feed 1.1 endpoints for subscribing to
AETHERGUARD's worldwide AI ecosystem intelligence in external RSS readers,
news aggregators, and team automation bots.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from xml.sax.saxutils import escape

from fastapi import APIRouter, Query, Response

from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import Category
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.cache import response_cache
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

feed_router = APIRouter(prefix="/feed")

AI_ECOSYSTEM_CATEGORIES = [
    Category.AI_RESEARCH,
    Category.AI_MODELS,
    Category.GITHUB_TRENDING,
    Category.CYBER_TOOLS,
    Category.AI_TECH,
]


def _format_rfc822(dt: datetime | None) -> str:
    """Format datetime as RFC-822 string for RSS 2.0 pubDate."""
    if not dt:
        dt = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


@feed_router.get(".xml")
@feed_router.get("/rss")
@feed_router.get("")
@feed_router.get("/")
async def get_rss_feed(
    category: str | None = Query(default=None, description="Optional category filter"),
    limit: int = Query(default=50, ge=1, le=100, description="Max entries to return"),
    min_velocity: int = Query(
        default=0, ge=0, le=100, description="Minimum velocity threshold"
    ),
) -> Response:
    """Generate RSS 2.0 syndicated feed of global AI ecosystem intelligence."""
    cache_key = f"feed_rss_{category}_{limit}_{min_velocity}"

    async def _generate_xml() -> str:
        cat_enum = None
        if category and category != "all":
            try:
                cat_enum = Category(category)
            except ValueError:
                pass

        async with SqlAlchemyUnitOfWork() as uow:
            filters = EntryFilters(
                category=cat_enum,
                categories=None if cat_enum else AI_ECOSYSTEM_CATEGORIES,
                since=datetime.now(UTC)
                - timedelta(days=settings.database.max_ingest_age_days),
                sort_by="newest",
            )
            pagination = PaginationParams(limit=limit, offset=0)
            entries = await uow.entries.list(filters=filters, pagination=pagination)

        # Filter by minimum velocity if requested
        if min_velocity > 0:
            filtered = []
            for e in entries:
                vel = 0
                if e.analysis:
                    vel = getattr(e.analysis, "threat_velocity", 0) or 0
                if vel >= min_velocity:
                    filtered.append(e)
            entries = filtered

        now_rfc822 = _format_rfc822(datetime.now(UTC))

        items_xml: list[str] = []
        for e in entries:
            pub_date = _format_rfc822(e.published_at)
            item_url = escape(e.url)
            item_title = escape(e.title)

            # Enrich summary with tech focus and analysis details
            summary_parts = []
            if e.summary:
                summary_parts.append(e.summary)
            if e.analysis:
                tech_focus = getattr(e.analysis, "attack_vector", None)
                cap_summary = getattr(e.analysis, "risk_assessment", None)
                if tech_focus:
                    summary_parts.append(f"Focus: {tech_focus}")
                if cap_summary:
                    summary_parts.append(f"Breakthrough: {cap_summary}")

            full_desc = escape("\n\n".join(summary_parts) if summary_parts else e.title)
            cat_val = escape(
                e.category.value if hasattr(e.category, "value") else str(e.category)
            )

            items_xml.append(f"""    <item>
      <title>{item_title}</title>
      <link>{item_url}</link>
      <guid isPermaLink="false">{e.id}</guid>
      <pubDate>{pub_date}</pubDate>
      <category>{cat_val}</category>
      <description>{full_desc}</description>
    </item>""")

        items_joined = "\n".join(items_xml)
        xml_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>AETHERGUARD Worldwide AI Ecosystem</title>
    <link>https://github.com/parth2024-tech/cyberversity-tracker</link>
    <description>Continuous telemetry, trending models, and research breakthroughs across the global AI ecosystem.</description>
    <language>en-us</language>
    <lastBuildDate>{now_rfc822}</lastBuildDate>
    <generator>AETHERGUARD Syndication Engine</generator>
{items_joined}
  </channel>
</rss>"""
        return xml_body

    xml_content = await response_cache.get_or_set(cache_key, 60.0, _generate_xml)
    return Response(
        content=xml_content,
        media_type="application/rss+xml; charset=utf-8",
        headers={"Cache-Control": "public, max-age=60"},
    )


@feed_router.get(".json")
@feed_router.get("/json")
async def get_json_feed(
    category: str | None = Query(default=None, description="Optional category filter"),
    limit: int = Query(default=50, ge=1, le=100, description="Max entries to return"),
) -> Response:
    """Generate JSON Feed 1.1 of global AI ecosystem intelligence."""
    cache_key = f"feed_json_{category}_{limit}"

    async def _generate_json() -> str:
        cat_enum = None
        if category and category != "all":
            try:
                cat_enum = Category(category)
            except ValueError:
                pass

        async with SqlAlchemyUnitOfWork() as uow:
            filters = EntryFilters(
                category=cat_enum,
                categories=None if cat_enum else AI_ECOSYSTEM_CATEGORIES,
                since=datetime.now(UTC)
                - timedelta(days=settings.database.max_ingest_age_days),
                sort_by="newest",
            )
            pagination = PaginationParams(limit=limit, offset=0)
            entries = await uow.entries.list(filters=filters, pagination=pagination)

        items = []
        for e in entries:
            pub_iso = (
                e.published_at.isoformat()
                if e.published_at
                else datetime.now(UTC).isoformat()
            )
            items.append(
                {
                    "id": str(e.id),
                    "url": e.url,
                    "title": e.title,
                    "content_text": e.summary or e.title,
                    "date_published": pub_iso,
                    "tags": e.tags,
                    "category": e.category.value
                    if hasattr(e.category, "value")
                    else str(e.category),
                }
            )

        feed_data = {
            "version": "https://jsonfeed.org/version/1.1",
            "title": "AETHERGUARD Worldwide AI Ecosystem",
            "home_page_url": "https://github.com/parth2024-tech/cyberversity-tracker",
            "feed_url": "https://github.com/parth2024-tech/cyberversity-tracker/feed.json",
            "description": "Continuous telemetry, trending models, and research breakthroughs across the global AI ecosystem.",
            "items": items,
        }
        return json.dumps(feed_data, ensure_ascii=False)

    json_content = await response_cache.get_or_set(cache_key, 60.0, _generate_json)
    return Response(
        content=json_content,
        media_type="application/feed+json; charset=utf-8",
        headers={"Cache-Control": "public, max-age=60"},
    )
