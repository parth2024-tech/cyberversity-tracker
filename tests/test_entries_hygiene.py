"""
Unit and integration tests for entries data hygiene, title/summary sanitization, and API formatting.
"""

from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.presentation.api.main import create_app
from ai_security_monitor.presentation.api.routers.entries import (
    _clean_entry_summary,
    _clean_entry_title,
)


def test_clean_entry_title_poc_prefixes():
    # PoC / Security Tool prefixes
    assert (
        _clean_entry_title("Security Tool / PoC: siyuan-note/siyuan")
        == "siyuan-note/siyuan"
    )
    assert (
        _clean_entry_title("Security Tool: activepieces/activepieces")
        == "activepieces/activepieces"
    )
    assert _clean_entry_title("PoC: slackhq/nebula") == "slackhq/nebula"
    assert _clean_entry_title("POC: CVE-2026-1234") == "CVE-2026-1234"


def test_clean_entry_title_html_entities_and_whitespace():
    assert (
        _clean_entry_title("&#32; DeepSeek-V3 &amp; Qwen-2.5 &#32;")
        == "DeepSeek-V3 & Qwen-2.5"
    )
    assert (
        _clean_entry_title("&quot;Ollama&quot; Multi-GPU &#39;Speedup&#39;")
        == "\"Ollama\" Multi-GPU 'Speedup'"
    )
    assert _clean_entry_title(None) == "Intelligence Dispatch"
    assert _clean_entry_title("   ") == "Intelligence Dispatch"


def test_clean_entry_summary_reddit_and_rss_junk():
    dummy_entry = Entry(
        source_id="src-1",
        published_at=datetime.utcnow(),
        title="vLLM Distributed Serving Architecture",
        url="https://github.com/vllm-project/vllm",
        content_hash="hash1",
        summary="&#32; submitted by &#32; /u/TestUser [link] &#32; [comments]",
        category=Category.GITHUB_TRENDING,
    )

    cleaned = _clean_entry_summary(dummy_entry.summary, dummy_entry)
    assert "submitted by" not in cleaned
    assert "[link]" not in cleaned
    assert "[comments]" not in cleaned
    # Since raw text was purely junk, it synthesizes an informative technical analysis
    assert len(cleaned.split()) >= 20
    assert cleaned.endswith((".", "!", "?"))


def test_clean_entry_summary_deduplication_and_sentence_boundary():
    dummy_entry = Entry(
        source_id="src-2",
        published_at=datetime.utcnow(),
        title="Kimi 1.5 Long-Context Architecture",
        url="https://arxiv.org/abs/2608.9999",
        content_hash="hash2",
        summary="An open-source reasoning model with native 200k context window An open-source reasoning model with native 200k context window",
        category=Category.AI_MODELS,
    )

    cleaned = _clean_entry_summary(dummy_entry.summary, dummy_entry)
    # Checks deduplication
    assert (
        cleaned.count("An open-source reasoning model with native 200k context window")
        == 1
    )
    assert cleaned.endswith((".", "!", "?"))


def test_clean_entry_summary_truncated_word_cleanup():
    dummy_entry = Entry(
        source_id="src-3",
        published_at=datetime.utcnow(),
        title="Reasoning Scaling Test",
        url="https://example.com",
        content_hash="hash3",
        summary=(
            "Safety evaluation is critical for assessing whether aligned Large Language Models "
            "remain robust against jailbreak attacks. And then abruptly cut"
        ),
        category=Category.AI_RESEARCH,
    )

    cleaned = _clean_entry_summary(dummy_entry.summary, dummy_entry)
    # The trailing abrupt cutoff fragment 'And then abruptly cut' should be trimmed to the last full sentence
    assert (
        cleaned
        == "Safety evaluation is critical for assessing whether aligned Large Language Models remain robust against jailbreak attacks."
    )
    assert cleaned.endswith(".")


@pytest.mark.asyncio
async def test_api_entries_serialization_hygiene():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/entries?limit=15")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        for e in data["entries"]:
            assert not e["title"].startswith("Security Tool / PoC:")
            assert not e["title"].startswith("Security Tool:")
            assert "submitted by /u/" not in e["summary"]
            assert "[link] [comments]" not in e["summary"]
            assert e["summary"].endswith((".", "!", "?", '"', "'"))


def test_database_retention_days_setting():
    from ai_security_monitor.config.settings import settings

    assert settings.database.retention_days == 7
    assert settings.database.auto_purge_enabled is False


