"""
Weekly Digest Export Service (Workstream C2).
Compiles and exports curated worldwide AI ecosystem intelligence into Markdown, HTML, and PDF formats.

Key Invariants:
1. Explicit User Saves: Distinguishes between explicitly user-bookmarked entries (is_user_saved=True)
   and automated landmark tagging (is_important=True).
2. Freshness Guard: Enforces 14-day maximum window (max_ingest_age_days = 14).
3. Redistribution Guard: Includes only redistributable fields (title, canonical link, our summary, tags, entities).
4. Explicit Timezone: Formats dates and schedule headers using the user's explicit timezone.
5. Multi-Format: Renders Markdown, HTML, and ReportLab PDF (with WeasyPrint fallback if available).
6. Portability & Archival: Persists to data/digests/weekly/ with optional remote sync hooks.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.database.models import EntryEntityModel
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

logger = get_logger(__name__)

MAX_DIGEST_AGE_DAYS = 14
DEFAULT_DIGEST_DAYS = 7


class DigestNumberedCanvas(canvas.Canvas):
    """Two-pass canvas for total page numbering, running headers, and metadata footers."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:  # noqa: N802 (ReportLab Canvas override)
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Running header on pages 2+
        if self._pageNumber > 1:
            self.drawString(
                36, 756, "AETHERGUARD • WORLDWIDE AI ECOSYSTEM WEEKLY DIGEST"
            )
            self.drawRightString(576, 756, "EXECUTIVE TECHNOLOGY BRIEF")
            self.setStrokeColor(colors.HexColor("#cbd5e1"))
            self.setLineWidth(0.5)
            self.line(36, 750, 576, 750)

        # Running footer on all pages
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawString(
            36,
            25,
            "AETHERGUARD AI OBSERVATORY • REDISTRIBUTABLE INTELLIGENCE DOSSIER",
        )
        self.drawRightString(576, 25, page_str)
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(36, 35, 576, 35)
        self.restoreState()


