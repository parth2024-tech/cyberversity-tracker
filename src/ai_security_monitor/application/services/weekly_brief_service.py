"""
Weekly "What Changed" Intelligence Brief Service (Feature 12).
Generates structured executive weekly briefing across worldwide AI ecosystems with:
- Regional releases grouped by lab (China, North America, Europe, Global)
- Benchmark and Leaderboard shifts (New #1 models, ranking surges)
- Biggest clustered stories (by corroboration volume and newsworthiness)
- Source health transitions (sources went STALE / DEAD / RECOVERED)
- Regional and lab coverage gap analysis
Outputs Markdown and JSON to data/briefs/YYYY-WW.md & .json (not tracked in git).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork

logger = get_logger(__name__)

# Canonical Regional Frontier Labs mapping
CANONICAL_LABS_BY_REGION = {
    "china": [
        "DeepSeek",
        "Alibaba / Qwen",
        "Zhipu AI",
        "Moonshot AI / Kimi",
        "Baichuan",
        "MiniMax",
        "StepFun",
        "ByteDance",
        "Tencent Hunyuan",
        "Baidu Ernie",
        "Shanghai AI Lab",
        "Tsinghua",
    ],
    "north_america": [
        "OpenAI",
        "Anthropic",
        "Meta AI",
        "Google DeepMind",
        "Microsoft",
        "xAI",
        "NVIDIA",
    ],
    "europe": [
        "Mistral AI",
        "Kyutai",
        "Aleph Alpha",
        "DeepL",
    ],
}


@dataclass
class WeeklyBrief:
    """Domain representation of a weekly intelligence brief."""

    year: int
    week: int
    start_date: datetime
    end_date: datetime
    releases_by_region: dict[str, dict[str, list[dict[str, Any]]]] = field(
        default_factory=dict
    )
    leaderboard_shifts: list[dict[str, Any]] = field(default_factory=list)
    top_stories: list[dict[str, Any]] = field(default_factory=list)
    health_transitions: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {
            "went_stale": [],
            "went_dead": [],
            "recovered": [],
        }
    )
    coverage_gaps: list[str] = field(default_factory=list)
    markdown: str = ""
    json_data: dict[str, Any] = field(default_factory=dict)

    def render_markdown(self) -> str:
        """Render brief content as clean, executive-grade Markdown."""
        lines: list[str] = [
            "# 🌐 Worldwide AI Ecosystem: Weekly 'What Changed' Brief",
            f"**Week {self.year}-W{self.week:02d}** | {self.start_date.strftime('%B %d, %Y')} – {self.end_date.strftime('%B %d, %Y')}",
            "",
            "> Automated synthesis of frontier releases, benchmark shifts, corroborating story clusters, and telemetry.",
            "",
            "---",
            "",
            "## 1. Regional Frontier Model Releases (By Lab)",
            "",
        ]

        if not self.releases_by_region:
            lines.append("_No major frontier releases recorded in this period._\n")
        else:
            for region, labs in self.releases_by_region.items():
                reg_title = region.replace("_", " ").title()
                lines.append(f"### {reg_title}")
                if not labs:
                    lines.append("_No primary releases._\n")
                    continue
                for lab_name, releases in labs.items():
                    lines.append(f"- **{lab_name}** ({len(releases)}):")
                    for rel in releases:
                        title = rel.get("title", "Untitled")
                        url = rel.get("url", "#")
                        lines.append(f"  - [{title}]({url})")
                lines.append("")

        lines.extend(
            [
                "---",
                "",
                "## 2. Benchmark & Leaderboard Shifts (New #1 & SOTA Moves)",
                "",
            ]
        )
        if not self.leaderboard_shifts:
            lines.append(
                "_No significant leaderboard shifts or new #1 SOTA models this week._\n"
            )
        else:
            for shift in self.leaderboard_shifts:
                model = shift.get("model", "Unknown Model")
                lb = shift.get("leaderboard", "Leaderboard")
                event_type = shift.get("event_type", "shift").replace("_", " ").title()
                detail = shift.get("detail", "")
                lines.append(f"- **{event_type}**: **{model}** on _{lb}_ – {detail}")
            lines.append("")

        lines.extend(
            [
                "---",
                "",
                "## 3. Biggest Clustered Stories (By Corroboration & Velocity)",
                "",
            ]
        )
        if not self.top_stories:
            lines.append("_No corroborated story clusters detected._\n")
        else:
            for idx, story in enumerate(self.top_stories, 1):
                title = story.get("title", "Untitled")
                cluster_size = story.get("cluster_size", 1)
                score = story.get("score", 0.0)
                summary = story.get("summary", "")
                lines.append(
                    f"{idx}. **{title}** (Sources: {cluster_size} | Score: {score:.1f})\n"
                    f"   _{summary}_\n"
                )

        lines.extend(
            [
                "---",
                "",
                "## 4. Source Health & Infrastructure Telemetry",
                "",
            ]
        )
        dead = self.health_transitions.get("went_dead", [])
        stale = self.health_transitions.get("went_stale", [])
        recovered = self.health_transitions.get("recovered", [])

        if not dead and not stale and not recovered:
            lines.append(
                "✅ _All monitored ecosystem feeds remained operational and healthy._\n"
            )
        else:
            if dead:
                lines.append(
                    f"- 🔴 **Feeds Went Dead** ({len(dead)}): "
                    + ", ".join(d.get("name", "") for d in dead)
                )
            if stale:
                lines.append(
                    f"- 🟡 **Feeds Stale** ({len(stale)}): "
                    + ", ".join(s.get("name", "") for s in stale)
                )
            if recovered:
                lines.append(
                    f"- 🟢 **Feeds Recovered** ({len(recovered)}): "
                    + ", ".join(r.get("name", "") for r in recovered)
                )
            lines.append("")

        lines.extend(
            [
                "---",
                "",
                "## 5. Coverage Gap Analysis",
                "",
            ]
        )
        if not self.coverage_gaps:
            lines.append(
                "✅ _No critical regional or lab coverage gaps identified for this period._\n"
            )
        else:
            for gap in self.coverage_gaps:
                lines.append(f"- ⚠️ {gap}")
            lines.append("")

        self.markdown = "\n".join(lines)
        return self.markdown

    def to_dict(self) -> dict[str, Any]:
        """Convert brief to dictionary for JSON output."""
        data = {
            "year": self.year,
            "week": self.week,
            "period": {
                "start": self.start_date.isoformat(),
                "end": self.end_date.isoformat(),
            },
            "releases_by_region": self.releases_by_region,
            "leaderboard_shifts": self.leaderboard_shifts,
            "top_stories": self.top_stories,
            "health_transitions": self.health_transitions,
            "coverage_gaps": self.coverage_gaps,
        }
        self.json_data = data
        return data

    def save(self, base_dir: Path | str = "data/briefs") -> tuple[Path, Path]:
        """Save brief to data/briefs/YYYY-WW.md and data/briefs/YYYY-WW.json."""
        out_dir = Path(base_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        filename_base = f"{self.year}-W{self.week:02d}"
        md_path = out_dir / f"{filename_base}.md"
        json_path = out_dir / f"{filename_base}.json"

        if not self.markdown:
            self.render_markdown()
        if not self.json_data:
            self.to_dict()

        md_path.write_text(self.markdown, encoding="utf-8")
        json_path.write_text(
            json.dumps(self.json_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        return md_path, json_path


class WeeklyBriefService:
    """Service to aggregate weekly data and generate the 'What Changed' brief."""

    @classmethod
    def get_week_bounds(cls, year: int, week: int) -> tuple[datetime, datetime]:
        """Calculate start and end datetime (UTC) for a given ISO year and week."""
        # ISO week 1 starts on Monday
        first_day_of_year = datetime(year, 1, 4, tzinfo=UTC)
        start_of_week_1 = first_day_of_year - timedelta(
            days=first_day_of_year.isoweekday() - 1
        )
        start_date = start_of_week_1 + timedelta(weeks=week - 1)
        start_date = datetime(
            start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=UTC
        )
        end_date = start_date + timedelta(days=6, hours=23, minutes=59, seconds=59)
        return start_date, end_date

    async def generate_brief(
        self,
        uow: UnitOfWork,
        year: int | None = None,
        week: int | None = None,
        output_dir: Path | str | None = None,
    ) -> WeeklyBrief:
        """
        Synthesize weekly brief without requiring new LLM API calls.
        Built deterministically from entries, source health telemetry, and story clusters.
        """
        now = datetime.now(UTC)
        if year is None or week is None:
            iso_year, iso_week, _ = now.isocalendar()
            year = year or iso_year
            week = week or iso_week

        start_date, end_date = self.get_week_bounds(year, week)

        # 1. Fetch Entries in period
        filters = EntryFilters(
            since=start_date,
            until=end_date,
        )
        entries = await uow.entries.list(
            filters=filters,
            pagination=PaginationParams(limit=500, offset=0),
        )

        # 2. Group Releases by Region and Lab
        releases_by_region: dict[str, dict[str, list[dict[str, Any]]]] = {
            "china": {},
            "north_america": {},
            "europe": {},
            "global": {},
        }

        # Track covered labs to detect coverage gaps
        covered_labs_by_region: dict[str, set[str]] = {
            "china": set(),
            "north_america": set(),
            "europe": set(),
        }

        # Candidate story clusters
        cluster_map: dict[str, list[Entry]] = {}

        for entry in entries:
            meta = entry.metadata or {}
            reg = str(
                meta.get("region") or meta.get("subject_region") or "global"
            ).lower()
            if reg not in releases_by_region:
                reg = "global"

            # Determine lab
            lab = meta.get("lab") or meta.get("author") or "Community / Open Source"
            lab_str = str(lab)

            # Check if relevant release / breakthrough
            is_model_release = (
                entry.category == Category.AI_MODELS
                or bool(meta.get("is_primary"))
                or "release" in entry.title.lower()
                or "开源" in entry.title
                or "发布" in entry.title
            )

            if is_model_release:
                if lab_str not in releases_by_region[reg]:
                    releases_by_region[reg][lab_str] = []
                releases_by_region[reg][lab_str].append(
                    {
                        "id": str(entry.id),
                        "title": entry.title,
                        "url": entry.url,
                        "published_at": entry.published_at.isoformat(),
                    }
                )
                if reg in covered_labs_by_region:
                    for known_lab in CANONICAL_LABS_BY_REGION.get(reg, []):
                        if (
                            known_lab.lower() in lab_str.lower()
                            or known_lab.lower() in entry.title.lower()
                        ):
                            covered_labs_by_region[reg].add(known_lab)

            # Cluster tracking
            story_key = str(
                meta.get("story_id")
                or meta.get("canonical_cluster_id")
                or entry.title[:30].lower()
            )
            if story_key not in cluster_map:
                cluster_map[story_key] = []
            cluster_map[story_key].append(entry)

        # 3. Detect Leaderboard Shifts
        leaderboard_shifts: list[dict[str, Any]] = []
        for entry in entries:
            meta = entry.metadata or {}
            if (
                meta.get("is_leaderboard")
                or "leaderboard" in entry.title.lower()
                or "arena" in entry.title.lower()
            ):
                shift_event = meta.get("leaderboard_event") or "new_sota"
                leaderboard_shifts.append(
                    {
                        "model": meta.get("model_name") or entry.title.split(":")[0],
                        "leaderboard": meta.get("leaderboard_name")
                        or "LMSYS / OpenLLM",
                        "event_type": shift_event,
                        "detail": entry.summary[:140] if entry.summary else entry.title,
                    }
                )

        # 4. Synthesize Biggest Clustered Stories
        top_stories: list[dict[str, Any]] = []
        for key, cluster_entries in cluster_map.items():
            first_entry = cluster_entries[0]
            cluster_size = len(cluster_entries)
            score = 0.0
            for e in cluster_entries:
                e_meta = e.metadata or {}
                s = float(
                    e_meta.get("ai_velocity_score")
                    or e_meta.get("score")
                    or e_meta.get("heat")
                    or 0.0
                )
                if s > score:
                    score = s

            # If score is 0, give base proportional to cluster size
            if score == 0.0:
                score = min(50.0 + cluster_size * 10.0, 95.0)

            top_stories.append(
                {
                    "title": first_entry.title,
                    "cluster_size": cluster_size,
                    "score": score,
                    "summary": first_entry.summary[:200]
                    if first_entry.summary
                    else first_entry.title,
                }
            )

        top_stories.sort(key=lambda s: (s["cluster_size"], s["score"]), reverse=True)
        top_stories = top_stories[:5]

        # 5. Source Health Telemetry
        sources = await uow.sources.list(enabled_only=False)
        went_dead: list[dict[str, Any]] = []
        went_stale: list[dict[str, Any]] = []
        recovered: list[dict[str, Any]] = []

        for src in sources:
            src_meta = src.config or {}
            health_state = src_meta.get("health_state", "ok")
            if health_state == "dead" or not src.enabled:
                went_dead.append({"name": src.name, "url": src.url})
            elif health_state == "stale":
                went_stale.append({"name": src.name, "url": src.url})
            elif src_meta.get("recently_recovered"):
                recovered.append({"name": src.name, "url": src.url})

        health_transitions = {
            "went_dead": went_dead,
            "went_stale": went_stale,
            "recovered": recovered,
        }

        # 6. Coverage Gap Analysis
        coverage_gaps: list[str] = []
        for reg, known_labs in CANONICAL_LABS_BY_REGION.items():
            covered = covered_labs_by_region.get(reg, set())
            reg_display = reg.replace("_", " ").title()
            if not releases_by_region.get(reg):
                coverage_gaps.append(
                    f"Zero releases ingested for {reg_display} ecosystem this week."
                )
            else:
                missing = [lab for lab in known_labs if lab not in covered]
                if len(missing) == len(known_labs):
                    coverage_gaps.append(
                        f"No releases from top tier labs in {reg_display} ({', '.join(known_labs[:3])})."
                    )

        # 7. Construct and optionally persist brief
        brief = WeeklyBrief(
            year=year,
            week=week,
            start_date=start_date,
            end_date=end_date,
            releases_by_region=releases_by_region,
            leaderboard_shifts=leaderboard_shifts,
            top_stories=top_stories,
            health_transitions=health_transitions,
            coverage_gaps=coverage_gaps,
        )

        brief.render_markdown()
        brief.to_dict()

        if output_dir:
            brief.save(output_dir)

        return brief
