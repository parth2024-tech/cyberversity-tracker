"""
Unit tests for Feature 12: Weekly 'What Changed' Intelligence Brief.
Tests:
- Accurate ISO week bounds calculation
- Rendering from fixture week entries & source telemetry
- Reconciliation of all 5 required sections (Regional releases, Leaderboards, Top stories, Source health, Coverage gaps)
- Markdown and JSON file persistence (data/briefs/YYYY-WW.md & .json)
- API endpoint integration
"""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.weekly_brief_service import (
    WeeklyBriefService,
)
from ai_security_monitor.domain.entities import Category, Entry, Source, SourceType


def test_weekly_brief_week_bounds():
    """Verify ISO week boundary calculation matches exact Monday to Sunday bounds."""
    start_dt, end_dt = WeeklyBriefService.get_week_bounds(2026, 40)
    assert start_dt.tzinfo == UTC
    assert end_dt.tzinfo == UTC
    assert start_dt.weekday() == 0  # Monday
    assert end_dt.weekday() == 6  # Sunday
    assert start_dt.hour == 0 and start_dt.minute == 0 and start_dt.second == 0
    assert end_dt.hour == 23 and end_dt.minute == 59 and end_dt.second == 59


@pytest.mark.asyncio
async def test_weekly_brief_rendering_from_fixture_week(test_uow, tmp_path: Path):
    """Render brief from a fixture week and assert all 5 sections exist and counts reconcile."""
    service = WeeklyBriefService()
    year = 2026
    week = 42
    start_dt, end_dt = service.get_week_bounds(year, week)
    mid_week = start_dt + (end_dt - start_dt) / 2

    src_id = uuid4()
    story_uuid = uuid4()

    # 1. Seed entries for the fixture week
    entry_deepseek = Entry(
        id=uuid4(),
        source_id=src_id,
        title="DeepSeek-V3 Official Open Source Weights Released",
        url="https://example.com/deepseek-v3",
        content_hash="hash_fixture_ds_v3",
        category=Category.AI_MODELS,
        summary="671B parameter MoE frontier model released with SOTA reasoning capabilities.",
        published_at=mid_week,
        metadata={
            "region": "china",
            "lab": "DeepSeek",
            "is_primary": True,
            "story_id": str(story_uuid),
            "ai_velocity_score": 96.0,
        },
    )

    entry_deepseek_echo = Entry(
        id=uuid4(),
        source_id=src_id,
        title="Tech News: Analyzing DeepSeek-V3 Breakthrough",
        url="https://example.com/tech-ds",
        content_hash="hash_fixture_ds_echo",
        category=Category.AI_MODELS,
        summary="Industry reactions and benchmarks on DeepSeek-V3.",
        published_at=mid_week,
        metadata={
            "region": "china",
            "lab": "DeepSeek",
            "story_id": str(story_uuid),
            "ai_velocity_score": 88.0,
        },
    )

    entry_qwen = Entry(
        id=uuid4(),
        source_id=src_id,
        title="Alibaba Releases Qwen2.5-Coder 32B Open Source",
        url="https://example.com/qwen25",
        content_hash="hash_fixture_qwen",
        category=Category.AI_MODELS,
        summary="Qwen team releases powerful coding foundation model.",
        published_at=mid_week,
        metadata={
            "region": "china",
            "lab": "Alibaba / Qwen",
            "is_primary": True,
            "ai_velocity_score": 90.0,
        },
    )

    entry_claude = Entry(
        id=uuid4(),
        source_id=src_id,
        title="Anthropic Launches Claude 3.7 Sonnet Hybrid Reasoning",
        url="https://example.com/claude37",
        content_hash="hash_fixture_claude",
        category=Category.AI_MODELS,
        summary="Anthropic introduces hybrid reasoning architecture.",
        published_at=mid_week,
        metadata={
            "region": "north_america",
            "lab": "Anthropic",
            "is_primary": True,
            "ai_velocity_score": 95.0,
        },
    )

    entry_leaderboard = Entry(
        id=uuid4(),
        source_id=src_id,
        title="DeepSeek-R1 takes #1 spot on LMSYS Chatbot Arena",
        url="https://example.com/lmsys-r1",
        content_hash="hash_fixture_lmsys",
        category=Category.AI_RESEARCH,
        summary="DeepSeek-R1 claims the #1 position on LMSYS Arena leaderboard.",
        published_at=mid_week,
        metadata={
            "is_leaderboard": True,
            "model_name": "DeepSeek-R1",
            "leaderboard_name": "LMSYS Chatbot Arena",
            "leaderboard_event": "new_number_one",
        },
    )

    async with test_uow as uow:
        await uow.entries.add(entry_deepseek)
        await uow.entries.add(entry_deepseek_echo)
        await uow.entries.add(entry_qwen)
        await uow.entries.add(entry_claude)
        await uow.entries.add(entry_leaderboard)

        # 2. Seed sources with health states
        healthy_src = Source(
            id=uuid4(),
            name="Primary Healthy Lab Feed",
            category=Category.AI_MODELS,
            type=SourceType.RSS,
            url="https://example.com/healthy.rss",
            enabled=True,
            config={"health_state": "ok"},
        )
        stale_src = Source(
            id=uuid4(),
            name="Stale University Lab Feed",
            category=Category.AI_RESEARCH,
            type=SourceType.RSS,
            url="https://example.com/stale.rss",
            enabled=True,
            config={"health_state": "stale"},
        )
        dead_src = Source(
            id=uuid4(),
            name="Defunct Scraper Feed",
            category=Category.AI_TECH,
            type=SourceType.RSS,
            url="https://example.com/dead.rss",
            enabled=False,
            config={"health_state": "dead"},
        )
        await uow.sources.add(healthy_src)
        await uow.sources.add(stale_src)
        await uow.sources.add(dead_src)
        await uow.commit()

        # 3. Generate Brief
        brief = await service.generate_brief(
            uow=uow,
            year=year,
            week=week,
            output_dir=tmp_path,
        )

        # 4. Assert Counts Reconcile
        assert brief.year == year
        assert brief.week == week

        # Section 1: Regional Releases
        china_releases = brief.releases_by_region.get("china", {})
        assert "DeepSeek" in china_releases
        assert "Alibaba / Qwen" in china_releases
        na_releases = brief.releases_by_region.get("north_america", {})
        assert "Anthropic" in na_releases

        # Section 2: Leaderboard Shifts
        assert len(brief.leaderboard_shifts) >= 1
        assert any("DeepSeek-R1" in s["model"] for s in brief.leaderboard_shifts)

        # Section 3: Biggest Clustered Stories
        assert len(brief.top_stories) >= 1
        top_cluster = brief.top_stories[0]
        # Story with 2 corroborating entries should have cluster_size=2
        assert top_cluster["cluster_size"] >= 2
        assert "DeepSeek-V3" in top_cluster["title"]

        # Section 4: Source Health Telemetry
        assert len(brief.health_transitions["went_dead"]) >= 1
        assert len(brief.health_transitions["went_stale"]) >= 1
        assert any(
            d["name"] == "Defunct Scraper Feed"
            for d in brief.health_transitions["went_dead"]
        )
        assert any(
            s["name"] == "Stale University Lab Feed"
            for s in brief.health_transitions["went_stale"]
        )

        # Section 5: Coverage Gaps
        # Europe had 0 releases in this fixture week
        assert any("Europe" in gap for gap in brief.coverage_gaps)

        # 5. Assert All 5 Sections Exist in Rendered Markdown
        md = brief.render_markdown()
        assert "## 1. Regional Frontier Model Releases (By Lab)" in md
        assert "## 2. Benchmark & Leaderboard Shifts (New #1 & SOTA Moves)" in md
        assert "## 3. Biggest Clustered Stories (By Corroboration & Velocity)" in md
        assert "## 4. Source Health & Infrastructure Telemetry" in md
        assert "## 5. Coverage Gap Analysis" in md

        # 6. Assert Output Files Persisted
        md_file = tmp_path / f"{year}-W{week:02d}.md"
        json_file = tmp_path / f"{year}-W{week:02d}.json"
        assert md_file.exists()
        assert json_file.exists()

        json_content = json.loads(json_file.read_text(encoding="utf-8"))
        assert json_content["year"] == year
        assert json_content["week"] == week
        assert "releases_by_region" in json_content
        assert "leaderboard_shifts" in json_content
        assert "top_stories" in json_content


