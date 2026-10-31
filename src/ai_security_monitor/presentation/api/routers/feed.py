"""
Outbound Syndication Feeds and Intelligence Export router (Feature 14).
Provides:
- RSS 2.0 (XML) endpoints (/feed.xml, /rss.xml, /feed/rss)
- JSON Feed 1.1 endpoints (/feed.json, /feed/json)
- RFC 4180 CSV export endpoints (/api/export.csv, /export.csv, /feed.csv)

Supports comprehensive filtering: category, search/q, lab, region, subject_region, tier,
and ISO-8601 date bounds (from/to), with strict <= 14-day freshness enforcement.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from xml.sax.saxutils import escape

from fastapi import APIRouter, Query, Response

from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.cache import response_cache
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

feed_router = APIRouter(prefix="/feed")
export_router = APIRouter(tags=["Syndication & Export"])

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


async def _resolve_export_entries(
    category: str | None = None,
    search: str | None = None,
    q: str | None = None,
    lab: str | None = None,
    region: str | None = None,
    subject_region: str | None = None,
    tier: float | int | None = None,
    from_: str | None = None,
    to: str | None = None,
    limit: int = 50,
    min_velocity: int = 0,
) -> tuple[list[Entry], dict[str, Any]]:
    """Retrieve entries and source metadata matching query filters with strict freshness guard."""
    effective_search = (search or q or "").strip() or None

    cat_enum = None
    if category and category != "all":
        try:
            cat_enum = Category(category)
        except ValueError:
            pass

    # Strictly enforce 14-day freshness window (never dump stale archives > 14 days old)
    max_age_cutoff = datetime.now(UTC) - timedelta(
        days=settings.database.max_ingest_age_days
    )
    since = max_age_cutoff
    if from_:
        try:
            parsed_from = datetime.fromisoformat(from_)
            if parsed_from.tzinfo is None:
                parsed_from = parsed_from.replace(tzinfo=UTC)
            since = max(parsed_from, max_age_cutoff)
        except ValueError:
            pass

    until = None
    if to:
        try:
            parsed_to = datetime.fromisoformat(to)
            if parsed_to.tzinfo is None:
                parsed_to = parsed_to.replace(tzinfo=UTC)
            until = parsed_to
        except ValueError:
            pass

    filters = EntryFilters(
        category=cat_enum,
        categories=None if cat_enum else AI_ECOSYSTEM_CATEGORIES,
        search=effective_search,
        since=since,
        until=until,
        region=region if region and region != "all" else None,
        subject_region=subject_region
        if subject_region and subject_region != "all"
        else None,
        lab=lab if lab and lab != "all" else None,
        tier=float(tier) if tier is not None else None,
        sort_by="newest",
    )
    pagination = PaginationParams(limit=limit, offset=0)

    async with SqlAlchemyUnitOfWork() as uow:
        entries = await uow.entries.list(filters=filters, pagination=pagination)
        sources = await uow.sources.list()
        sources_map = {str(s.id): s for s in sources}

    if min_velocity > 0:
        filtered = []
        for e in entries:
            vel = 0
            if e.analysis:
                vel = getattr(e.analysis, "threat_velocity", 0) or 0
            if vel >= min_velocity:
                filtered.append(e)
        entries = filtered

    return entries, sources_map


@feed_router.get(".xml")
@feed_router.get("/rss")
@feed_router.get("/xml")
@feed_router.get("")
@feed_router.get("/")
@export_router.get("/feed.xml")
@export_router.get("/rss.xml")
async def get_rss_feed(
    category: str | None = Query(default=None, description="Optional category filter"),
    search: str | None = Query(default=None, description="Full-text search query"),
    q: str | None = Query(default=None, description="Search query alias"),
    lab: str | None = Query(default=None, description="Filter by AI lab or author"),
    region: str | None = Query(default=None, description="Filter by source region"),
    subject_region: str | None = Query(
        default=None, description="Filter by subject region"
    ),
    tier: float | None = Query(default=None, description="Filter by source tier"),
    from_: str | None = Query(
        default=None, alias="from", description="ISO-8601 start date"
    ),
    to: str | None = Query(default=None, description="ISO-8601 end date"),
    limit: int = Query(default=50, ge=1, le=200, description="Max entries to return"),
    min_velocity: int = Query(
        default=0, ge=0, le=100, description="Minimum velocity threshold"
    ),
) -> Response:
    """Generate RSS 2.0 syndicated feed of global AI ecosystem intelligence."""
    effective_q = search or q
    cache_key = f"feed_rss_{category}_{effective_q}_{lab}_{region}_{subject_region}_{tier}_{from_}_{to}_{limit}_{min_velocity}"

    async def _generate_xml() -> str:
        entries, sources_map = await _resolve_export_entries(
            category=category,
            search=search,
            q=q,
            lab=lab,
            region=region,
            subject_region=subject_region,
            tier=tier,
            from_=from_,
            to=to,
            limit=limit,
            min_velocity=min_velocity,
        )

        now_rfc822 = _format_rfc822(datetime.now(UTC))

        items_xml: list[str] = []
        for e in entries:
            pub_date = _format_rfc822(e.published_at)
            item_url = escape(str(e.url or ""))
            item_title = escape(str(e.title or "Untitled"))

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

            full_desc = escape(
                "\n\n".join(summary_parts) if summary_parts else str(e.title or "")
            )
            cat_val = escape(
                str(
                    e.category.value
                    if hasattr(e.category, "value")
                    else (e.category or "")
                )
            )

            meta = e.metadata or {}
            src = sources_map.get(str(e.source_id))
            author_val = (
                meta.get("lab") or meta.get("author") or (src.name if src else None)
            )
            author_tag = (
                f"      <author>{escape(str(author_val))}</author>\n"
                if author_val
                else ""
            )

            items_xml.append(f"""    <item>
      <title>{item_title}</title>
      <link>{item_url}</link>
      <guid isPermaLink="false">{e.id}</guid>
      <pubDate>{pub_date}</pubDate>
      <category>{cat_val}</category>
{author_tag}      <description>{full_desc}</description>
    </item>""")

        items_joined = "\n".join(items_xml)
        xml_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>AETHERGUARD Worldwide AI Ecosystem</title>
    <link>https://github.com/parth2024-tech/cyberversity-tracker</link>
    <atom:link href="https://github.com/parth2024-tech/cyberversity-tracker/feed.xml" rel="self" type="application/rss+xml" />
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
@export_router.get("/feed.json")
async def get_json_feed(
    category: str | None = Query(default=None, description="Optional category filter"),
    search: str | None = Query(default=None, description="Full-text search query"),
    q: str | None = Query(default=None, description="Search query alias"),
    lab: str | None = Query(default=None, description="Filter by AI lab or author"),
    region: str | None = Query(default=None, description="Filter by source region"),
    subject_region: str | None = Query(
        default=None, description="Filter by subject region"
    ),
    tier: float | None = Query(default=None, description="Filter by source tier"),
    from_: str | None = Query(
        default=None, alias="from", description="ISO-8601 start date"
    ),
    to: str | None = Query(default=None, description="ISO-8601 end date"),
    limit: int = Query(default=50, ge=1, le=200, description="Max entries to return"),
) -> Response:
    """Generate JSON Feed 1.1 of global AI ecosystem intelligence."""
    effective_q = search or q
    cache_key = f"feed_json_{category}_{effective_q}_{lab}_{region}_{subject_region}_{tier}_{from_}_{to}_{limit}"

    async def _generate_json() -> str:
        entries, sources_map = await _resolve_export_entries(
            category=category,
            search=search,
            q=q,
            lab=lab,
            region=region,
            subject_region=subject_region,
            tier=tier,
            from_=from_,
            to=to,
            limit=limit,
        )

        items = []
        for e in entries:
            pub_iso = (
                e.published_at.isoformat()
                if e.published_at
                else datetime.now(UTC).isoformat()
            )
            meta = e.metadata or {}
            src = sources_map.get(str(e.source_id))
            src_name = src.name if src else "Verified Intel"

            author_name = meta.get("lab") or meta.get("author") or src_name
            authors_list = [{"name": author_name}] if author_name else []

            item_dict: dict[str, Any] = {
                "id": str(e.id),
                "url": e.url,
                "title": e.title,
                "content_text": e.summary or e.title,
                "date_published": pub_iso,
                "tags": e.tags,
                "category": e.category.value
                if hasattr(e.category, "value")
                else str(e.category),
                "authors": authors_list,
                "_aetherguard": {
                    "source_name": src_name,
                    "region": meta.get("subject_region")
                    or meta.get("region")
                    or (src.config.get("region") if src and src.config else "global"),
                    "lab": meta.get("lab"),
                    "heat_score": meta.get("heat_score", 0.0),
                    "first_reported_by": meta.get("first_reported_by"),
                },
            }
            items.append(item_dict)

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


@feed_router.get(".csv")
@feed_router.get("/csv")
@export_router.get("/export.csv")
@export_router.get("/api/export.csv")
@export_router.get("/api/v1/export.csv")
@export_router.get("/api/entries/export.csv")
@export_router.get("/entries/export.csv")
@export_router.get("/feed.csv")
async def get_csv_export(
    category: str | None = Query(default=None, description="Optional category filter"),
    search: str | None = Query(default=None, description="Full-text search query"),
    q: str | None = Query(default=None, description="Search query alias"),
    lab: str | None = Query(default=None, description="Filter by AI lab or author"),
    region: str | None = Query(default=None, description="Filter by source region"),
    subject_region: str | None = Query(
        default=None, description="Filter by subject region"
    ),
    tier: float | None = Query(default=None, description="Filter by source tier"),
    from_: str | None = Query(
        default=None, alias="from", description="ISO-8601 start date"
    ),
    to: str | None = Query(default=None, description="ISO-8601 end date"),
    limit: int = Query(default=500, ge=1, le=2000, description="Max entries to return"),
) -> Response:
    """Generate RFC 4180 compliant CSV export of global AI ecosystem intelligence."""
    effective_q = search or q
    cache_key = f"export_csv_{category}_{effective_q}_{lab}_{region}_{subject_region}_{tier}_{from_}_{to}_{limit}"

    async def _generate_csv_string() -> str:
        entries, sources_map = await _resolve_export_entries(
            category=category,
            search=search,
            q=q,
            lab=lab,
            region=region,
            subject_region=subject_region,
            tier=tier,
            from_=from_,
            to=to,
            limit=limit,
        )

        output = io.StringIO()
        writer = csv.writer(output, dialect="excel")
        writer.writerow(
            [
                "id",
                "title",
                "url",
                "category",
                "published_at",
                "source_name",
                "region",
                "lab",
                "tier",
                "heat_score",
                "first_reported_by",
                "summary",
                "tags",
            ]
        )

        for e in entries:
            meta = e.metadata or {}
            src = sources_map.get(str(e.source_id))
            src_name = src.name if src else "Verified Intel"
            reg = (
                meta.get("subject_region")
                or meta.get("region")
                or (src.config.get("region") if src and src.config else "global")
            )
            lab_val = meta.get("lab") or meta.get("author") or ""
            tier_val = meta.get("tier") or (
                src.config.get("tier") if src and src.config else ""
            )
            heat_val = meta.get("heat_score", 0.0)
            first_rep = meta.get("first_reported_by") or (
                src_name if meta.get("is_primary") else ""
            )
            tags_str = ", ".join(e.tags) if e.tags else ""
            pub_str = e.published_at.isoformat() if e.published_at else ""
            cat_val = (
                e.category.value
                if hasattr(e.category, "value")
                else str(e.category or "")
            )

            # Clean newlines from title/summary for tidy CSV readability while preserving full text
            clean_title = re.sub(r"\s+", " ", e.title or "").strip()
            clean_summary = re.sub(r"\s+", " ", e.summary or "").strip()

            writer.writerow(
                [
                    str(e.id),
                    clean_title,
                    e.url or "",
                    cat_val,
                    pub_str,
                    src_name,
                    reg,
                    lab_val,
                    tier_val,
                    heat_val,
                    first_rep,
                    clean_summary,
                    tags_str,
                ]
            )

        return output.getvalue()

    csv_data = await response_cache.get_or_set(cache_key, 60.0, _generate_csv_string)
    filename = f"aetherguard_export_{datetime.now(UTC).strftime('%Y%m%d')}.csv"
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "public, max-age=60",
        },
    )
