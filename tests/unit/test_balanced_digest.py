"""Unit tests for BalancedDigestService."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ai_security_monitor.application.services.balanced_digest import (
    BalancedDigestService,
    CategoryQuota,
)
from ai_security_monitor.domain.entities import Category, Entry


def make_entry(
    title: str,
    category: Category,
    score: int = 50,
    source_name: str | None = None,
    source_tier: float | None = None,
    source_id: Any | None = None,
) -> Entry:
    metadata: dict[str, Any] = {"priority_score": score}
    if source_name is not None:
        metadata["source_name"] = source_name
    if source_tier is not None:
        metadata["source_tier"] = source_tier

    return Entry(
        id=uuid4(),
        source_id=source_id or uuid4(),
        title=title,
        url=f"https://example.com/{title.replace(' ', '_')}",
        content_hash=f"hash_{title}",
        summary=f"Summary of {title}",
        published_at=datetime.now(UTC),
        category=category,
        metadata=metadata,
    )


def test_balanced_digest_enforces_category_quotas():
    """BalancedDigestService should cap over-represented categories and preserve diversity."""
    quotas = [
        CategoryQuota(name="Models", limit=2, categories=["ai_models"]),
        CategoryQuota(name="Papers", limit=2, categories=["ai_research"]),
        CategoryQuota(name="Repos", limit=2, categories=["github_trending"]),
    ]
    service = BalancedDigestService(quotas=quotas, max_total_items=10)

    # 10 repos, 1 model, 1 paper
    entries = [
        make_entry(f"Repo {i}", Category.GITHUB_TRENDING, score=100 - i)
        for i in range(10)
    ]
    entries.append(make_entry("Paper Alpha", Category.AI_RESEARCH, score=90))
    entries.append(make_entry("Model Omega", Category.AI_MODELS, score=95))

    # Sort descending by priority score
    result = service.balance(
        entries, sort_key=lambda e: e.metadata.get("priority_score", 0)
    )

    assert result.total_eligible == 12
    # Only 2 repos should be selected (quota=2), plus 1 model and 1 paper = 4 total
    assert result.total_selected == 4
    assert result.group_counts["Repos"] == 2
    assert result.group_counts["Models"] == 1
    assert result.group_counts["Papers"] == 1
    assert result.dropped_count == 8


def test_balanced_digest_empty_input():
    service = BalancedDigestService()
    result = service.balance([])
    assert result.total_selected == 0
    assert result.items == []


def test_balanced_digest_default_quotas_caps_source_spam():
    """Verify that default quotas cap any single category at default limit (5) and preserve all pillars."""
    service = BalancedDigestService(max_total_items=25)

    entries = [
        make_entry(f"Spam Repo {i}", Category.GITHUB_TRENDING, score=100)
        for i in range(20)
    ]
    entries.extend(
        [
            make_entry(f"Frontier Model {i}", Category.AI_MODELS, score=80)
            for i in range(5)
        ]
    )
    entries.extend(
        [
            make_entry(f"Research Paper {i}", Category.AI_RESEARCH, score=70)
            for i in range(5)
        ]
    )

    result = service.balance(entries)
    assert result.total_eligible == 30
    assert result.total_selected == 15
    assert result.group_counts["Trending Codebases & Runtimes"] == 5
    assert result.group_counts["Frontier Models & Weights"] == 5
    assert result.group_counts["Research Breakthroughs"] == 5
    assert result.dropped_count == 15


def test_balanced_digest_tiered_credibility_gates():
    """Verify tiered credibility gates: T1 (55), T1.5 (65), T2 (70)."""
    service = BalancedDigestService(max_total_items=10)

    t1_pass = make_entry("T1 Pass", Category.AI_MODELS, score=55, source_tier=1.0)
    t1_fail = make_entry("T1 Fail", Category.AI_MODELS, score=54, source_tier=1.0)
    t15_pass = make_entry("T1.5 Pass", Category.AI_RESEARCH, score=65, source_tier=1.5)
    t15_fail = make_entry("T1.5 Fail", Category.AI_RESEARCH, score=64, source_tier=1.5)
    t2_pass = make_entry("T2 Pass", Category.GITHUB_TRENDING, score=70, source_tier=2.0)
    t2_fail = make_entry("T2 Fail", Category.GITHUB_TRENDING, score=69, source_tier=2.0)

    result = service.balance([t1_pass, t1_fail, t15_pass, t15_fail, t2_pass, t2_fail])

    assert result.total_eligible == 6
    assert result.total_selected == 3
    assert result.dropped_by_tier == 3
    selected_titles = {e.title for e in result.items}
    assert selected_titles == {"T1 Pass", "T1.5 Pass", "T2 Pass"}


def test_balanced_digest_unassigned_source_defaults_to_t2():
    """Unassigned or unrecognized sources must strictly default to Tier 2 (threshold 70)."""
    service = BalancedDigestService(max_total_items=10)

    # No tier in metadata, source name not in config -> defaults to 2.0 (requires 70)
    unassigned_pass = make_entry("Unknown Pass", Category.AI_MODELS, score=70)
    unassigned_fail = make_entry("Unknown Fail", Category.AI_MODELS, score=69)

    result = service.balance([unassigned_pass, unassigned_fail])
    assert result.total_eligible == 2
    assert result.total_selected == 1
    assert result.items[0].title == "Unknown Pass"
    assert result.dropped_by_tier == 1


def test_balanced_digest_per_source_cap_enforcement():
    """Verify per-source capping limits high-frequency feeds to max_items_per_source (default 2)."""
    service = BalancedDigestService(max_total_items=10, max_items_per_source=2)

    # 5 items from the exact same source, all passing gate with score 90
    deepseek_entries = [
        make_entry(
            f"DeepSeek Release {i}",
            Category.AI_MODELS,
            score=95 - i,
            source_name="DeepSeek Releases",
            source_tier=1.0,
        )
        for i in range(5)
    ]
    # 2 items from another source
    mistral_entries = [
        make_entry(
            f"Mistral Release {i}",
            Category.AI_MODELS,
            score=85 - i,
            source_name="Mistral Releases",
            source_tier=1.0,
        )
        for i in range(2)
    ]

    result = service.balance(
        deepseek_entries + mistral_entries,
        sort_key=lambda e: e.metadata.get("priority_score", 0),
    )

    # DeepSeek had 5, should be capped at 2
    assert result.source_counts["DeepSeek Releases"] == 2
    # Mistral had 2, should have 2
    assert result.source_counts["Mistral Releases"] == 2
    assert result.total_selected == 4
    assert result.dropped_by_source_cap == 3
    assert result.dropped_count == 3


def test_balanced_digest_diagnostics_tracking():
    """Verify diagnostic counters accurately differentiate drops between tier, source cap, and category quotas."""
    quotas = [CategoryQuota(name="Models", limit=2, categories=["ai_models"])]
    service = BalancedDigestService(
        quotas=quotas, max_total_items=10, max_items_per_source=2
    )

    # 1 item dropped by tier (T2 score 50 < 70)
    tier_dropped = make_entry(
        "Tier Drop", Category.AI_MODELS, score=50, source_name="Feed A", source_tier=2.0
    )
    # 3 items from Feed B (T1 score 80 >= 55). Cap is 2 -> 1 dropped by source cap
    feed_b = [
        make_entry(
            f"Feed B Item {i}",
            Category.AI_MODELS,
            score=80,
            source_name="Feed B",
            source_tier=1.0,
        )
        for i in range(3)
    ]
    # 2 items from Feed C (T1 score 75 >= 55). But quota for Models is 2 (already filled by Feed B 2 items) -> dropped by quota
    feed_c = [
        make_entry(
            f"Feed C Item {i}",
            Category.AI_MODELS,
            score=75,
            source_name="Feed C",
            source_tier=1.0,
        )
        for i in range(2)
    ]

    result = service.balance(
        [tier_dropped] + feed_b + feed_c,
        sort_key=lambda e: e.metadata.get("priority_score", 0),
    )

    assert result.total_eligible == 6
    assert result.total_selected == 2
    assert result.dropped_by_tier == 1
    assert result.dropped_by_source_cap == 1
    assert result.dropped_by_quota == 2
    assert result.dropped_count == 4
    assert result.tier_counts[1.0] == 2
    assert result.source_counts["Feed B"] == 2
