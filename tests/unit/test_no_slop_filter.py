"""
Unit and integration tests for No-Slop Ingestion Filter Service and Audit Log.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.no_slop_filter import (
    FilterReason,
    NoSlopFilterService,
    no_slop_filter,
)
from ai_security_monitor.config.settings import settings
from ai_security_monitor.infrastructure.database.connection import db_manager
from ai_security_monitor.infrastructure.database.models import (
    FilteredEntryModel,
    SourceModel,
)
from ai_security_monitor.presentation.api.main import create_app


def test_no_slop_filter_20_synthetic_titles():
    """
    Test suite of 20 synthetic titles:
    10 slop titles that must drop with the exact expected reason,
    and 10 high-value technical announcements that must pass.
    """
    service = NoSlopFilterService()

    # ── 10 Slop Titles (Must Drop) ───────────────────────────────────────────
    slop_cases = [
        # Roundups
        ("Top 10 AI Tools to Boost Productivity in 2026", FilterReason.ROUNDUP),
        ("Best AI tools for developers this semester", FilterReason.ROUNDUP),
        ("Weekly digest: What happened in AI this week #42", FilterReason.ROUNDUP),
        # Promotional / Clickbait
        ("How to use ChatGPT to make money online fast", FilterReason.PROMOTIONAL),
        ("Save 10 hours with these 5 prompt templates", FilterReason.PROMOTIONAL),
        ("The future of software is here with AI copilot", FilterReason.PROMOTIONAL),
        # Aggregator / Launch spam
        (
            "Product Hunt launch: SuperSummarizer AI tool",
            FilterReason.AGGREGATOR_LAUNCH,
        ),
        # Social reaction without substance
        (
            "Reddit reacts to the latest OpenAI model announcement",
            FilterReason.SOCIAL_REACTION,
        ),
        (
            "The internet reacts to the new humanoid robot demo",
            FilterReason.SOCIAL_REACTION,
        ),
        # Cybersecurity / CVE omission (User Core Directive)
        (
            "Critical CVE-2026-4412 remote code execution vulnerability in web service",
            FilterReason.SECURITY_CVE_OMITTED,
        ),
    ]

    for title, expected_reason in slop_cases:
        decision = service.evaluate(title=title)
        assert decision.is_slop is True, f"Expected '{title}' to be dropped as slop"
        assert decision.reason == expected_reason, (
            f"Expected reason '{expected_reason}' for '{title}', got '{decision.reason}'"
        )

    # ── 10 High-Value AI Titles (Must Pass) ──────────────────────────────────
    pass_cases = [
        "DeepSeek-V3: Multi-Head Latent Attention Architecture and Training Dynamics",
        "Qwen 2.5-Coder 32B Open Weights Checkpoint Released on HuggingFace",
        "vLLM v0.6.2 Inference Runtime Optimization for MoE Models",
        "Test-Time Compute Scaling via Search and Verification in Mathematics",
        "SGLang: High-Throughput Serving Engine with RadixAttention Architecture",
        "InternLM 2.5: Advancing Reasoning Capabilities in 1M Long-Context Tasks",
        "MiniMax Video-01 Generation Architecture Technical Report",
        "Moonshot AI Kimi 1.5 Context Window Scaling to 2M Tokens",
        "Anthropic Claude 3.5 Sonnet Computer Use API Documentation",
        "Mistral Pixtral 12B Vision-Language Foundation Model Checkpoint",
    ]

    for title in pass_cases:
        decision = service.evaluate(title=title)
        assert decision.is_slop is False, (
            f"Expected '{title}' to pass, but got dropped with '{decision.reason}'"
        )


@pytest.mark.asyncio
async def test_filter_log_recording_and_stats():
    """Verify recording dropped items and retrieving stats from database."""
    service = NoSlopFilterService()
    source_id = str(uuid4())

    async with db_manager.session_factory() as session:
        # Create source
        src = SourceModel(
            id=source_id,
            name="Test Slop RSS Feed",
            category="ai_ecosystem",
            type="rss",
            enabled=True,
        )
        session.add(src)
        await session.commit()

        # Record a dropped item
        decision = service.evaluate("Top 10 AI Tools of 2026")
        await service.record_filtered_item(
            session=session,
            source_id=source_id,
            source_name="Test Slop RSS Feed",
            title="Top 10 AI Tools of 2026",
            url="https://example.com/top10",
            decision=decision,
        )
        await session.commit()

        # Retrieve log
        logs = await service.get_filter_log(
            session=session, limit=10, reason=FilterReason.ROUNDUP
        )
        assert len(logs) >= 1
        assert logs[0]["title"] == "Top 10 AI Tools of 2026"
        assert logs[0]["reason"] == FilterReason.ROUNDUP
        assert logs[0]["source_name"] == "Test Slop RSS Feed"

        # Check stats
        stats = await service.get_filter_stats(session=session)
        assert stats["total_filtered_7d"] >= 1
        assert FilterReason.ROUNDUP in stats["by_reason"]


@pytest.mark.asyncio
async def test_purge_expired_filtered_entries():
    """Verify 7-day TTL cleanup removes old records while retaining fresh ones."""
    service = NoSlopFilterService()
    source_id = str(uuid4())

    async with db_manager.session_factory() as session:
        src = SourceModel(
            id=source_id,
            name="Test TTL Source",
            category="ai_ecosystem",
            type="rss",
            enabled=True,
        )
        session.add(src)

        # 1 old record (10 days ago)
        old_item = FilteredEntryModel(
            id=str(uuid4()),
            source_id=source_id,
            source_name="Test TTL Source",
            title="Old Weekly Digest #1",
            url="https://example.com/old",
            reason=FilterReason.ROUNDUP,
            filtered_at=datetime.now(UTC) - timedelta(days=10),
        )
        # 1 fresh record (2 days ago)
        fresh_item = FilteredEntryModel(
            id=str(uuid4()),
            source_id=source_id,
            source_name="Test TTL Source",
            title="Fresh Weekly Digest #2",
            url="https://example.com/fresh",
            reason=FilterReason.ROUNDUP,
            filtered_at=datetime.now(UTC) - timedelta(days=2),
        )
        session.add(old_item)
        session.add(fresh_item)
        await session.commit()

        # Purge items older than 7 days
        purged = await service.purge_expired_filtered_entries(session=session, days=7)
        await session.commit()
        assert purged >= 1

        # Check remaining
        remaining = await service.get_filter_log(session=session, source_id=source_id)
        titles = [r["title"] for r in remaining]
        assert "Fresh Weekly Digest #2" in titles
        assert "Old Weekly Digest #1" not in titles


@pytest.mark.asyncio
async def test_filter_log_api_endpoints():
    """Verify API endpoints: GET /api/filter-log, GET /api/filter-log/stats, POST /api/filter-log/evaluate, POST /api/filter-log/purge."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. POST /api/filter-log/evaluate
        eval_resp = await client.post(
            "/api/filter-log/evaluate",
            json={"title": "How to use AI to make money in 2026", "summary": ""},
        )
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        assert eval_data["is_slop"] is True
        assert eval_data["reason"] == "promotional"

        # 2. GET /api/filter-log
        resp = await client.get("/api/filter-log?limit=50")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

        # 3. GET /api/filter-log/stats
        stats_resp = await client.get("/api/filter-log/stats")
        assert stats_resp.status_code == 200
        stats_data = stats_resp.json()
        assert "total_filtered_7d" in stats_data
        assert "by_reason" in stats_data

        # 4. POST /api/filter-log/purge unauthorized check
        with patch.object(settings.api, "admin_api_key", "secret-test-key"):
            unauth_resp = await client.post("/api/filter-log/purge?days=7")
            assert unauth_resp.status_code == 401

            auth_resp = await client.post(
                "/api/filter-log/purge?days=7",
                headers={"X-Admin-Key": "secret-test-key"},
            )
            assert auth_resp.status_code == 200
            assert auth_resp.json()["status"] == "success"