def test_weekly_brief_api_endpoints(test_uow):
    """Verify FastAPI router returns JSON and Markdown representations of the weekly brief."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ai_security_monitor.presentation.api.routers.digest import (
        digest_router,
    )

    app = FastAPI()
    app.include_router(digest_router, prefix="/api")
    client = TestClient(app)

    # 1. GET JSON brief
    resp = client.get("/api/digest/weekly?year=2026&week=42&format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["year"] == 2026
    assert data["week"] == 42
    assert "releases_by_region" in data

    # 2. GET Markdown brief
    resp_md = client.get("/api/digest/weekly?year=2026&week=42&format=markdown")
    assert resp_md.status_code == 200
    assert "text/markdown" in resp_md.headers["content-type"]
    assert "# 🌐 Worldwide AI Ecosystem: Weekly 'What Changed' Brief" in resp_md.text

    # 3. POST Generate brief
    resp_gen = client.post("/api/digest/weekly/generate?year=2026&week=42")
    assert resp_gen.status_code == 200
    gen_data = resp_gen.json()
    assert gen_data["year"] == 2026
    assert gen_data["week"] == 42
    assert "2026-W42.md" in gen_data["markdown_file"]

    # 4. POST Generate brief with admin authentication configured
    from ai_security_monitor.config.settings import settings

    orig_key = settings.api.admin_api_key
    try:
        settings.api.admin_api_key = "secret-admin-token"

        # Missing token -> 401
        res_unauth = client.post("/api/digest/weekly/generate?year=2026&week=42")
        assert res_unauth.status_code == 401

        # Wrong token -> 401
        res_wrong = client.post(
            "/api/digest/weekly/generate?year=2026&week=42",
            headers={"X-Admin-Key": "wrong-key"},
        )
        assert res_wrong.status_code == 401

        # Valid token -> 200
        res_auth = client.post(
            "/api/digest/weekly/generate?year=2026&week=42",
            headers={"X-Admin-Key": "secret-admin-token"},
        )
        assert res_auth.status_code == 200
    finally:
        settings.api.admin_api_key = orig_key
