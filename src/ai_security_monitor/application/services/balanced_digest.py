"""
Balanced Digest Service.
Enforces category group quotas, tiered credibility gates (T1/T1.5/T2),
and per-source caps across intelligence feeds to prevent single-source
domination and maintain editorial balance across all AI pillars.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

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
    source_counts: dict[str, int] = field(default_factory=dict)
    tier_counts: dict[float, int] = field(default_factory=dict)
    primary_count: int = 0
    primary_ratio: float = 0.0
    dropped_count: int = 0
    dropped_by_tier: int = 0
    dropped_by_source_cap: int = 0
    dropped_by_quota: int = 0


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

# Calibrated against actual score distribution in database:
# - T1 (55): Loose cut passes 99%+ of official frontier lab releases and arXiv papers
# - T1.5 (65): Balanced cut passes 90%+ of GitHub trending repos and core tooling
# - T2 (70): Strict cut passes top 25-30% of Reddit/Twitter/aggregators while rejecting hype
DEFAULT_TIER_THRESHOLDS: dict[float, int] = {
    1.0: 55,
    1.5: 65,
    2.0: 70,
}


def load_source_tier_map() -> dict[str, float]:
    """Load mapping of source name (lowercase) -> credibility tier from sources.yaml."""
    from ai_security_monitor.config.sources import load_sources

    try:
        cfg = load_sources()
        mapping: dict[str, float] = {}
        for s in cfg.sources:
            mapping[s.name.strip().lower()] = s.tier
        return mapping
    except Exception as e:
        logger.debug(f"Failed to load source tier map from config: {e}")
        return {}


class BalancedDigestService:
    """Balances items across category groups, enforces tiered credibility gates, and caps per-source volume."""

    def __init__(
        self,
        quotas: list[CategoryQuota] | None = None,
        max_total_items: int = 25,
        default_limit: int = 3,
        max_items_per_source: int = 2,
        tier_thresholds: dict[float, int] | None = None,
        source_tier_map: dict[str, float] | None = None,
        min_primary_ratio: float = 0.50,
    ):
        self.quotas = quotas or DEFAULT_CATEGORY_QUOTAS
        self.max_total_items = max_total_items
        self.default_limit = default_limit
        self.max_items_per_source = max_items_per_source
        self.tier_thresholds = tier_thresholds or dict(DEFAULT_TIER_THRESHOLDS)
        self._source_tier_map = source_tier_map
        self.min_primary_ratio = min_primary_ratio

        # Fast lookup from category string to group
        self._category_to_quota: dict[str, CategoryQuota] = {}
        for q in self.quotas:
            for cat in q.categories:
                self._category_to_quota[cat.lower()] = q

    def _get_entry_source_identifier(self, entry: Entry) -> str:
        """Derive consistent source identifier (name, UUID, or domain) for per-source capping."""
        if entry.metadata and entry.metadata.get("source_name"):
            return str(entry.metadata["source_name"]).strip()
        if entry.source_id:
            return str(entry.source_id)
        if entry.url:
            try:
                parsed = urlparse(entry.url)
                netloc = (parsed.hostname or "").lower()
                if netloc.startswith("www."):
                    netloc = netloc[4:]
                if netloc:
                    return netloc
            except Exception:
                pass
        return "unknown"

    def _get_entry_tier(self, entry: Entry) -> float:
        """Resolve credibility tier for an entry (strictly defaults to 2.0 if unassigned)."""
        # 1. Metadata on entry
        if entry.metadata:
            if "source_tier" in entry.metadata:
                try:
                    return float(entry.metadata["source_tier"])
                except (ValueError, TypeError):
                    pass
            # Check source_name against map
            src_name = entry.metadata.get("source_name")
            if src_name:
                src_key = str(src_name).strip().lower()
                if self._source_tier_map and src_key in self._source_tier_map:
                    return self._source_tier_map[src_key]

        # 2. Lazy load source tier map if not set
        if self._source_tier_map is None:
            self._source_tier_map = load_source_tier_map()
            if entry.metadata and entry.metadata.get("source_name"):
                src_key = str(entry.metadata["source_name"]).strip().lower()
                if src_key in self._source_tier_map:
                    return self._source_tier_map[src_key]

        # 3. Unassigned default: strictly Tier 2 (strictest gate)
        return 2.0

    def _get_entry_score(self, entry: Entry) -> int:
        """Extract velocity or priority score for gate evaluation."""
        if entry.analysis:
            return getattr(entry.analysis, "threat_velocity", 0)
        if entry.metadata:
            return int(
                entry.metadata.get(
                    "threat_velocity", entry.metadata.get("priority_score", 0)
                )
            )
        return 0

    def balance(
        self, entries: list[Entry], sort_key: Any = None
    ) -> BalancedDigestResult:
        """Filter and balance entries according to tier gates, source caps, and category quotas.

        Assumes entries are already sorted by priority/velocity descending,
        or accepts a custom sort key.
        Guarantees that at least min_primary_ratio (default 50%) of selected items
        are primary lab releases if sufficient primary entries are available.
        """
        if not entries:
            return BalancedDigestResult(
                items=[],
                total_eligible=0,
                total_selected=0,
                primary_count=0,
                primary_ratio=0.0,
            )

        sorted_items = list(entries)
        if sort_key:
            sorted_items.sort(key=sort_key, reverse=True)

        group_counts: dict[str, int] = defaultdict(int)
        group_limits: dict[str, int] = {q.name: q.limit for q in self.quotas}
        group_limits["Other"] = self.default_limit

        source_counts: dict[str, int] = defaultdict(int)
        tier_counts: dict[float, int] = defaultdict(int)

        def is_primary(entry: Entry) -> bool:
            return bool(
                getattr(entry, "is_primary", False)
                or (entry.metadata and entry.metadata.get("is_primary"))
            )

        dropped_by_tier = 0
        dropped_by_source_cap = 0
        dropped_by_quota = 0

        # Step 1: Pre-filter by Tier Credibility Gate
        eligible_items: list[tuple[Entry, float, str, str]] = []
        for item in sorted_items:
            tier = self._get_entry_tier(item)
            threshold = self.tier_thresholds.get(
                tier, self.tier_thresholds.get(2.0, 70)
            )
            score = self._get_entry_score(item)

            if score < threshold:
                dropped_by_tier += 1
                continue

            source_key = self._get_entry_source_identifier(item)
            cat_str = (
                item.category.value
                if hasattr(item.category, "value")
                else str(item.category)
            ).lower()
            quota = self._category_to_quota.get(cat_str)
            group_name = quota.name if quota else "Other"

            eligible_items.append((item, tier, source_key, group_name))

        selected: list[Entry] = []
        selected_ids: set[Any] = set()

        # Step 2: Phase 1 - Primary Guarantee (reserve up to min_primary_ratio for primary lab announcements)
        if self.min_primary_ratio > 0.0:
            target_primary = math.ceil(
                min(len(eligible_items), self.max_total_items) * self.min_primary_ratio
            )
            for item, tier, source_key, group_name in eligible_items:
                if len([e for e in selected if is_primary(e)]) >= target_primary:
                    break
                if not is_primary(item):
                    continue

                # Check per-source cap
                if (
                    self.max_items_per_source > 0
                    and source_counts[source_key] >= self.max_items_per_source
                ):
                    continue

                # Check category group quota
                limit = group_limits.get(group_name, self.default_limit)
                if group_counts[group_name] >= limit:
                    continue

                if len(selected) >= self.max_total_items:
                    break

                selected.append(item)
                selected_ids.add(item.id)
                group_counts[group_name] += 1
                source_counts[source_key] += 1
                tier_counts[tier] += 1

        # Step 3: Phase 2 - Fill remaining allocation from all eligible candidates in priority order
        for item, tier, source_key, group_name in eligible_items:
            if item.id in selected_ids:
                continue

            # Check per-source cap
            if (
                self.max_items_per_source > 0
                and source_counts[source_key] >= self.max_items_per_source
            ):
                dropped_by_source_cap += 1
                continue

            # Check category group quota
            limit = group_limits.get(group_name, self.default_limit)
            if group_counts[group_name] >= limit:
                dropped_by_quota += 1
                continue

            # Check total items limit
            if len(selected) >= self.max_total_items:
                dropped_by_quota += 1
                continue

            selected.append(item)
            selected_ids.add(item.id)
            group_counts[group_name] += 1
            source_counts[source_key] += 1
            tier_counts[tier] += 1

        if sort_key:
            selected.sort(key=sort_key, reverse=True)

        primary_cnt = sum(1 for e in selected if is_primary(e))
        primary_rat = round(primary_cnt / len(selected), 3) if selected else 0.0
        total_dropped = dropped_by_tier + dropped_by_source_cap + dropped_by_quota

        logger.info(
            f"Balanced digest selected {len(selected)} items out of {len(entries)} "
            f"(primary: {primary_cnt}/{len(selected)} = {primary_rat:.1%}, dropped: tier_gate={dropped_by_tier}, source_cap={dropped_by_source_cap}, quota={dropped_by_quota})"
        )

        return BalancedDigestResult(
            items=selected,
            total_eligible=len(entries),
            total_selected=len(selected),
            group_counts=dict(group_counts),
            group_limits=group_limits,
            source_counts=dict(source_counts),
            tier_counts=dict(tier_counts),
            primary_count=primary_cnt,
            primary_ratio=primary_rat,
            dropped_count=total_dropped,
            dropped_by_tier=dropped_by_tier,
            dropped_by_source_cap=dropped_by_source_cap,
            dropped_by_quota=dropped_by_quota,
        )


balanced_digest_service = BalancedDigestService()