@pytest.mark.asyncio
async def test_monitor_service_drops_slop_and_increments_entries_filtered():
    """Verify that MonitorService.fetch_source filters slop before pipeline and logs entries_filtered."""
    from ai_security_monitor.application.services.monitor_service import MonitorService
    from ai_security_monitor.domain.entities import (
        Category,
        Entry,
        FetchStatus,
        Source,
        SourceType,
    )
    from ai_security_monitor.infrastructure.fetchers.base import (
        FetcherRegistry,
        FetchResult,
    )

    monitor_svc = MonitorService()
    source_id = uuid4()
    source = Source(
        id=source_id,
        name="Test Ingest Pipeline Feed",
        category=Category.AI_RESEARCH,
        type=SourceType.RSS,
        url="https://example.com/feed.xml",
        enabled=True,
    )
    async with monitor_svc._uow_factory() as uow:
        await uow.sources.add(source)
        await uow.commit()

    # 1 legit entry, 1 slop roundup entry
    entry_clean = Entry(
        source_id=source_id,
        title="DeepSeek-V3 Multi-Head Latent Attention Technical Report",
        url="https://example.com/deepseek-clean",
        content_hash="clean-hash-1",
        category=Category.AI_RESEARCH,
        summary="Novel MoE architecture",
        published_at=datetime.now(UTC),
    )
    entry_slop = Entry(
        source_id=source_id,
        title="Top 10 AI Tools to Boost Productivity in 2026",
        url="https://example.com/top-10-slop",
        content_hash="slop-hash-2",
        category=Category.AI_RESEARCH,
        summary="Roundup of tools",
        published_at=datetime.now(UTC),
    )

    mock_fetcher = AsyncMock()
    mock_fetcher.fetch.return_value = FetchResult(
        entries=[entry_clean, entry_slop],
        entries_new=2,
        entries_total=2,
        status=FetchStatus.SUCCESS,
    )

    with patch.object(FetcherRegistry, "get", return_value=lambda s: mock_fetcher):
        fetch_log = await monitor_svc.fetch_source(source)

        assert fetch_log.status == FetchStatus.SUCCESS
        assert fetch_log.entries_total == 2
        assert fetch_log.entries_filtered == 1
        assert fetch_log.entries_new == 1

        # Verify slop was recorded in filtered_entries table
        async with db_manager.session_factory() as session:
            filter_records = await no_slop_filter.get_filter_log(
                session=session, source_id=str(source_id)
            )
            assert len(filter_records) == 1
            assert (
                filter_records[0]["title"]
                == "Top 10 AI Tools to Boost Productivity in 2026"
            )
            assert filter_records[0]["reason"] == FilterReason.ROUNDUP
