"""
No-Slop Ingestion Filter Service.
Drops low-value aggregate noise, roundups, promotional clickbait, and unwanted topics
before they enter the database or downstream analysis pipelines.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_security_monitor.infrastructure.database.models import FilteredEntryModel

logger = logging.getLogger(__name__)


class FilterReason:
    """Canonical classification reasons for rejected slop entries."""

    ROUNDUP = "roundup"
    PROMOTIONAL = "promotional"
    AGGREGATOR_LAUNCH = "aggregator_launch"
    SOCIAL_REACTION = "social_reaction"
    SECURITY_CVE_OMITTED = "security_cve_omitted"


@dataclass(frozen=True)
class FilterDecision:
    """Evaluation result for a content item."""

    is_slop: bool
    reason: str | None = None
    matched_pattern: str | None = None


# Compiled Regex Rules for High-Throughput Stream Ingestion
ROUNDUP_PATTERNS = [
    re.compile(
        r"\b(top\s+\d+|best\s+ai\s+tools|weekly\s+digest|newsletter\s*#?\d*|roundup|what\s+happened\s+in\s+ai\s+this\s+week|this\s+week\s+in\s+ai|ai\s+news\s+roundup|weekly\s+recap|daily\s+roundup)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d+\s+ai\s+tools\s+you\s+need|tools\s+of\s+the\s+week|ai\s+bulletin|weekly\s+ai\s+summary)\b",
        re.IGNORECASE,
    ),
]

PROMOTIONAL_PATTERNS = [
    re.compile(
        r"\b(how\s+to\s+use\s+.+\s+to\s+make\s+money|make\s+\$?\d+k?\s+with\s+ai|save\s+\d+\s+hours\s+with|the\s+future\s+of\s+.+\s+is\s+here|10x\s+your\s+.+\s+with\s+ai|monetize\s+ai|passive\s+income\s+with\s+ai)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(cheat\s+sheet\s+for\s+ai|prompts\s+you\s+must\s+try|get\s+rich\s+with\s+ai|ultimate\s+guide\s+to\s+prompts)\b",
        re.IGNORECASE,
    ),
]

AGGREGATOR_LAUNCH_PATTERNS = [
    re.compile(
        r"\b(product\s+hunt\s+launch|launching\s+today\s+on\s+product\s+hunt|featured\s+on\s+product\s+hunt|check\s+us\s+out\s+on\s+product\s+hunt)\b",
        re.IGNORECASE,
    ),
]

SOCIAL_REACTION_PATTERNS = [
    re.compile(
        r"\b(reddit\s+reacts\s+to|twitter\s+reacts\s+to|x\s+reacts\s+to|the\s+internet\s+reacts\s+to|people\s+are\s+furious\s+about|community\s+reacts|devs\s+are\s+going\s+crazy\s+over)\b",
        re.IGNORECASE,
    ),
]

# Strict User Directive: DO NOT focus on cybersecurity, CVEs, or vulnerability threat intelligence
SECURITY_OMITTED_PATTERNS = [
    re.compile(
        r"\b(cve-\d{4}-\d+|zero-day\s+exploit|ransomware|malware\s+analysis|penetration\s+testing|sql\s+injection|privilege\s+escalation\s+exploit)\b",
        re.IGNORECASE,
    ),
]

ALLOWED_PRIMARY_LABS = {
    "deepseek",
    "qwen",
    "alibaba",
    "zhipu",
    "moonshot",
    "kimi",
    "minimax",
    "stepfun",
    "bytedance",
    "tencent",
    "baidu",
    "huawei",
    "iflytek",
    "shanghai ai lab",
    "internlm",
    "01.ai",
    "yi",
    "anthropic",
    "claude",
    "openai",
    "mistral",
    "meta llama",
    "google deepmind",
}


class NoSlopFilterService:
    """Service evaluating and enforcing no-slop ingestion hygiene."""

    def evaluate(self, title: str, summary: str = "", url: str = "") -> FilterDecision:
        """
        Evaluate candidate intelligence against deterministic no-slop rules.
        """
        text = f"{title} {summary}".strip()

        # 1. Check Cybersecurity / CVE Omission Rule (User Mandate)
        for pattern in SECURITY_OMITTED_PATTERNS:
            match = pattern.search(text)
            if match:
                return FilterDecision(
                    is_slop=True,
                    reason=FilterReason.SECURITY_CVE_OMITTED,
                    matched_pattern=match.group(0),
                )

        # 2. Check Roundups & Aggregate Summaries
        for pattern in ROUNDUP_PATTERNS:
            match = pattern.search(text)
            if match:
                return FilterDecision(
                    is_slop=True,
                    reason=FilterReason.ROUNDUP,
                    matched_pattern=match.group(0),
                )

        # 3. Check Promotional Clickbait
        for pattern in PROMOTIONAL_PATTERNS:
            match = pattern.search(text)
            if match:
                return FilterDecision(
                    is_slop=True,
                    reason=FilterReason.PROMOTIONAL,
                    matched_pattern=match.group(0),
                )

        # 4. Check Social Reactions without Technical Substance
        for pattern in SOCIAL_REACTION_PATTERNS:
            match = pattern.search(text)
            if match:
                return FilterDecision(
                    is_slop=True,
                    reason=FilterReason.SOCIAL_REACTION,
                    matched_pattern=match.group(0),
                )

        # 5. Check Aggregator / Product Hunt Spam (unless from verified primary lab)
        for pattern in AGGREGATOR_LAUNCH_PATTERNS:
            match = pattern.search(text)
            if match:
                text_lower = text.lower()
                is_whitelisted_lab = any(
                    lab in text_lower for lab in ALLOWED_PRIMARY_LABS
                )
                if not is_whitelisted_lab:
                    return FilterDecision(
                        is_slop=True,
                        reason=FilterReason.AGGREGATOR_LAUNCH,
                        matched_pattern=match.group(0),
                    )

        return FilterDecision(is_slop=False)

    async def record_filtered_item(
        self,
        session: AsyncSession,
        source_id: str,
        source_name: str,
        title: str,
        url: str,
        decision: FilterDecision,
    ) -> FilteredEntryModel:
        """Record dropped entry into the 7-day inspection audit trail."""
        model = FilteredEntryModel(
            id=str(uuid4()),
            source_id=source_id,
            source_name=source_name,
            title=title[:500],
            url=url,
            reason=decision.reason or "unknown",
            matched_pattern=decision.matched_pattern,
            filtered_at=datetime.now(UTC),
        )
        session.add(model)
        return model

    async def get_filter_log(
        self,
        session: AsyncSession,
        limit: int = 100,
        reason: str | None = None,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve recent filtered items for human audit."""
        stmt = (
            select(FilteredEntryModel)
            .order_by(FilteredEntryModel.filtered_at.desc())
            .limit(limit)
        )
        if reason:
            stmt = stmt.where(FilteredEntryModel.reason == reason.strip())
        if source_id:
            stmt = stmt.where(FilteredEntryModel.source_id == source_id.strip())

        res = await session.execute(stmt)
        items = res.scalars().all()
        return [
            {
                "id": item.id,
                "source_id": item.source_id,
                "source_name": item.source_name,
                "title": item.title,
                "url": item.url,
                "reason": item.reason,
                "matched_pattern": item.matched_pattern,
                "filtered_at": item.filtered_at.isoformat()
                if item.filtered_at
                else None,
            }
            for item in items
        ]

    async def get_filter_stats(self, session: AsyncSession) -> dict[str, Any]:
        """Get aggregate metrics on filtered slop."""
        # By reason
        reason_stmt = select(
            FilteredEntryModel.reason, func.count(FilteredEntryModel.id)
        ).group_by(FilteredEntryModel.reason)
        reason_res = await session.execute(reason_stmt)
        by_reason = {row[0]: row[1] for row in reason_res.all()}

        # Total count
        total_stmt = select(func.count(FilteredEntryModel.id))
        total_res = await session.execute(total_stmt)
        total_count = total_res.scalar() or 0

        # Top filtered sources
        source_stmt = (
            select(FilteredEntryModel.source_name, func.count(FilteredEntryModel.id))
            .group_by(FilteredEntryModel.source_name)
            .order_by(func.count(FilteredEntryModel.id).desc())
            .limit(10)
        )
        source_res = await session.execute(source_stmt)
        top_sources = [
            {"source": row[0], "filtered_count": row[1]} for row in source_res.all()
        ]

        return {
            "total_filtered_7d": total_count,
            "by_reason": by_reason,
            "top_filtered_sources": top_sources,
        }

    async def purge_expired_filtered_entries(
        self, session: AsyncSession, days: int = 7
    ) -> int:
        """Enforce strict 7-day TTL cleanup on filtered audit log."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        cutoff_naive = cutoff.replace(tzinfo=None)

        stmt = (
            delete(FilteredEntryModel)
            .where(
                (FilteredEntryModel.filtered_at < cutoff)
                | (FilteredEntryModel.filtered_at < cutoff_naive)
            )
            .execution_options(synchronize_session=False)
        )
        res = await session.execute(stmt)
        deleted_count = res.rowcount if hasattr(res, "rowcount") else 0
        return max(0, deleted_count)


# Global singleton
no_slop_filter = NoSlopFilterService()
