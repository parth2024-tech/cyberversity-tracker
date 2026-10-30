"""
Coverage and Lab Telemetry Service.
Calculates regional and per-lab AI ecosystem intelligence coverage,
identifies ecosystem blind spots and source gaps, and provides
structured JSON and copy-pasteable Markdown reports.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_security_monitor.domain.entities import Lab
from ai_security_monitor.infrastructure.database.models import (
    EntryModel,
    LabModel,
    SourceModel,
)

logger = logging.getLogger(__name__)

DEFAULT_FRONTIER_LABS: list[dict[str, Any]] = [
    {
        "name": "DeepSeek",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["deepseek-ai"],
        "github_orgs": ["deepseek-ai"],
        "modelscope_ids": ["deepseek-ai"],
        "wechat_accounts": ["deepseek"],
        "aliases": ["deepseek", "深度求索", "deepseek-r1", "deepseek-v3", "deepseek-coder", "deepseek-math"],
        "notes": "High-efficiency open-weights frontier lab (Hangzhou High-Flyer / DeepSeek AI)",
    },
    {
        "name": "Qwen / Alibaba",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["Qwen"],
        "github_orgs": ["QwenLM", "alibaba"],
        "modelscope_ids": ["qwen"],
        "wechat_accounts": ["Alibaba_Cloud"],
        "aliases": ["qwen", "通义千问", "qwen2.5", "qwen-vl", "qwq"],
        "notes": "Alibaba Cloud Tongyi Lab / Qwen foundation models",
    },
    {
        "name": "Zhipu AI",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["THUDM", "ZhipuAI"],
        "github_orgs": ["THUDM", "zai-org"],
        "modelscope_ids": ["ZhipuAI"],
        "wechat_accounts": ["ZhipuAI"],
        "aliases": ["zhipu", "智谱", "glm-4", "chatglm", "cogview", "cogvlm"],
        "notes": "Tsinghua spin-off / GLM foundation models",
    },
    {
        "name": "Moonshot AI",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["moonshotai"],
        "github_orgs": ["MoonshotAI"],
        "modelscope_ids": ["moonshotai"],
        "wechat_accounts": ["MoonshotAI"],
        "aliases": ["moonshot", "月之暗面", "kimi"],
        "notes": "Long-context reasoning pioneer / Kimi model family",
    },
    {
        "name": "MiniMax",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["MiniMaxAI"],
        "github_orgs": ["MiniMax-AI"],
        "modelscope_ids": ["MiniMax"],
        "wechat_accounts": ["MiniMax"],
        "aliases": ["minimax", "名之梦", "abab", "minimax-text"],
        "notes": "Frontier multimodal & MoE foundation models",
    },
    {
        "name": "StepFun",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["stepfun-ai"],
        "github_orgs": ["stepfun-ai"],
        "modelscope_ids": ["stepfun-ai"],
        "wechat_accounts": ["StepFun"],
        "aliases": ["stepfun", "阶跃星辰", "step-1", "step-2"],
        "notes": "Step series multimodal and reasoning models",
    },
    {
        "name": "ByteDance Seed",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["ByteDance"],
        "github_orgs": ["bytedance"],
        "modelscope_ids": ["ByteDance"],
        "wechat_accounts": ["ByteDance"],
        "aliases": ["bytedance", "字节跳动", "doubao", "豆包", "seed-tts"],
        "notes": "ByteDance AI Lab / Doubao foundation models",
    },
    {
        "name": "Tencent Hunyuan",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["tencent"],
        "github_orgs": ["Tencent"],
        "modelscope_ids": ["Tencent-Hunyuan"],
        "wechat_accounts": ["Tencent"],
        "aliases": ["hunyuan", "混元", "tencent hunyuan"],
        "notes": "Tencent Hunyuan foundation models & HunyuanDiT",
    },
    {
        "name": "Baidu",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["baidu"],
        "github_orgs": ["PaddlePaddle", "baidu"],
        "modelscope_ids": ["baidu"],
        "wechat_accounts": ["Baidu"],
        "aliases": ["baidu", "百度", "ernie", "文心一言", "paddlepaddle"],
        "notes": "Baidu Ernie foundation models & PaddlePaddle framework",
    },
    {
        "name": "Huawei",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["Huawei", "Noah-Ark"],
        "github_orgs": ["huawei-noah"],
        "modelscope_ids": ["Huawei"],
        "wechat_accounts": ["Huawei"],
        "aliases": ["huawei", "华为", "pangu", "盘古", "ascend", "noah's ark"],
        "notes": "Huawei Noah's Ark Lab / Pangu foundation models & Ascend AI",
    },
    {
        "name": "iFlytek",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["iFLYTEK"],
        "github_orgs": ["iflytek"],
        "modelscope_ids": ["iFLYTEK"],
        "wechat_accounts": ["iFLYTEK"],
        "aliases": ["iflytek", "科大讯飞", "spark", "星火"],
        "notes": "iFlytek Spark cognitive foundation model family",
    },
    {
        "name": "Shanghai AI Lab",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["internlm", "Shanghai_AI_Laboratory"],
        "github_orgs": ["InternLM"],
        "modelscope_ids": ["Shanghai_AI_Laboratory"],
        "wechat_accounts": ["Shanghai_AI_Laboratory"],
        "aliases": ["shanghai ai lab", "上海人工智能实验室", "internlm", "书生", "lmdeploy"],
        "notes": "Shanghai Artificial Intelligence Laboratory / InternLM ecosystem",
    },
    {
        "name": "01.AI",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["01-ai"],
        "github_orgs": ["01-ai"],
        "modelscope_ids": ["01ai"],
        "wechat_accounts": ["01ai"],
        "aliases": ["01.ai", "01-ai", "零一万物", "yi-", "yi-34b", "yi-lightning"],
        "notes": "Kai-Fu Lee founded frontier lab / Yi foundation models",
    },
]


def detect_entry_lab(
    title: str,
    summary: str,
    url: str,
    metadata: dict[str, Any] | None,
    labs: Sequence[Lab | LabModel],
) -> Lab | LabModel | None:
    """
    Match an entry against registered Frontier AI labs based on:
    1. Repository / organization metadata (Hugging Face, GitHub, ModelScope)
    2. URL path slugs
    3. Title and summary token matching
    """
    meta = metadata or {}
    text_content = f"{title} {summary}".lower()
    url_lower = (url or "").lower()

    # 1. Direct metadata matching (author, org, repo slugs)
    author = str(meta.get("author") or "").lower().strip()
    org = str(meta.get("org") or "").lower().strip()
    repo_id = str(meta.get("hf_repo") or meta.get("github_repo") or "").lower().strip()

    for lab in labs:
        hf_orgs = [o.lower() for o in (lab.hf_orgs or [])]
        gh_orgs = [o.lower() for o in (lab.github_orgs or [])]
        ms_ids = [o.lower() for o in (lab.modelscope_ids or [])]

        if author and (author in hf_orgs or author in gh_orgs or author in ms_ids):
            return lab
        if org and (org in hf_orgs or org in gh_orgs or org in ms_ids):
            return lab
        for target_org in hf_orgs + gh_orgs + ms_ids:
            if repo_id and repo_id.startswith(f"{target_org}/"):
                return lab
            if f"/{target_org}/" in url_lower:
                return lab

    # 2. Text / Title alias matching with word boundaries
    for lab in labs:
        aliases = [lab.name.lower()] + [a.lower() for a in (lab.aliases or [])]
        for alias in aliases:
            if not alias or len(alias) < 2:
                continue
            # Use word boundary or exact match
            escaped = re.escape(alias)
            # Support Chinese characters without word boundary requirements
            if any("\u4e00" <= char <= "\u9fff" for char in alias):
                if alias in text_content:
                    return lab
            else:
                pattern = rf"(?:\b|_){escaped}(?:\b|_)"
                if re.search(pattern, text_content, re.IGNORECASE) or re.search(
                    pattern, url_lower, re.IGNORECASE
                ):
                    return lab

    return None


class CoverageService:
    """Service generating regional intelligence share and per-lab coverage metrics."""

    async def ensure_seeded_labs(self, session: AsyncSession) -> int:
        """Seed default 13 verified frontier AI labs if labs table is empty."""
        count_res = await session.execute(select(func.count(LabModel.id)))
        count = count_res.scalar_one() or 0
        if count > 0:
            return 0

        inserted = 0
        for lab_data in DEFAULT_FRONTIER_LABS:
            lab_model = LabModel(
                id=str(uuid4()),
                name=lab_data["name"],
                region=lab_data["region"],
                country=lab_data["country"],
                hf_orgs=lab_data["hf_orgs"],
                github_orgs=lab_data["github_orgs"],
                modelscope_ids=lab_data["modelscope_ids"],
                wechat_accounts=lab_data["wechat_accounts"],
                aliases=lab_data["aliases"],
                notes=lab_data["notes"],
            )
            session.add(lab_model)
            inserted += 1

        await session.flush()
        return inserted

    async def backfill_entry_labs(
        self, session: AsyncSession, limit: int = 2000
    ) -> int:
        """Tag untagged database entries with matching lab_id and subject_region."""
        labs_res = await session.execute(select(LabModel))
        labs = list(labs_res.scalars().all())
        if not labs:
            await self.ensure_seeded_labs(session)
            labs_res = await session.execute(select(LabModel))
            labs = list(labs_res.scalars().all())
            if not labs:
                return 0

        entries_res = await session.execute(
            select(EntryModel)
            .where(EntryModel.lab_id.is_(None))
            .where(EntryModel.is_purged.is_(False))
            .order_by(EntryModel.published_at.desc())
            .limit(limit)
        )
        entries = list(entries_res.scalars().all())
        tagged_count = 0

        for entry in entries:
            matched_lab = detect_entry_lab(
                title=entry.title,
                summary=entry.summary,
                url=entry.url,
                metadata=entry.extra_metadata,
                labs=labs,
            )
            if matched_lab:
                entry.lab_id = str(matched_lab.id)
                entry.subject_region = matched_lab.region
                tagged_count += 1

        if tagged_count > 0:
            await session.flush()
        return tagged_count

    async def generate_coverage_report(
        self,
        session: AsyncSession,
        target_region: str | None = None,
        now: datetime | None = None,
        auto_backfill: bool = True,
    ) -> dict[str, Any]:
        """
        Generate complete coverage report per region, per lab, and identify gap lists.
        """
        ref_now = now or datetime.now(UTC)
        if ref_now.tzinfo is None:
            ref_now = ref_now.replace(tzinfo=UTC)

        cutoff_7d = ref_now - timedelta(days=7)
        cutoff_30d = ref_now - timedelta(days=30)
        cutoff_30d_naive = cutoff_30d.replace(tzinfo=None)

        if auto_backfill:
            try:
                await self.backfill_entry_labs(session, limit=2000)
            except Exception as e:
                logger.debug(f"Auto-backfill skipped or encountered: {e}")

        # ── 1. Fetch Sources & Group by Region ─────────────────────────────────
        sources_res = await session.execute(
            select(SourceModel).where(SourceModel.enabled.is_(True))
        )
        sources = list(sources_res.scalars().all())

        # Check if source_health table exists to count healthy sources
        healthy_sources_set: set[str] = set()
        try:
            health_stmt = text(
                "SELECT source_id, state FROM source_health WHERE state = 'OK'"
            )
            health_res = await session.execute(health_stmt)
            healthy_sources_set = {row[0] for row in health_res.fetchall()}
        except Exception:
            # Fallback: sources with successful fetch or active
            for s in sources:
                if s.last_status == "success":
                    healthy_sources_set.add(s.id)

        regional_sources: dict[str, list[SourceModel]] = {}
        for s in sources:
            reg = ((s.config or {}).get("region") or "global").lower().strip()
            regional_sources.setdefault(reg, []).append(s)

        total_sources_count = len(sources) or 1

        # ── 2. Query Entries for Volume Metrics ────────────────────────────────
        all_entries_res = await session.execute(
            select(EntryModel)
            .where(EntryModel.is_purged.is_(False))
            .where(
                or_(
                    EntryModel.published_at >= cutoff_30d,
                    EntryModel.published_at >= cutoff_30d_naive,
                    EntryModel.fetched_at >= cutoff_30d,
                    EntryModel.fetched_at >= cutoff_30d_naive,
                )
            )
        )
        entries_30d = list(all_entries_res.scalars().all())
        total_entries_30d = len(entries_30d) or 1

        # ── 3. Build Per-Region Telemetry ─────────────────────────────────────
        all_regions = sorted(
            set(regional_sources.keys()).union(
                {"china", "us", "europe", "apac", "global"}
            )
        )

        region_reports: list[dict[str, Any]] = []
        for reg in all_regions:
            reg_sources = regional_sources.get(reg, [])
            reg_source_ids = {s.id for s in reg_sources}
            src_count = len(reg_sources)
            healthy_count = sum(1 for s in reg_sources if s.id in healthy_sources_set)

            # Entries from publishers located in this region
            publisher_entries = [e for e in entries_30d if e.source_id in reg_source_ids]
            # Entries where subject is about a lab in this region
            subject_entries = [
                e
                for e in entries_30d
                if (e.subject_region and e.subject_region.lower() == reg)
            ]

            # Combined total coverage entries (union)
            union_entries = list({e.id: e for e in (publisher_entries + subject_entries)}.values())
            entries_count_30d = len(union_entries)

            # 7-day entries count
            entries_count_7d = len(
                [
                    e
                    for e in union_entries
                    if (
                        e.published_at
                        and (
                            (e.published_at.replace(tzinfo=UTC) if e.published_at.tzinfo is None else e.published_at)
                            >= cutoff_7d
                        )
                    )
                ]
            )

            src_share_pct = round((src_count / total_sources_count) * 100.0, 1)
            entry_share_pct = round((entries_count_30d / total_entries_30d) * 100.0, 1)
            share_diff = round(entry_share_pct - src_share_pct, 1)

            region_reports.append(
                {
                    "region": reg,
                    "sources_configured": src_count,
                    "sources_healthy": healthy_count,
                    "source_share_pct": src_share_pct,
                    "entries_7d": entries_count_7d,
                    "entries_30d": entries_count_30d,
                    "entry_share_pct": entry_share_pct,
                    "share_differential": share_diff,
                    "publisher_entries_30d": len(publisher_entries),
                    "subject_entries_30d": len(subject_entries),
                }
            )

        # ── 4. Build Per-Lab Telemetry ─────────────────────────────────────────
        labs_stmt = select(LabModel).order_by(LabModel.name)
        if target_region:
            labs_stmt = labs_stmt.where(
                func.lower(LabModel.region) == target_region.lower().strip()
            )
        labs_res = await session.execute(labs_stmt)
        labs = list(labs_res.scalars().all())

        # Map source_id to source_name for attribution
        source_name_map = {s.id: s.name for s in sources}

        lab_reports: list[dict[str, Any]] = []
        inactive_labs: list[dict[str, str]] = []

        for lab in labs:
            lab_entries = [e for e in entries_30d if e.lab_id == lab.id]
            count_30d = len(lab_entries)

            # Distinct feeding sources
            feeding_sources = sorted(
                {
                    source_name_map.get(e.source_id, "Unknown Source")
                    for e in lab_entries
                }
            )

            # Last seen entry date
            last_entry_at: str | None = None
            if lab_entries:
                max_dt = max(
                    (e.published_at for e in lab_entries if e.published_at),
                    default=None,
                )
                if max_dt:
                    last_entry_at = max_dt.isoformat()

            status = "ACTIVE" if count_30d > 0 else "GAP"
            report_item = {
                "id": lab.id,
                "name": lab.name,
                "region": lab.region,
                "country": lab.country,
                "entries_30d": count_30d,
                "last_entry_at": last_entry_at,
                "feeding_sources": feeding_sources,
                "status": status,
            }
            lab_reports.append(report_item)

            if count_30d == 0:
                inactive_labs.append(
                    {
                        "name": lab.name,
                        "region": lab.region,
                        "country": lab.country,
                        "details": f"Zero entries detected in the last 30 days ({len(lab.hf_orgs or [])} HF orgs, {len(lab.github_orgs or [])} GH orgs configured).",
                    }
                )

        # ── 5. Gap List: Zero-Yield Enabled Sources ───────────────────────────
        active_source_ids = {e.source_id for e in entries_30d}
        zero_yield_sources: list[dict[str, Any]] = []

        for s in sources:
            if s.id not in active_source_ids:
                s_reg = ((s.config or {}).get("region") or "global").lower().strip()
                if not target_region or s_reg == target_region.lower().strip():
                    zero_yield_sources.append(
                        {
                            "id": s.id,
                            "name": s.name,
                            "region": s_reg,
                            "tier": s.tier,
                            "url": s.url,
                            "last_status": s.last_status,
                        }
                    )

        # ── 6. Render Copy-Pasteable Markdown Tables ──────────────────────────
        markdown_output = self._render_markdown_tables(
            region_reports=region_reports,
            lab_reports=lab_reports,
            inactive_labs=inactive_labs,
            zero_yield_sources=zero_yield_sources,
            target_region=target_region,
        )

        return {
            "generated_at": ref_now.isoformat(),
            "target_region": target_region or "all",
            "summary": {
                "total_configured_sources": len(sources),
                "total_entries_30d": len(entries_30d),
                "total_labs_monitored": len(labs),
                "active_labs_count": len([lab_rep for lab_rep in lab_reports if lab_rep["status"] == "ACTIVE"]),
                "inactive_labs_count": len(inactive_labs),
                "zero_yield_sources_count": len(zero_yield_sources),
            },
            "regions": region_reports,
            "labs": lab_reports,
            "gaps": {
                "inactive_labs": inactive_labs,
                "zero_yield_sources": zero_yield_sources,
            },
            "markdown_table": markdown_output,
            "markdown_report": markdown_output,
        }

    def _render_markdown_tables(
        self,
        region_reports: list[dict[str, Any]],
        lab_reports: list[dict[str, Any]],
        inactive_labs: list[dict[str, str]],
        zero_yield_sources: list[dict[str, Any]],
        target_region: str | None = None,
    ) -> str:
        """Render high-density, professional markdown tables for reports and briefings."""
        lines: list[str] = []

        lines.append("### AetherGuard Regional & Frontier AI Lab Coverage Report\n")

        # Table 1: Regional Source & Volume Share
        lines.append("#### 1. Regional Ecosystem Share")
        lines.append(
            "| Region | Configured Sources | Healthy Sources | Source Share | 7d Entries | 30d Entries | Coverage Share | Net Differential |"
        )
        lines.append(
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
        )
        for r in region_reports:
            diff_str = (
                f"+{r['share_differential']}%"
                if r["share_differential"] > 0
                else f"{r['share_differential']}%"
            )
            lines.append(
                f"| **{r['region'].upper()}** | {r['sources_configured']} | {r['sources_healthy']} | "
                f"{r['source_share_pct']}% | {r['entries_7d']} | {r['entries_30d']} | "
                f"{r['entry_share_pct']}% | `{diff_str}` |"
            )
        lines.append("")

        # Table 2: Frontier AI Lab Intelligence Coverage
        filter_str = f" ({target_region.upper()})" if target_region else ""
        lines.append(f"#### 2. Frontier AI Lab Coverage{filter_str}")
        lines.append(
            "| Lab Name | Region | 30d Entries | Last Seen | Feeding Intelligence Sources | Status |"
        )
        lines.append(
            "| :--- | :---: | :---: | :---: | :--- | :---: |"
        )
        for lab in lab_reports:
            last_seen = (
                lab["last_entry_at"][:10] if lab["last_entry_at"] else "Never"
            )
            sources_preview = (
                ", ".join(lab["feeding_sources"][:3])
                + (f" (+{len(lab['feeding_sources']) - 3} more)" if len(lab["feeding_sources"]) > 3 else "")
                if lab["feeding_sources"]
                else "—"
            )
            status_badge = (
                "`ACTIVE`" if lab["status"] == "ACTIVE" else "**`GAP`**"
            )
            lines.append(
                f"| **{lab['name']}** | {lab['region'].upper()} | {lab['entries_30d']} | "
                f"{last_seen} | {sources_preview} | {status_badge} |"
            )
        lines.append("")

        # Table 3: Gaps & Blind Spots
        lines.append("#### 3. Intelligence Blind Spots & Gaps")
        if not inactive_labs and not zero_yield_sources:
            lines.append("*No coverage gaps detected. All monitored labs and sources are active.*")
        else:
            lines.append(
                "| Gap Type | Target Identifier | Region | Diagnostic Detail |"
            )
            lines.append(
                "| :--- | :--- | :---: | :--- |"
            )
            for il in inactive_labs:
                lines.append(
                    f"| **Lab Silent** | {il['name']} | {il['region'].upper()} | {il['details']} |"
                )
            for zs in zero_yield_sources[:15]:
                lines.append(
                    f"| **Source Idle** | {zs['name']} | {zs['region'].upper()} | 0 entries yielded in last 30 days (T{zs['tier']:.1f}). |"
                )
            if len(zero_yield_sources) > 15:
                lines.append(
                    f"| *...and {len(zero_yield_sources) - 15} more idle sources* | — | — | — |"
                )

        return "\n".join(lines)


coverage_service = CoverageService()
