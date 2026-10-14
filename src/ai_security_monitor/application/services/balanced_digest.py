"""
Balanced Digest Service.
Enforces category group quotas and limits across intelligence feeds to prevent
single-source domination and maintain editorial balance across all AI pillars.
Inspired by Horizon's Balanced Digest architecture.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry

logger = get_logger(__name__)


@dataclass
class CategoryQuota:
    """Quota limit configuration for a group of categories."""

    name: str
    limit: int
    categories: list[str]


@dataclass
class BalancedDigestResult:
    """Result of balanced selection across intelligence pillars."""

    items: list[Entry]
    total_eligible: int
    total_selected: int
    group_counts: dict[str, int] = field(default_factory=dict)
    group_limits: dict[str, int] = field(default_factory=dict)
    dropped_count: int = 0


DEFAULT_CATEGORY_QUOTAS = [
    CategoryQuota(
        name="Frontier Models & Weights",
        limit=5,
        categories=[Category.AI_MODELS.value, "ai_models"],
    ),
    CategoryQuota(
        name="Research Breakthroughs",
        limit=5,
        categories=[Category.AI_RESEARCH.value, "ai_research"],
    ),
    CategoryQuota(
        name="Trending Codebases & Runtimes",
        limit=5,
        categories=[Category.GITHUB_TRENDING.value, "github_trending"],
    ),
    CategoryQuota(
        name="Developer Tooling & Infrastructure",
        limit=5,
        categories=[Category.CYBER_TOOLS.value, "cyber_tools"],
    ),
    CategoryQuota(
        name="Global AI Ecosystem & Corridors",
        limit=5,
        categories=[Category.AI_TECH.value, "ai_tech"],
    ),
]


class BalancedDigestService:
    """Balances items across category groups using configurable limits."""

    def __init__(
        self,
        quotas: list[CategoryQuota] | None = None,
        max_total_items: int = 25,
        default_limit: int = 3,
    ):
        self.quotas = quotas or DEFAULT_CATEGORY_QUOTAS
        self.max_total_items = max_total_items
        self.default_limit = default_limit

        # Fast lookup from category string to group
        self._category_to_quota: dict[str, CategoryQuota] = {}
        for q in self.quotas:
            for cat in q.categories:
                self._category_to_quota[cat.lower()] = q

    def balance(
        self, entries: list[Entry], sort_key: Any = None
    ) -> BalancedDigestResult:
        """Filter and balance entries according to category group quotas.

        Assumes entries are already sorted by priority/velocity descending,
        or accepts a custom sort key.
        """
        if not entries:
            return BalancedDigestResult(items=[], total_eligible=0, total_selected=0)

        sorted_items = list(entries)
        if sort_key:
            sorted_items.sort(key=sort_key, reverse=True)

        group_counts: dict[str, int] = defaultdict(int)
        group_limits: dict[str, int] = {q.name: q.limit for q in self.quotas}
        group_limits["Other"] = self.default_limit

        selected: list[Entry] = []
        dropped = 0

        for item in sorted_items:
            cat_str = (
                item.category.value
                if hasattr(item.category, "value")
                else str(item.category)
            ).lower()

            quota = self._category_to_quota.get(cat_str)
            group_name = quota.name if quota else "Other"
            limit = group_limits.get(group_name, self.default_limit)

            if (
                group_counts[group_name] < limit
                and len(selected) < self.max_total_items
            ):
                selected.append(item)
                group_counts[group_name] += 1
            else:
                dropped += 1

        logger.info(
            f"Balanced digest selected {len(selected)} items out of {len(entries)} (dropped {dropped} for quota limits)"
        )

        return BalancedDigestResult(
            items=selected,
            total_eligible=len(entries),
            total_selected=len(selected),
            group_counts=dict(group_counts),
            group_limits=group_limits,
            dropped_count=dropped,
        )


balanced_digest_service = BalancedDigestService()
