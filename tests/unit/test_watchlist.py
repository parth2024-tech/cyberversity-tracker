"""
Unit tests for Custom Watchlist Rules and Threat Hunting.
"""
from datetime import datetime
from uuid import uuid4
import pytest

from ai_security_monitor.domain.entities import Category, Entry, Analysis, AnalysisModel
from ai_security_monitor.domain.watchlist import WatchlistRule


def test_watchlist_rule_keyword_matching():
    rule = WatchlistRule(
        name="DeepSeek / vLLM Watchlist",
        keywords=["deepseek", "vllm", "lcel"],
        enabled=True
    )

    entry1 = Entry(
        source_id=uuid4(),
        title="Novel DeepSeek-V3 jailbreak technique discovered",
        url="https://example.com/deepseek-exploit",
        content_hash="hash1",
        category=Category.AI_RESEARCH,
        summary="Researchers demonstrated prompt leaking on DeepSeek MoE architecture.",
        published_at=datetime.utcnow()
    )

    entry2 = Entry(
        source_id=uuid4(),
        title="Unrelated standard kernel vulnerability",
        url="https://example.com/kernel",
        content_hash="hash2",
        category=Category.CYBERSECURITY,
        summary="Buffer overflow in older Linux kernel module.",
        published_at=datetime.utcnow()
    )

    assert rule.matches(entry1) is True
    assert rule.matches(entry2) is False


def test_watchlist_rule_category_and_velocity_constraints():
    rule = WatchlistRule(
        name="Critical CVEs only",
        keywords=["pytorch"],
        categories=[Category.VULNERABILITIES],
        min_threat_velocity=70,
        enabled=True
    )

    # Low velocity or wrong category -> False
    entry_wrong_cat = Entry(
        source_id=uuid4(),
        title="PyTorch 2.5 general release notes",
        url="https://example.com/pytorch",
        content_hash="hash3",
        category=Category.AI_TECH,
        summary="New features in PyTorch 2.5.",
        published_at=datetime.utcnow()
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
            model=AnalysisModel.HEURISTIC
        )
    )
    assert rule.matches(entry_high_threat) is True


def test_watchlist_rule_disabled():
    rule = WatchlistRule(
        name="Disabled Rule",
        keywords=["langchain"],
        enabled=False
    )
    entry = Entry(
        source_id=uuid4(),
        title="LangChain prompt injection advisory",
        url="https://example.com/lc",
        content_hash="hash5",
        category=Category.VULNERABILITIES,
        summary="Critical vulnerability in LangChain LCEL parser.",
        published_at=datetime.utcnow()
    )
    assert rule.matches(entry) is False


@pytest.mark.asyncio
async def test_watchlist_repository_crud(test_uow):
    async with test_uow as uow:
        rule = WatchlistRule(
            name="My Custom Cloud Watchlist",
            keywords=["langchain", "ollama", "anthropic"],
            min_threat_velocity=50,
            enabled=True
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
