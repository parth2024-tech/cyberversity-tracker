"""
Missed-Story Audit Service.
Finds intelligence blind spots and evaluates capture rate and lag times
against verified ground-truth AI foundation model and framework announcements.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_security_monitor.domain.entities import AuditStory
from ai_security_monitor.infrastructure.database.models import (
    AuditResultModel,
    AuditStoryModel,
    EntryModel,
    SourceModel,
)

logger = logging.getLogger(__name__)


def normalize_tokens(text: str) -> list[str]:
    """
    Generate normalized token representations for hyphen/dot/space insensitive matching.
    e.g. 'DeepSeek-V2.5' -> ['deepseek-v2.5', 'deepseek v2.5', 'deepseekv2.5', 'deepseek v2 5', 'deepseekv25']
    """
    t = text.lower().strip()
    variants = {t}
    # Replace hyphens and underscores with spaces
    variants.add(re.sub(r"[-_]", " ", t))
    # Remove hyphens and underscores completely
    variants.add(re.sub(r"[-_]", "", t))
    # Replace dots, hyphens, underscores with spaces
    variants.add(re.sub(r"[-_.]", " ", t))
    # Remove dots, hyphens, underscores completely
    variants.add(re.sub(r"[-_.]", "", t))
    return list(variants)


def matches_story_tokens(
    story: AuditStory | AuditStoryModel,
    title: str,
    summary: str,
    url: str,
) -> bool:
    """
    Check if an entry matches model names and org tokens of an audit story.
    Supports punctuation-insensitive synonyms (e.g. DeepSeek-V4.1 vs DeepSeek V4.1).
    """
    entry_text = f"{title} {summary} {url}".lower()
    entry_clean = re.sub(r"[-_.]", " ", entry_text)

    # 1. Match specific model names
    for m in story.model_names or []:
        for variant in normalize_tokens(m):
            if variant in entry_text or variant in entry_clean:
                return True

    # 2. Match combinations of org tokens and release keywords
    org_match = False
    for o in story.org_tokens or []:
        for variant in normalize_tokens(o):
            pattern = (
                rf"\b{re.escape(variant)}\b" if len(variant) > 3 else re.escape(variant)
            )
            if re.search(pattern, entry_text) or re.search(pattern, entry_clean):
                org_match = True
                break
        if org_match:
            break

    if org_match:
        # Check if title also mentions key story terms
        story_title_tokens = [
            tok
            for tok in re.findall(r"\w+", story.title.lower())
            if len(tok) > 3
            and tok
            not in {"foundation", "model", "release", "models", "open", "source"}
        ]
        for tok in story_title_tokens:
            if tok in entry_text or tok in entry_clean:
                return True

    return False


class AuditService:
    """Service executing missed-story benchmark evaluations and lag telemetry."""

    async def run_audit(
        self,
        session: AsyncSession,
        since: datetime | None = None,
        region: str | None = None,
        window_days: int = 7,
    ) -> dict[str, Any]:
        """
        Execute missed-story audit evaluation across registered ground-truth benchmark stories.
        """
        ref_now = datetime.now(UTC)

        # 1. Query benchmark stories
        stories_stmt = select(AuditStoryModel).order_by(
            AuditStoryModel.release_date.desc()
        )
        if since:
            since_naive = since.replace(tzinfo=None) if since.tzinfo else since
            stories_stmt = stories_stmt.where(
                or_(
                    AuditStoryModel.release_date >= since,
                    AuditStoryModel.release_date >= since_naive,
                )
            )
        if region:
            stories_stmt = stories_stmt.where(
                AuditStoryModel.region == region.lower().strip()
            )

        stories_res = await session.execute(stories_stmt)
        stories = list(stories_res.scalars().all())

        if not stories:
            return {
                "run_at": ref_now.isoformat(),
                "summary": {
                    "total_stories": 0,
                    "captured_count": 0,
                    "capture_rate_pct": 0.0,
                    "status": "NO_STORIES",
                },
                "results": [],
                "markdown_report": "### AetherGuard Missed-Story Audit Report\n\n*No benchmark stories found.*",
            }

        # 2. Query sources to map source_id to source_name
        sources_res = await session.execute(select(SourceModel))
        sources_map = {s.id: s.name for s in sources_res.scalars().all()}

        # 3. Query all non-purged entries within the audit window
        min_release_date = min(s.release_date for s in stories)
        if min_release_date.tzinfo is None:
            min_release_date = min_release_date.replace(tzinfo=UTC)

        search_cutoff = min_release_date - timedelta(days=window_days + 1)
        search_cutoff_naive = search_cutoff.replace(tzinfo=None)

        entries_stmt = (
            select(EntryModel)
            .where(EntryModel.is_purged.is_(False))
            .where(
                or_(
                    EntryModel.published_at >= search_cutoff,
                    EntryModel.published_at >= search_cutoff_naive,
                    EntryModel.fetched_at >= search_cutoff,
                    EntryModel.fetched_at >= search_cutoff_naive,
                )
            )
            .order_by(EntryModel.published_at.asc())
        )
        entries_res = await session.execute(entries_stmt)
        entries = list(entries_res.scalars().all())

        # 4. Evaluate each story against entries
        evaluated_results: list[dict[str, Any]] = []
        captured_count = 0
        china_total = 0
        china_captured = 0
        lag_values: list[float] = []
        missed_stories: list[dict[str, Any]] = []

        for story in stories:
            is_china = story.region.lower().strip() == "china"
            if is_china:
                china_total += 1

            story_dt = story.release_date
            if story_dt.tzinfo is None:
                story_dt = story_dt.replace(tzinfo=UTC)

            window_start = story_dt - timedelta(days=window_days)
            window_end = story_dt + timedelta(days=window_days)

            matched_entry: EntryModel | None = None
            candidate_matches: list[dict[str, Any]] = []

            for entry in entries:
                if not matches_story_tokens(
                    story, entry.title, entry.summary, entry.url
                ):
                    continue

                entry_dt = entry.published_at or entry.fetched_at
                if not entry_dt:
                    continue
                if entry_dt.tzinfo is None:
                    entry_dt = entry_dt.replace(tzinfo=UTC)

                # Check window
                if window_start <= entry_dt <= window_end:
                    matched_entry = entry
                    break
                elif abs((entry_dt - story_dt).total_seconds()) <= 14 * 86400:
                    candidate_matches.append(
                        {
                            "entry_id": entry.id,
                            "title": entry.title,
                            "published_at": entry_dt.isoformat(),
                            "source": sources_map.get(entry.source_id, "Unknown"),
                            "date_offset_days": round(
                                (entry_dt - story_dt).total_seconds() / 86400.0, 1
                            ),
                        }
                    )

            if matched_entry:
                captured_count += 1
                if is_china:
                    china_captured += 1

                entry_dt = matched_entry.published_at or matched_entry.fetched_at
                if entry_dt and entry_dt.tzinfo is None:
                    entry_dt = entry_dt.replace(tzinfo=UTC)

                lag = (
                    max(0.0, round(((entry_dt - story_dt).total_seconds() / 3600.0), 1))
                    if entry_dt
                    else 0.0
                )
                lag_values.append(lag)

                source_name = sources_map.get(matched_entry.source_id, "Unknown Source")

                result_model = AuditResultModel(
                    id=str(uuid4()),
                    story_id=story.id,
                    run_at=ref_now,
                    captured=True,
                    first_seen_at=entry_dt,
                    lag_hours=lag,
                    matched_entry_id=matched_entry.id,
                    matched_source=source_name,
                    match_method="token_window",
                    diagnostic="Captured within 7-day publication window.",
                    created_at=ref_now,
                )
                session.add(result_model)

                evaluated_results.append(
                    {
                        "story_id": story.id,
                        "title": story.title,
                        "lab_name": story.lab_name,
                        "region": story.region,
                        "release_date": story_dt.strftime("%Y-%m-%d"),
                        "captured": True,
                        "lag_hours": lag,
                        "first_seen_at": entry_dt.strftime("%Y-%m-%d %H:%M")
                        if entry_dt
                        else "—",
                        "matched_source": source_name,
                        "diagnostic": "Captured",
                    }
                )
            else:
                # Missed story
                diagnostic = (
                    f"Candidate found but outside 7d window ({len(candidate_matches)} entries)"
                    if candidate_matches
                    else "Zero matching entries found across active threat & research feeds"
                )
                todo_action = (
                    f"Expand window or check ingestion feed for {story.lab_name}"
                    if candidate_matches
                    else f"Add primary release feed for {story.lab_name} ({story.canonical_url})"
                )

                result_model = AuditResultModel(
                    id=str(uuid4()),
                    story_id=story.id,
                    run_at=ref_now,
                    captured=False,
                    first_seen_at=None,
                    lag_hours=None,
                    matched_entry_id=None,
                    matched_source=None,
                    match_method="token_window",
                    diagnostic=diagnostic,
                    created_at=ref_now,
                )
                session.add(result_model)

                miss_record = {
                    "story_id": story.id,
                    "title": story.title,
                    "lab_name": story.lab_name,
                    "region": story.region,
                    "release_date": story_dt.strftime("%Y-%m-%d"),
                    "canonical_url": story.canonical_url,
                    "diagnostic": diagnostic,
                    "todo_action": todo_action,
                    "candidates": candidate_matches,
                }
                missed_stories.append(miss_record)

                evaluated_results.append(
                    {
                        "story_id": story.id,
                        "title": story.title,
                        "lab_name": story.lab_name,
                        "region": story.region,
                        "release_date": story_dt.strftime("%Y-%m-%d"),
                        "captured": False,
                        "lag_hours": None,
                        "first_seen_at": "—",
                        "matched_source": "—",
                        "diagnostic": diagnostic,
                    }
                )

        await session.flush()

        # 5. Compute summary metrics & pass/fail criteria
        total_stories_count = len(stories)
        capture_rate = round((captured_count / total_stories_count) * 100.0, 1)
        china_capture_rate = (
            round((china_captured / china_total) * 100.0, 1)
            if china_total > 0
            else 100.0
        )
        med_lag = round(median(lag_values), 1) if lag_values else 0.0

        overall_pass = capture_rate >= 80.0
        china_pass = china_capture_rate >= 70.0
        lag_pass = med_lag <= 24.0
        audit_passed = overall_pass and china_pass and lag_pass

        markdown_report = self._render_markdown_report(
            evaluated_results=evaluated_results,
            missed_stories=missed_stories,
            summary={
                "total_stories": total_stories_count,
                "captured_count": captured_count,
                "capture_rate_pct": capture_rate,
                "china_total": china_total,
                "china_captured": china_captured,
                "china_capture_rate_pct": china_capture_rate,
                "median_lag_hours": med_lag,
                "audit_passed": audit_passed,
            },
        )

        return {
            "run_at": ref_now.isoformat(),
            "summary": {
                "total_stories": total_stories_count,
                "captured_count": captured_count,
                "missed_count": len(missed_stories),
                "capture_rate_pct": capture_rate,
                "china_total": china_total,
                "china_captured": china_captured,
                "china_capture_rate_pct": china_capture_rate,
                "median_lag_hours": med_lag,
                "pass_criteria": {
                    "overall_pass": overall_pass,
                    "china_pass": china_pass,
                    "lag_pass": lag_pass,
                    "status": "PASS" if audit_passed else "NEEDS_TUNING",
                },
            },
            "missed_stories": missed_stories,
            "results": evaluated_results,
            "markdown_report": markdown_report,
            "markdown_table": markdown_report,
        }

    def _render_markdown_report(
        self,
        evaluated_results: list[dict[str, Any]],
        missed_stories: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> str:
        """Render copy-pasteable Markdown report table."""
        lines: list[str] = []
        lines.append("### AetherGuard Missed-Story & Ecosystem Audit Report\n")

        status_str = "✅ **PASS**" if summary["audit_passed"] else "⚠️ **NEEDS_TUNING**"
        lines.append(
            f"**Audit Verdict**: {status_str} | "
            f"**Overall Capture Rate**: `{summary['capture_rate_pct']}%` ({summary['captured_count']}/{summary['total_stories']}) | "
            f"**China Capture Rate**: `{summary['china_capture_rate_pct']}%` ({summary['china_captured']}/{summary['china_total']}) | "
            f"**Median Ingestion Lag**: `{summary['median_lag_hours']}h`\n"
        )

        # Table 1: Evaluated Benchmark Stories
        lines.append("#### 1. Benchmark Model & Story Capture Log")
        lines.append(
            "| Story / Breakthrough | Lab | Region | Release Date | Status | Lag | First Reported By |"
        )
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :--- |")
        for r in evaluated_results:
            badge = "`CAPTURED`" if r["captured"] else "**`MISSED`**"
            lag_str = f"{r['lag_hours']}h" if r["lag_hours"] is not None else "—"
            lines.append(
                f"| **{r['title'][:45]}** | {r['lab_name']} | {r['region'].upper()} | "
                f"{r['release_date']} | {badge} | {lag_str} | {r['matched_source']} |"
            )
        lines.append("")

        # Table 2: Missed Story Diagnostics & Action Items
        lines.append("#### 2. Missed Story Diagnostics & Feed To-Do Actions")
        if not missed_stories:
            lines.append(
                "*Zero blind spots detected. All ground-truth benchmark stories captured successfully!*"
            )
        else:
            lines.append(
                "| Missed Story | Lab | Diagnostic Finding | Prescribed Action Item |"
            )
            lines.append("| :--- | :---: | :--- | :--- |")
            for m in missed_stories:
                lines.append(
                    f"| **{m['title'][:40]}** | {m['lab_name']} | {m['diagnostic']} | `{m['todo_action']}` |"
                )

        return "\n".join(lines)


audit_service = AuditService()