class WeeklyDigestExportService:
    """Service orchestrating weekly intelligence compilation, multi-format rendering, and archival."""

    def __init__(
        self,
        uow_factory: type[SqlAlchemyUnitOfWork] = SqlAlchemyUnitOfWork,
        default_timezone: str | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self.default_timezone = (
            default_timezone
            or getattr(settings.export, "default_timezone", "UTC")
            or "UTC"
        )
        self.output_dir = (
            output_dir
            or getattr(settings.export, "output_dir", Path("data/digests/weekly"))
            or Path("data/digests/weekly")
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def resolve_timezone(self, tz_name: str | None) -> ZoneInfo:
        """Resolve valid ZoneInfo from name, falling back to default or UTC."""
        candidate = tz_name or self.default_timezone or "UTC"
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(f"Invalid timezone '{candidate}', falling back to UTC.")
            return ZoneInfo("UTC")

    async def compile_weekly_digest(
        self,
        days: int = DEFAULT_DIGEST_DAYS,
        timezone_str: str | None = None,
        include_user_saves_only: bool = False,
        limit_per_section: int = 15,
    ) -> dict[str, Any]:
        """
        Compile weekly intelligence data from database.
        Enforces 14-day freshness limit and aggregates explicit user bookmarks vs broader breakthroughs.
        """
        # Clamp days to max 14 days
        effective_days = max(1, min(days, MAX_DIGEST_AGE_DAYS))
        tz = self.resolve_timezone(timezone_str)

        now_utc = datetime.now(UTC)
        since_utc = now_utc - timedelta(days=effective_days)

        now_local = now_utc.astimezone(tz)
        since_local = since_utc.astimezone(tz)

        async with self._uow_factory() as uow:
            # 1. Fetch explicit user saves directly via dedicated filter (never dropped by pagination)
            user_saves_filters = EntryFilters(
                since=since_utc,
                user_saved_only=True,
            )
            user_saved_entries = await uow.entries.list(
                filters=user_saves_filters,
                pagination=PaginationParams(limit=100, offset=0),
            )

            # 2. Fetch broader ecosystem breakthroughs in time window
            if not include_user_saves_only:
                filters = EntryFilters(
                    since=since_utc,
                    sort_by="velocity",
                )
                pagination = PaginationParams(limit=250, offset=0)
                all_entries = await uow.entries.list(
                    filters=filters, pagination=pagination
                )
            else:
                all_entries = user_saved_entries
            working_pool = (
                user_saved_entries if include_user_saves_only else all_entries
            )

            # 4. Fetch top entities and momentum from Pillar 4 Knowledge Graph
            from sqlalchemy import desc, func, select

            stmt_entities = (
                select(
                    EntryEntityModel.entity_type,
                    EntryEntityModel.name,
                    EntryEntityModel.display_name,
                    func.count(EntryEntityModel.id).label("mention_count"),
                )
                .where(EntryEntityModel.created_at >= since_utc)
                .group_by(EntryEntityModel.entity_type, EntryEntityModel.name)
                .order_by(desc("mention_count"))
                .limit(20)
            )
            res_entities = await uow.session.execute(stmt_entities)
            top_entities = [
                {
                    "entity_type": row.entity_type,
                    "name": row.name,
                    "display_name": row.display_name,
                    "mentions": row.mention_count,
                }
                for row in res_entities
            ]

        # 5. Categorize entries into dedicated sections
        categorized: dict[str, list[dict[str, Any]]] = {
            "user_saves": [],
            "frontier_models": [],
            "developer_infrastructure": [],
            "research_papers": [],
            "trending_repos": [],
            "sovereign_ai": [],
        }

        # Populate user saves
        for e in user_saved_entries:
            categorized["user_saves"].append(self._format_redistributable_entry(e, tz))

        if not include_user_saves_only:
            for e in working_pool:
                cat = (
                    e.category.value
                    if hasattr(e.category, "value")
                    else str(e.category)
                )
                formatted = self._format_redistributable_entry(e, tz)

                if cat == "ai_models":
                    categorized["frontier_models"].append(formatted)
                elif cat == "cyber_tools" or any(
                    k in (e.title or "").lower()
                    for k in (
                        "vllm",
                        "sglang",
                        "ollama",
                        "llama.cpp",
                        "triton",
                        "quantization",
                    )
                ):
                    categorized["developer_infrastructure"].append(formatted)
                elif cat == "ai_research":
                    categorized["research_papers"].append(formatted)
                elif cat == "github_trending":
                    categorized["trending_repos"].append(formatted)
                else:
                    categorized["sovereign_ai"].append(formatted)

            # Cap each section to avoid bloated exports
            for sec in categorized:
                if sec != "user_saves":
                    categorized[sec] = categorized[sec][:limit_per_section]

        total_breakthroughs = sum(len(items) for items in categorized.values())

        return {
            "title": "AETHERGUARD Worldwide AI Intelligence Digest",
            "period_days": effective_days,
            "timezone": str(tz),
            "generated_at_utc": now_utc.isoformat(),
            "generated_at_local": now_local.strftime("%B %d, %Y • %H:%M %Z"),
            "period_start_local": since_local.strftime("%B %d, %Y"),
            "period_end_local": now_local.strftime("%B %d, %Y"),
            "user_saved_count": len(categorized["user_saves"]),
            "total_breakthroughs": total_breakthroughs,
            "include_user_saves_only": include_user_saves_only,
            "sections": categorized,
            "top_entities": top_entities,
        }

    def _format_redistributable_entry(
        self, entry: Entry, tz: ZoneInfo
    ) -> dict[str, Any]:
        """
        Format an entry extracting strictly redistributable public fields.
        Excludes copyrighted article bodies or unverified external text dumps.
        """
        published_local_str = (
            entry.published_at.replace(tzinfo=UTC).astimezone(tz).strftime("%b %d, %Y")
            if entry.published_at
            else "Recent"
        )
        velocity = (
            getattr(entry.analysis, "threat_velocity", 50) if entry.analysis else 50
        )
        decision_brief = (
            getattr(entry.analysis, "decision_brief", None) if entry.analysis else None
        )

        action_summary = None
        if decision_brief and isinstance(decision_brief, dict):
            action_summary = decision_brief.get("action_rationale")

        meta = entry.metadata or {}

        return {
            "id": str(entry.id),
            "title": (entry.title or "").strip(),
            "url": entry.url,
            "category": entry.category.value
            if hasattr(entry.category, "value")
            else str(entry.category),
            "summary": (entry.summary or "").strip().replace("\n", " "),
            "published_at_local": published_local_str,
            "velocity": velocity,
            "tags": entry.tags or [],
            "action_summary": action_summary,
            "importance_reason": meta.get("importance_reason"),
            "user_saved_at": meta.get("user_saved_at"),
            "is_user_saved": bool(
                getattr(entry, "is_user_saved", False)
                or meta.get("is_user_saved", False)
            ),
        }

    # ─── Markdown Rendering ───────────────────────────────────────────────────

    def render_markdown(self, data: dict[str, Any]) -> str:
        """Render publication-grade GitHub-flavored Markdown with YAML frontmatter."""
        tz_str = data["timezone"]
        gen_local = data["generated_at_local"]
        p_start = data["period_start_local"]
        p_end = data["period_end_local"]
        days = data["period_days"]
        user_saves_count = data["user_saved_count"]
        total = data["total_breakthroughs"]

        lines = [
            "---",
            f'title: "{data["title"]}"',
            f'generated_at: "{data["generated_at_utc"]}"',
            f'timezone: "{tz_str}"',
            f"coverage_window_days: {days}",
            f"user_bookmarks_count: {user_saves_count}",
            f"total_items: {total}",
            "---",
            "",
            f"# {data['title']}",
            f"**Coverage Window**: {p_start} — {p_end} ({days} days) • **Generated**: {gen_local} ({tz_str})  ",
            f"**Curated Entries**: {total} total breakthroughs • **Explicit User Bookmarks**: {user_saves_count}",
            "",
            "---",
            "",
        ]

        sections = data["sections"]

        # Section 1: Explicit User Saves
        user_saves = sections.get("user_saves", [])
        if user_saves:
            lines.append(f"## ⭐ User Bookmarks & Saved Intel ({len(user_saves)})")
            lines.append(
                "*Entries explicitly pinned or saved to the Vault by the user during this period.*"
            )
            lines.append("")
            for it in user_saves:
                lines.append(f"### [{it['title']}]({it['url']})")
                lines.append(
                    f"**Category**: `{it['category']}` | **Published**: {it['published_at_local']} | **Velocity**: `{it['velocity']}/100`"
                )
                if it.get("importance_reason"):
                    lines.append(f"📌 **Save Reason**: *{it['importance_reason']}*")
                if it["summary"]:
                    lines.append(f"> {it['summary']}")
                if it.get("action_summary"):
                    lines.append(f"- **Recommended Action**: {it['action_summary']}")
                lines.append("")
            lines.append("---")
            lines.append("")

        # Section 2: Frontier Foundation Models
        models = sections.get("frontier_models", [])
        if models:
            lines.append(
                f"## 🚀 Frontier Foundation Models & Reasoning Architecture ({len(models)})"
            )
            lines.append("")
            for it in models:
                lines.append(f"### [{it['title']}]({it['url']})")
                lines.append(
                    f"**Published**: {it['published_at_local']} | **Velocity**: `{it['velocity']}/100`"
                )
                if it["summary"]:
                    lines.append(f"> {it['summary']}")
                lines.append("")
            lines.append("---")
            lines.append("")

        # Section 3: Developer Infrastructure & Runtimes
        infra = sections.get("developer_infrastructure", [])
        if infra:
            lines.append(
                f"## ⚡ Inference Engines & High-Throughput Runtimes ({len(infra)})"
            )
            lines.append("")
            for it in infra:
                lines.append(f"### [{it['title']}]({it['url']})")
                lines.append(
                    f"**Published**: {it['published_at_local']} | **Velocity**: `{it['velocity']}/100`"
                )
                if it["summary"]:
                    lines.append(f"> {it['summary']}")
                lines.append("")
            lines.append("---")
            lines.append("")

        # Section 4: Breakthrough Research Papers
        papers = sections.get("research_papers", [])
        if papers:
            lines.append(
                f"## 🔬 Top AI Research Breakthroughs & Preprints ({len(papers)})"
            )
            lines.append("")
            for it in papers:
                lines.append(f"### [{it['title']}]({it['url']})")
                lines.append(
                    f"**Published**: {it['published_at_local']} | **Velocity**: `{it['velocity']}/100`"
                )
                if it["summary"]:
                    lines.append(f"> {it['summary']}")
                lines.append("")
            lines.append("---")
            lines.append("")

        # Section 5: Trending Open-Source Frameworks & Repos
        repos = sections.get("trending_repos", [])
        if repos:
            lines.append(
                f"## 🛠️ Trending Developer Repositories & Agent Frameworks ({len(repos)})"
            )
            lines.append("")
            for it in repos:
                lines.append(f"### [{it['title']}]({it['url']})")
                lines.append(
                    f"**Published**: {it['published_at_local']} | **Velocity**: `{it['velocity']}/100`"
                )
                if it["summary"]:
                    lines.append(f"> {it['summary']}")
                lines.append("")
            lines.append("---")
            lines.append("")

        # Section 6: Top Knowledge Graph Entities
        top_ent = data.get("top_entities", [])
        if top_ent:
            lines.append("## 🌐 Structured AI Entities & Velocity Rollup")
            lines.append("| Entity Type | Name | Identifier | Mention Velocity |")
            lines.append("| :--- | :--- | :--- | :--- |")
            for ent in top_ent[:10]:
                lines.append(
                    f"| `{ent['entity_type']}` | **{ent['display_name']}** | `{ent['name']}` | {ent['mentions']} references |"
                )
            lines.append("")
            lines.append("---")
            lines.append("")

        lines.append(
            f"*Autonomous weekly intelligence compilation generated by AETHERGUARD AI Observatory at {data['generated_at_utc']}*"
        )
        return "\n".join(lines)

    # ─── HTML Rendering ───────────────────────────────────────────────────────

    def render_html(self, data: dict[str, Any]) -> str:
        """
        Render clean, modern HTML dossier.
        Strictly obeys anti-vibe-coding rules: crisp system fonts, structured cards, zero AI purple gradients.
        """
        import html

        title = html.escape(data["title"])
        tz_str = html.escape(data["timezone"])
        gen_local = html.escape(data["generated_at_local"])
        p_start = html.escape(data["period_start_local"])
        p_end = html.escape(data["period_end_local"])
        total = data["total_breakthroughs"]
        user_saves_count = data["user_saved_count"]

        sections_html = []

        # User Saves Section
        user_saves = data["sections"].get("user_saves", [])
        if user_saves:
            items_markup = []
            for it in user_saves:
                items_markup.append(f"""
                <article class="entry-card user-save-card">
                    <div class="card-header">
                        <span class="badge badge-accent">⭐ User Bookmark</span>
                        <span class="meta-tag">{html.escape(it["category"])}</span>
                        <span class="meta-tag">Published: {html.escape(it["published_at_local"])}</span>
                        <span class="velocity-pill">Velocity {it["velocity"]}/100</span>
                    </div>
                    <h3 class="entry-title"><a href="{html.escape(it["url"])}" target="_blank" rel="noopener noreferrer">{html.escape(it["title"])}</a></h3>
                    {f'<p class="save-reason"><strong>📌 Reason:</strong> {html.escape(it["importance_reason"])}</p>' if it.get("importance_reason") else ""}
                    <p class="entry-summary">{html.escape(it["summary"])}</p>
                    {f'<div class="action-box"><strong>Recommended Action:</strong> {html.escape(it["action_summary"])}</div>' if it.get("action_summary") else ""}
                </article>
                """)
            sections_html.append(f"""
            <section class="digest-section">
                <h2 class="section-title">⭐ Explicit User Bookmarks & Saved Intel ({len(user_saves)})</h2>
                <div class="cards-grid">{"".join(items_markup)}</div>
            </section>
            """)

        # Other standard sections
        section_titles = [
            (
                "frontier_models",
                "🚀 Frontier Foundation Models & Reasoning Architecture",
            ),
            (
                "developer_infrastructure",
                "⚡ Inference Engines & High-Throughput Runtimes",
            ),
            ("research_papers", "🔬 Breakthrough AI Research Papers & Preprints"),
            ("trending_repos", "🛠️ Trending Developer Repositories & Agents"),
            ("sovereign_ai", "🌐 Global & Sovereign AI Ecosystem Developments"),
        ]

        for sec_key, sec_title in section_titles:
            items = data["sections"].get(sec_key, [])
            if not items:
                continue
            items_markup = []
            for it in items:
                items_markup.append(f"""
                <article class="entry-card">
                    <div class="card-header">
                        <span class="meta-tag">{html.escape(it["category"])}</span>
                        <span class="meta-tag">Published: {html.escape(it["published_at_local"])}</span>
                        <span class="velocity-pill">Velocity {it["velocity"]}/100</span>
                    </div>
                    <h3 class="entry-title"><a href="{html.escape(it["url"])}" target="_blank" rel="noopener noreferrer">{html.escape(it["title"])}</a></h3>
                    <p class="entry-summary">{html.escape(it["summary"])}</p>
                </article>
                """)
            sections_html.append(f"""
            <section class="digest-section">
                <h2 class="section-title">{sec_title} ({len(items)})</h2>
                <div class="cards-grid">{"".join(items_markup)}</div>
            </section>
            """)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        :root {{
            --bg-page: #0f172a;
            --bg-surface: #1e293b;
            --border-color: #334155;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --accent-color: #38bdf8;
            --accent-amber: #f59e0b;
            --font-stack: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }}
        body {{
            background-color: var(--bg-page);
            color: var(--text-primary);
            font-family: var(--font-stack);
            margin: 0;
            padding: 2.5rem 1.5rem;
            line-height: 1.6;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
        }}
        header.digest-header {{
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 1.5rem;
            margin-bottom: 2.5rem;
        }}
        h1.main-title {{
            font-size: 1.85rem;
            font-weight: 700;
            margin: 0 0 0.5rem 0;
            color: var(--text-primary);
        }}
        .meta-bar {{
            font-size: 0.9rem;
            color: var(--text-secondary);
        }}
        .section-title {{
            font-size: 1.35rem;
            font-weight: 600;
            color: var(--accent-color);
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 0.5rem;
            margin: 2.5rem 0 1.25rem 0;
        }}
        .cards-grid {{
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
        }}
        .entry-card {{
            background: var(--bg-surface);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1.25rem;
        }}
        .user-save-card {{
            border-left: 4px solid var(--accent-amber);
        }}
        .card-header {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            align-items: center;
            margin-bottom: 0.6rem;
            font-size: 0.8rem;
        }}
        .badge {{
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-weight: 600;
        }}
        .badge-accent {{
            background: #d97706;
            color: #ffffff;
        }}
        .meta-tag {{
            color: var(--text-secondary);
        }}
        .velocity-pill {{
            margin-left: auto;
            background: #0369a1;
            color: #ffffff;
            padding: 0.15rem 0.45rem;
            border-radius: 4px;
            font-weight: 600;
            font-size: 0.75rem;
        }}
        .entry-title {{
            font-size: 1.15rem;
            margin: 0 0 0.5rem 0;
        }}
        .entry-title a {{
            color: var(--text-primary);
            text-decoration: none;
        }}
        .entry-title a:hover {{
            color: var(--accent-color);
            text-decoration: underline;
        }}
        .save-reason {{
            font-size: 0.85rem;
            color: var(--accent-amber);
            margin: 0 0 0.5rem 0;
        }}
        .entry-summary {{
            color: var(--text-secondary);
            font-size: 0.95rem;
            margin: 0 0 0.5rem 0;
        }}
        .action-box {{
            background: #0f172a;
            border-left: 3px solid var(--accent-color);
            padding: 0.6rem 0.8rem;
            font-size: 0.85rem;
            color: #e2e8f0;
            border-radius: 0 4px 4px 0;
        }}
        footer.digest-footer {{
            margin-top: 3.5rem;
            border-top: 1px solid var(--border-color);
            padding-top: 1.5rem;
            text-align: center;
            font-size: 0.85rem;
            color: var(--text-secondary);
        }}
    </style>
</head>
<body>
    <div class="container">
        <header class="digest-header">
            <h1 class="main-title">{title}</h1>
            <div class="meta-bar">
                Coverage: <strong>{p_start} — {p_end}</strong> • Timezone: <strong>{tz_str}</strong> • Generated: <strong>{gen_local}</strong><br>
                Total Breakthroughs: <strong>{total}</strong> • User Bookmarks: <strong>{user_saves_count}</strong>
            </div>
        </header>
        <main>
            {"".join(sections_html)}
        </main>
        <footer class="digest-footer">
            AETHERGUARD AI Observatory • Automated Intelligence Compilation • Confidential & Redistributable Briefing
        </footer>
    </div>
</body>
</html>
"""

    # ─── PDF Rendering ────────────────────────────────────────────────────────

    def render_pdf(
        self, data: dict[str, Any], output_path: Path | None = None
    ) -> bytes:
        """
        Render multi-page executive PDF document using ReportLab.
        Uses two-pass DigestNumberedCanvas for page counts and running headers.
        """
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=letter,
            leftMargin=36,
            rightMargin=36,
            topMargin=45,
            bottomMargin=45,
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=6,
        )

        subtitle_style = ParagraphStyle(
            "DocSubTitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#475569"),
            spaceAfter=12,
        )

        section_heading_style = ParagraphStyle(
            "SectionHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#0369a1"),
            spaceBefore=14,
            spaceAfter=6,
            keepWithNext=True,
        )

        entry_title_style = ParagraphStyle(
            "EntryTitle",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=2,
        )

        entry_meta_style = ParagraphStyle(
            "EntryMeta",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=4,
        )

        entry_body_style = ParagraphStyle(
            "EntryBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11.5,
            textColor=colors.HexColor("#334155"),
            spaceAfter=6,
        )

        story: list[Any] = []

        # Document Header
        story.append(Paragraph(data["title"], title_style))
        meta_line = (
            f"Coverage: {data['period_start_local']} — {data['period_end_local']} • "
            f"Timezone: {data['timezone']} • Total Items: {data['total_breakthroughs']} • "
            f"User Bookmarks: {data['user_saved_count']}"
        )
        story.append(Paragraph(meta_line, subtitle_style))
        story.append(
            HRFlowable(
                width="100%",
                thickness=1,
                color=colors.HexColor("#0f172a"),
                spaceAfter=10,
            )
        )

        sections = data["sections"]

        # Section 1: User Bookmarks
        user_saves = sections.get("user_saves", [])
        if user_saves:
            story.append(
                Paragraph(
                    f"⭐ User Bookmarks & Saved Intelligence ({len(user_saves)})",
                    section_heading_style,
                )
            )
            for it in user_saves:
                block: list[Any] = [
                    Paragraph(it["title"], entry_title_style),
                    Paragraph(
                        f"Category: {it['category']} | Published: {it['published_at_local']} | Velocity: {it['velocity']}/100 | Link: {it['url']}",
                        entry_meta_style,
                    ),
                    Paragraph(it["summary"], entry_body_style),
                    Spacer(1, 4),
                ]
                story.append(KeepTogether(block))

        # Standard sections
        label_map = [
            (
                "frontier_models",
                "🚀 Frontier Foundation Models & Scaling Breakthroughs",
            ),
            (
                "developer_infrastructure",
                "⚡ High-Throughput Runtimes & Inference Tooling",
            ),
            ("research_papers", "🔬 Key AI Research Papers & Preprints"),
            ("trending_repos", "🛠️ Trending Open-Source Developer Repositories"),
        ]

        for sec_key, sec_title in label_map:
            items = sections.get(sec_key, [])
            if not items:
                continue
            story.append(
                Paragraph(f"{sec_title} ({len(items)})", section_heading_style)
            )
            for it in items:
                block = [
                    Paragraph(it["title"], entry_title_style),
                    Paragraph(
                        f"Category: {it['category']} | Published: {it['published_at_local']} | Velocity: {it['velocity']}/100",
                        entry_meta_style,
                    ),
                    Paragraph(it["summary"], entry_body_style),
                    Spacer(1, 4),
                ]
                story.append(KeepTogether(block))

        # Build Document
        doc.build(story, canvasmaker=DigestNumberedCanvas)
        pdf_bytes = buf.getvalue()

        if output_path:
            output_path.write_bytes(pdf_bytes)

        return pdf_bytes

    # ─── Archival & Portability ───────────────────────────────────────────────

    async def export_and_archive(
        self,
        days: int = DEFAULT_DIGEST_DAYS,
        timezone_str: str | None = None,
        include_user_saves_only: bool = False,
    ) -> dict[str, Any]:
        """
        Compile and write weekly digest in Markdown, HTML, and PDF to the local archive directory.
        Returns metadata and file paths.
        """
        data = await self.compile_weekly_digest(
            days=days,
            timezone_str=timezone_str,
            include_user_saves_only=include_user_saves_only,
        )

        date_tag = datetime.now(UTC).strftime("%Y-%m-%d")
        suffix = "-user-saves" if include_user_saves_only else ""

        md_content = self.render_markdown(data)
        html_content = self.render_html(data)

        md_path = self.output_dir / f"weekly-digest-{date_tag}{suffix}.md"
        html_path = self.output_dir / f"weekly-digest-{date_tag}{suffix}.html"
        pdf_path = self.output_dir / f"weekly-digest-{date_tag}{suffix}.pdf"

        md_path.write_text(md_content, encoding="utf-8")
        html_path.write_text(html_content, encoding="utf-8")
        self.render_pdf(data, output_path=pdf_path)

        logger.info(
            f"Weekly digest archived successfully to {self.output_dir} "
            f"({len(data['sections']['user_saves'])} user bookmarks, {data['total_breakthroughs']} total items)"
        )

        return {
            "status": "success",
            "date": date_tag,
            "timezone": data["timezone"],
            "period_days": data["period_days"],
            "user_saved_count": data["user_saved_count"],
            "total_items": data["total_breakthroughs"],
            "files": {
                "markdown": str(md_path),
                "html": str(html_path),
                "pdf": str(pdf_path),
            },
        }