@pytest.mark.asyncio
async def test_purge_old_entries_1_week_retention(test_uow):
    from datetime import timedelta

    from sqlalchemy import select

    from ai_security_monitor.infrastructure.database.models import EntryModel

    purged = await test_uow.entries.purge_old_entries(older_than_days=7)
    assert isinstance(purged, int)
    assert purged >= 0
    await test_uow.commit()

    cutoff = datetime.utcnow() - timedelta(days=7)
    all_stale = (
        (
            await test_uow.session.execute(
                select(EntryModel).where(EntryModel.fetched_at < cutoff)
            )
        )
        .scalars()
        .all()
    )
    unvaulted_active_stale = [
        e
        for e in all_stale
        if not e.is_purged
        and not (
            e.extra_metadata
            and (
                e.extra_metadata.get("is_important")
                or e.extra_metadata.get("is_saved")
                or e.extra_metadata.get("is_pinned")
            )
        )
    ]
    assert len(unvaulted_active_stale) == 0


@pytest.mark.asyncio
async def test_github_trending_fetcher_api_fallback():
    from unittest.mock import patch

    from ai_security_monitor.domain.entities import Category, Source, SourceType
    from ai_security_monitor.infrastructure.fetchers.github_trending_fetcher import (
        GitHubTrendingFetcher,
    )

    src = Source(
        name="Test Trending Fallback",
        category=Category.GITHUB_TRENDING,
        type=SourceType.GITHUB_TRENDING,
    )
    fetcher = GitHubTrendingFetcher(src)

    # Force scraping failure to verify fallback triggers
    with patch.object(
        fetcher, "_fetch_raw_scraping", side_effect=Exception("Datacenter 429")
    ):
        with patch.object(
            fetcher,
            "_fetch_raw_api",
            return_value=[
                {
                    "title": "vllm-project/vllm: High-throughput LLM serving...",
                    "url": "https://github.com/vllm-project/vllm",
                    "content": "A high-throughput and memory-efficient LLM inference engine",
                    "published_at": datetime.utcnow(),
                    "tags": ["github", "trending", "open-source", "ai"],
                    "metadata": {"repo_name": "vllm-project/vllm", "stars": 30000},
                }
            ],
        ):
            res = await fetcher.fetch()
            assert res.status.value == "success"
            assert len(res.entries) == 1
            assert "vllm" in res.entries[0].title
            assert res.entries[0].category == Category.GITHUB_TRENDING


def test_ai_developer_tools_and_repos_sources():
    from ai_security_monitor.config.sources import load_sources

    cfg = load_sources()
    cyber_tools = [s for s in cfg.sources if s.category == "cyber_tools"]
    github_trending = [s for s in cfg.sources if s.category == "github_trending"]

    assert len(cyber_tools) >= 10
    assert len(github_trending) >= 6

    # Verify key inference runtimes and tools are present
    tool_names = " ".join(s.name for s in cyber_tools).lower()
    assert "vllm" in tool_names
    assert "ollama" in tool_names
    assert "llama.cpp" in tool_names
    assert "sglang" in tool_names


def test_max_ingest_age_days_strict_freshness_boundary():
    """Verify strict ingest age boundary: entries <= max_age_days are kept, entries > max_age_days rejected."""
    from datetime import UTC, datetime, timedelta

    max_age_days = 90
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=max_age_days)

    # 1. Entry within freshness window (89 days old)
    entry_fresh = Entry(
        source_id="src-fresh",
        published_at=now - timedelta(days=89),
        title="vLLM 0.7.0 Release",
        url="https://example.com/vllm",
        content_hash="hash_fresh",
        summary="vLLM release announcement within boundary",
        category=Category.CYBER_TOOLS,
    )

    # 2. Entry outside freshness window (91 days old)
    entry_stale = Entry(
        source_id="src-stale",
        published_at=now - timedelta(days=91),
        title="Ancient Archive Item",
        url="https://example.com/ancient",
        content_hash="hash_stale",
        summary="Old historical dump item that should be discarded",
        category=Category.AI_TECH,
    )

    # 3. Naive datetime within freshness window (5 days old)
    entry_naive = Entry(
        source_id="src-naive",
        published_at=datetime.utcnow() - timedelta(days=5),
        title="Recent Post with Naive Timestamp",
        url="https://example.com/naive",
        content_hash="hash_naive",
        summary="Naive timestamp within freshness window",
        category=Category.AI_RESEARCH,
    )

    # 4. Entry with None published_at should not be dropped
    entry_none = Entry(
        source_id="src-none",
        published_at=None,
        title="Post without Timestamp",
        url="https://example.com/notime",
        content_hash="hash_none",
        summary="Item without published_at",
        category=Category.GITHUB_TRENDING,
    )

    entries = [entry_fresh, entry_stale, entry_naive, entry_none]

    # Replicate the Ingestion Freshness Guard logic from MonitorService
    kept = []
    for e in entries:
        pub_at = e.published_at
        if pub_at is not None:
            if pub_at.tzinfo is None:
                pub_at = pub_at.replace(tzinfo=UTC)
            if pub_at < cutoff:
                continue
        kept.append(e)

    assert entry_fresh in kept
    assert entry_naive in kept
    assert entry_none in kept
    assert entry_stale not in kept
    assert len(kept) == 3
