"""
Unit tests for Missed-Story Audit Service and Telemetry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.audit_service import (
    AuditService,
    matches_story_tokens,
    normalize_tokens,
)
from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import AuditStory
from ai_security_monitor.infrastructure.database.connection import db_manager
from ai_security_monitor.infrastructure.database.models import (
    AuditStoryModel,
    EntryModel,
    SourceModel,
)
from ai_security_monitor.presentation.api.main import create_app


def test_normalize_tokens():
    """Verify that normalize_tokens generates punctuation and separator variants."""
    variants = normalize_tokens("DeepSeek-V2.5")
    assert "deepseek-v2.5" in variants
    assert "deepseek v2.5" in variants
    assert "deepseekv2.5" in variants
    assert "deepseek v2 5" in variants
    assert "deepseekv25" in variants

    underscore_variants = normalize_tokens("seed_tts")
    assert "seed_tts" in underscore_variants
    assert "seed tts" in underscore_variants
    assert "seedtts" in underscore_variants


def test_matches_story_tokens_model_names():
    """Verify matching based on model names with hyphen and space variations."""
    story = AuditStory(
        id=uuid4(),
        title="DeepSeek-V2.5 Multi-Head Latent Attention Release",
        lab_name="DeepSeek",
        region="china",
        release_date=datetime(2026, 9, 5, 0, 0, tzinfo=UTC),
        canonical_url="https://api-docs.deepseek.com/news/news20260905",
        model_names=["DeepSeek-V2.5", "DeepSeek V2.5"],
        org_tokens=["deepseek"],
    )

    # Exact hyphen match
    assert (
        matches_story_tokens(
            story,
            title="DeepSeek-V2.5 officially open sourced",
            summary="Weights released on HuggingFace",
            url="https://github.com/deepseek-ai/DeepSeek-V2.5",
        )
        is True
    )

    # Separator variation (space instead of hyphen)
    assert (
        matches_story_tokens(
            story,
            title="DeepSeek V2.5 released with chat and coder abilities merged",
            summary="New unified checkpoint",
            url="https://huggingface.co/deepseek-ai",
        )
        is True
    )

    # Compact variation (no separator)
    assert (
        matches_story_tokens(
            story,
            title="benchmarking deepseekv2.5 on reasoning tasks",
            summary="Analysis",
            url="https://example.com/test",
        )
        is True
    )

    # Completely unrelated headline
    assert (
        matches_story_tokens(
            story,
            title="Release notes for Linux Kernel 6.12",
            summary="Memory management enhancements",
            url="https://kernel.org",
        )
        is False
    )


def test_matches_story_tokens_org_and_title_keywords():
    """Verify matching through org tokens and distinct title tokens."""
    story = AuditStory(
        id=uuid4(),
        title="Kimi 1.5 Multimodal Long Context Release",
        lab_name="Moonshot AI",
        region="china",
        release_date=datetime(2026, 10, 11, 0, 0, tzinfo=UTC),
        canonical_url="https://kimi.moonshot.cn",
        model_names=["Kimi 1.5", "Kimi-1.5"],
        org_tokens=["moonshot"],
    )

    # Org match + title token 'kimi'
    assert (
        matches_story_tokens(
            story,
            title="Moonshot launches Kimi with expanded multimodal context",
            summary="Now accepts 2M tokens",
            url="https://techcrunch.com/moonshot-kimi",
        )
        is True
    )

    # Org match without relevant title release tokens
    assert (
        matches_story_tokens(
            story,
            title="Moonshot venture capital closes investment round",
            summary="Financial quarterly update",
            url="https://investor.com/news",
        )
        is False
    )


def test_render_markdown_report():
    """Verify markdown report rendering structure and status tags."""
    service = AuditService()
    report = service._render_markdown_report(
        evaluated_results=[
            {
                "story_id": "1",
                "title": "DeepSeek-V2.5",
                "lab_name": "DeepSeek",
                "region": "china",
                "release_date": "2026-09-05",
                "captured": True,
                "lag_hours": 1.2,
                "first_seen_at": "2026-09-05 01:12",
                "matched_source": "HuggingFace Trending",
                "diagnostic": "Captured",
            },
            {
                "story_id": "2",
                "title": "MiniMax Video-01",
                "lab_name": "MiniMax",
                "region": "china",
                "release_date": "2026-09-01",
                "captured": False,
                "lag_hours": None,
                "first_seen_at": "—",
                "matched_source": "—",
                "diagnostic": "Zero matching entries found",
            },
        ],
        missed_stories=[
            {
                "story_id": "2",
                "title": "MiniMax Video-01",
                "lab_name": "MiniMax",
                "region": "china",
                "release_date": "2026-09-01",
                "canonical_url": "https://minimax.io",
                "diagnostic": "Zero matching entries found across active feeds",
                "todo_action": "Add primary release feed for MiniMax",
                "candidates": [],
            }
        ],
        summary={
            "total_stories": 2,
            "captured_count": 1,
            "capture_rate_pct": 50.0,
            "china_total": 2,
            "china_captured": 1,
            "china_capture_rate_pct": 50.0,
            "median_lag_hours": 1.2,
            "audit_passed": False,
        },
    )

    assert "### AetherGuard Missed-Story & Ecosystem Audit Report" in report
    assert "Overall Capture Rate" in report
    assert "50.0%" in report
    assert "China Capture Rate" in report
    assert "Median Ingestion Lag" in report
    assert "1.2h" in report
    assert "NEEDS_TUNING" in report
    assert "Missed Story Diagnostics & Feed To-Do Actions" in report
    assert "Add primary release feed for MiniMax" in report


@pytest.mark.asyncio
async def test_run_audit_no_stories():
    """Verify run_audit handles empty story set gracefully."""
    service = AuditService()
    mock_session = AsyncMock()

    mock_stories_res = MagicMock()
    mock_stories_res.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_stories_res

    res = await service.run_audit(session=mock_session)
    assert res["summary"]["total_stories"] == 0
    assert res["summary"]["status"] == "NO_STORIES"
    assert "No benchmark stories found" in res["markdown_report"]


@pytest.mark.asyncio
async def test_run_audit_captured_and_missed_flow():
    """Verify full evaluation logic with captured story, missed story, and candidate out of window."""
    service = AuditService()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    story1 = AuditStoryModel(
        id="story-1",
        title="DeepSeek-V2.5 Unified Release",
        lab_name="DeepSeek",
        region="china",
        release_date=datetime(2026, 9, 5, 0, 0, tzinfo=UTC),
        canonical_url="https://deepseek.com",
        model_names=["DeepSeek-V2.5"],
        org_tokens=["deepseek"],
    )
    story2 = AuditStoryModel(
        id="story-2",
        title="MiniMax Video-01 Generation",
        lab_name="MiniMax",
        region="china",
        release_date=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
        canonical_url="https://minimax.io",
        model_names=["Video-01"],
        org_tokens=["minimax"],
    )
    story3 = AuditStoryModel(
        id="story-3",
        title="Mistral Pixtral 12B Vision Model",
        lab_name="Mistral AI",
        region="europe",
        release_date=datetime(2026, 9, 17, 0, 0, tzinfo=UTC),
        canonical_url="https://mistral.ai",
        model_names=["Pixtral 12B"],
        org_tokens=["mistral"],
    )

    source1 = SourceModel(
        id="source-1",
        name="HuggingFace AI Releases",
        category="ai_research",
        type="rss",
        enabled=True,
    )

    entry1 = EntryModel(
        id="entry-1",
        source_id="source-1",
        title="DeepSeek-V2.5 officially released",
        summary="Unified checkpoint open on HuggingFace",
        url="https://example.com/deepseek",
        content_hash="hash-1",
        published_at=datetime(2026, 9, 5, 3, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 9, 5, 3, 10, tzinfo=UTC),
        is_purged=False,
    )
    # Entry 3 is 10 days after release (outside 7d window, inside 14d candidate window)
    entry3_late = EntryModel(
        id="entry-3",
        source_id="source-1",
        title="Mistral Pixtral 12B fine-tuning tutorial",
        summary="A retrospective review of Pixtral 12B",
        url="https://example.com/pixtral-late",
        content_hash="hash-3",
        published_at=datetime(2026, 9, 27, 0, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 9, 27, 0, 10, tzinfo=UTC),
        is_purged=False,
    )

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        res = MagicMock()
        if call_count == 1:
            # stories query
            res.scalars.return_value.all.return_value = [story1, story2, story3]
        elif call_count == 2:
            # sources query
            res.scalars.return_value.all.return_value = [source1]
        elif call_count == 3:
            # entries query
            res.scalars.return_value.all.return_value = [entry1, entry3_late]
        return res

    mock_session.execute.side_effect = mock_execute

    report = await service.run_audit(session=mock_session)

    assert report["summary"]["total_stories"] == 3
    assert report["summary"]["captured_count"] == 1
    assert report["summary"]["missed_count"] == 2
    assert report["summary"]["capture_rate_pct"] == 33.3
    assert report["summary"]["china_total"] == 2
    assert report["summary"]["china_captured"] == 1
    assert report["summary"]["china_capture_rate_pct"] == 50.0
    assert report["summary"]["median_lag_hours"] == 3.0

    # Verify results details
    results = report["results"]
    assert len(results) == 3
    assert results[0]["captured"] is True
    assert results[0]["lag_hours"] == 3.0
    assert results[0]["matched_source"] == "HuggingFace AI Releases"

    # Story 2 missed with 0 candidates
    assert results[1]["captured"] is False
    assert "Zero matching entries" in results[1]["diagnostic"]

    # Story 3 missed with candidate outside 7d window
    assert results[2]["captured"] is False
    assert "outside 7d window" in results[2]["diagnostic"]


@pytest.mark.asyncio
async def test_audit_api_endpoints():
    """Verify GET /api/audit and POST /api/audit/run routes."""
    # Ensure test story exists in test database
    async with db_manager.session_factory() as session:
        test_story = AuditStoryModel(
            id=str(uuid4()),
            title="Qwen 2.5-Coder 32B Benchmark Release",
            lab_name="Alibaba Qwen",
            region="china",
            release_date=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
            canonical_url="https://qwenlm.github.io/blog/qwen2.5-coder/",
            model_names=["Qwen 2.5-Coder", "Qwen2.5-Coder"],
            org_tokens=["qwen", "alibaba"],
            added_by="test",
        )
        session.add(test_story)
        await session.commit()

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. GET /api/audit (JSON format)
        resp = await client.get("/api/audit?since=2026-09-01")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "results" in data
        assert "markdown_report" in data
        assert data["summary"]["total_stories"] >= 1

        # 2. GET /api/audit (Markdown format)
        resp_md = await client.get("/api/audit?since=2026-09-01&format=markdown")
        assert resp_md.status_code == 200
        assert "### AetherGuard Missed-Story & Ecosystem Audit Report" in resp_md.text

        # 3. POST /api/audit/run with unauthenticated request when key configured
        with patch.object(settings.api, "admin_api_key", "secret-test-key"):
            unauth_resp = await client.post("/api/audit/run")
            assert unauth_resp.status_code == 401

        # 4. POST /api/audit/run with valid key
        with patch.object(settings.api, "admin_api_key", "secret-test-key"):
            auth_resp = await client.post(
                "/api/audit/run", headers={"X-Admin-Key": "secret-test-key"}
            )
            assert auth_resp.status_code == 200
            run_data = auth_resp.json()
            assert "summary" in run_data
            assert run_data["summary"]["total_stories"] >= 1
