"""Unit tests for BalancedDigestService."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from ai_security_monitor.application.services.balanced_digest import (
    BalancedDigestService,
    CategoryQuota,
)
from ai_security_monitor.domain.entities import Category, Entry


def make_entry(title: str, category: Category, score: int = 50) -> Entry:
    return Entry(
        id=uuid4(),
        source_id=uuid4(),
        title=title,
        url=f"https://example.com/{title.replace(' ', '_')}",
        content_hash=f"hash_{title}",
        summary=f"Summary of {title}",
        published_at=datetime.now(UTC),
        category=category,
        metadata={"priority_score": score},
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
    entries.extend([
        make_entry(f"Frontier Model {i}", Category.AI_MODELS, score=80)
        for i in range(5)
    ])
    entries.extend([
        make_entry(f"Research Paper {i}", Category.AI_RESEARCH, score=70)
        for i in range(5)
    ])

    result = service.balance(entries)
    assert result.total_eligible == 30
    assert result.total_selected == 15
    assert result.group_counts["Trending Codebases & Runtimes"] == 5
    assert result.group_counts["Frontier Models & Weights"] == 5
    assert result.group_counts["Research Breakthroughs"] == 5
    assert result.dropped_count == 15

