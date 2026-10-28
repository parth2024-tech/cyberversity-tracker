"""
Unit tests for Custom Watchlist Rules and Threat Hunting.
"""

from datetime import datetime
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import Analysis, AnalysisModel, Category, Entry
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.domain.watchlist import WatchlistRule


def test_watchlist_rule_keyword_matching():
    rule = WatchlistRule(
        name="DeepSeek / vLLM Watchlist",
        keywords=["deepseek", "vllm", "lcel"],
        enabled=True,
    )

    entry1 = Entry(
        source_id=uuid4(),
        title="Novel DeepSeek-V3 jailbreak technique discovered",
        url="https://example.com/deepseek-exploit",
        content_hash="hash1",
        category=Category.AI_RESEARCH,
        summary="Researchers demonstrated prompt leaking on DeepSeek MoE architecture.",
        published_at=datetime.utcnow(),
    )

    entry2 = Entry(
        source_id=uuid4(),
        title="Unrelated standard kernel vulnerability",
        url="https://example.com/kernel",
        content_hash="hash2",
        category=Category.CYBERSECURITY,
        summary="Buffer overflow in older Linux kernel module.",
        published_at=datetime.utcnow(),
    )

    assert rule.matches(entry1) is True
    assert rule.matches(entry2) is False


def test_watchlist_rule_category_and_velocity_constraints():
    rule = WatchlistRule(
        name="Critical CVEs only",
        keywords=["pytorch"],
        categories=[Category.VULNERABILITIES],
        min_threat_velocity=70,
        enabled=True,
    )

    # Low velocity or wrong category -> False
    entry_wrong_cat = Entry(
        source_id=uuid4(),
        title="PyTorch 2.5 general release notes",
        url="https://example.com/pytorch",
        content_hash="hash3",
        category=Category.AI_TECH,
        summary="New features in PyTorch 2.5.",
        published_at=datetime.utcnow(),
    )
    assert rule.matches(entry_wrong_cat) is False

    entry_high_threat = Entry(
        source_id=uuid4(),
        title="Critical PyTorch TorchScript Remote Code Execution",
        url="https://example.com/cve-pytorch",
        content_hash="hash4",
        category=Category.VULNERABILITIES,
        summary="Arbitrary code execution via untrusted model weights in PyTorch.",
        published_at=datetime.utcnow(),
        analysis=Analysis(
            entry_id=uuid4(),
            attack_vector="Deserialization",
            risk_assessment="RCE",
            mitigation="Patch",
            threat_velocity=85,
            severity_index=90,
            model=AnalysisModel.HEURISTIC,
        ),
    )
    assert rule.matches(entry_high_threat) is True


def test_watchlist_rule_disabled():
    rule = WatchlistRule(name="Disabled Rule", keywords=["langchain"], enabled=False)
    entry = Entry(
        source_id=uuid4(),
        title="LangChain prompt injection advisory",
        url="https://example.com/lc",
        content_hash="hash5",
        category=Category.VULNERABILITIES,
        summary="Critical vulnerability in LangChain LCEL parser.",
        published_at=datetime.utcnow(),
    )
    assert rule.matches(entry) is False


@pytest.mark.asyncio
async def test_watchlist_repository_crud(test_uow):
    async with test_uow as uow:
        rule = WatchlistRule(
            name="My Custom Cloud Watchlist",
            keywords=["langchain", "ollama", "anthropic"],
            min_threat_velocity=50,
            enabled=True,
        )
        saved = await uow.watchlist.add(rule)
        assert saved.id is not None
        assert saved.name == "My Custom Cloud Watchlist"
        assert len(saved.keywords) == 3

        # Get
        fetched = await uow.watchlist.get(saved.id)
        assert fetched is not None
        assert fetched.name == "My Custom Cloud Watchlist"

        # List
        rules = await uow.watchlist.list()
        assert len(rules) >= 1

        # Toggle
        toggled = await uow.watchlist.toggle(saved.id, False)
        assert toggled.enabled is False

        # Delete
        deleted = await uow.watchlist.delete(saved.id)
        assert deleted is True

        assert await uow.watchlist.get(saved.id) is None


@pytest.mark.asyncio
async def test_watchlist_pagination_and_sql_filtering(test_uow):
    """Verify that watchlist queries respect category filters in SQL and maintain exact page limits."""
    src_id = uuid4()
    async with test_uow as uow:
        # 1. Create a watchlist rule requiring category AI_MODELS and keyword 'vllm'
        rule = WatchlistRule(
            id=uuid4(),
            name="vLLM Models Watchlist",
            keywords=["vllm"],
            categories=[Category.AI_MODELS],
            enabled=True,
        )
        await uow.watchlist.add(rule)

        # 2. Add 5 matching entries (Category.AI_MODELS with 'vllm' in title)
        for i in range(5):
            entry = Entry(
                id=uuid4(),
                source_id=src_id,
                title=f"vLLM High Performance Serving #{i}",
                url=f"https://example.com/vllm-{src_id}-{i}",
                content_hash=f"hash_vllm_{src_id}_{i}",
                summary=f"Inference optimization #{i} using vLLM PagedAttention.",
                category=Category.AI_MODELS,
                published_at=datetime.utcnow(),
            )
            await uow.entries.add(entry)

        # 3. Add non-matching entry (Category.CYBERSECURITY, wrong category)
        bad_entry = Entry(
            id=uuid4(),
            source_id=src_id,
            title="vLLM in cyber tools",
            url=f"https://example.com/bad-vllm-{src_id}",
            content_hash=f"hash_bad_vllm_{src_id}",
            summary="Testing wrong category filter.",
            category=Category.CYBERSECURITY,
            published_at=datetime.utcnow(),
        )
        await uow.entries.add(bad_entry)
        await uow.commit()

        # 4. Query with watchlist_rules and limit=2
        filters = EntryFilters(watchlist_rules=[rule])
        page1 = await uow.entries.list(filters=filters, pagination=PaginationParams(limit=2, offset=0))
        assert len(page1) == 2

        count = await uow.entries.count(filters=filters)
        assert count == 5  # The bad_entry with wrong category was excluded
