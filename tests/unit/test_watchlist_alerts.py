"""
Unit tests for Feature 11: Watchlists and Multi-Channel Alerts.
Covers:
- Multi-attribute rule matching (lab, model_family, region, min_score, keywords)
- Story-level deduplication (alerts once per story cluster, not per repetitive entry)
- Quiet hours suppression and bypass
- Rate limiting (max N alerts per hour)
- Source health transition alerting (Feature 1 integration)
- API endpoint integration
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.watchlist_alert_service import (
    WatchlistAlertService,
)
from ai_security_monitor.domain.entities import Category, Entry, Source, SourceType
from ai_security_monitor.domain.watchlist import WatchlistRule


def test_watchlist_rule_matching_multi_attributes():
    """Verify rule matching across lab, model_family, region, and min_score."""
    # 1. Lab rule
    deepseek_rule = WatchlistRule(
        name="DeepSeek Lab Tracker",
        lab="DeepSeek",
        enabled=True,
    )

    entry_deepseek = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="DeepSeek-V3 Architecture Deep Dive",
        url="https://example.com/deepseek-v3",
        content_hash="hash_deepseek_1",
        category=Category.AI_MODELS,
        summary="Technical analysis of the newly released DeepSeek-V3 MoE weights.",
        published_at=datetime.now(UTC),
        metadata={"lab": "DeepSeek", "author": "DeepSeek-AI"},
    )
    entry_meta = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Llama 4 Weights Released by Meta AI",
        url="https://example.com/llama4",
        content_hash="hash_llama_1",
        category=Category.AI_MODELS,
        summary="Meta publishes open weights for Llama 4 foundation model.",
        published_at=datetime.now(UTC),
        metadata={"lab": "Meta", "author": "Meta AI"},
    )

    assert deepseek_rule.matches(entry_deepseek) is True
    assert deepseek_rule.matches(entry_meta) is False

    # 2. Model Family rule
    qwen_rule = WatchlistRule(
        name="Qwen Family Tracker",
        model_family="qwen",
        enabled=True,
    )
    entry_qwen = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Alibaba Releases Qwen2.5-Coder 32B",
        url="https://example.com/qwen",
        content_hash="hash_qwen_1",
        category=Category.AI_MODELS,
        summary="Alibaba open-sources Qwen2.5-Coder with SOTA code completion.",
        published_at=datetime.now(UTC),
        metadata={"model_family": "qwen", "lab": "Alibaba"},
    )
    assert qwen_rule.matches(entry_qwen) is True
    assert qwen_rule.matches(entry_meta) is False

    # 3. Region rule
    china_rule = WatchlistRule(
        name="China Ecosystem Radar",
        region="china",
        enabled=True,
    )
    assert (
        china_rule.matches(entry_qwen) is False
    )  # no region metadata and no 'china' in text
    entry_china = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Shanghai AI Lab InternLM-3 Open Sourced",
        url="https://example.com/internlm",
        content_hash="hash_internlm_1",
        category=Category.AI_MODELS,
        summary="Shanghai AI Lab launches InternLM-3 reasoning model in China.",
        published_at=datetime.now(UTC),
        metadata={"region": "china"},
    )
    assert china_rule.matches(entry_china) is True

    # 4. Minimum Score rule
    high_score_rule = WatchlistRule(
        name="Breaking Breakthroughs",
        min_score=80.0,
        enabled=True,
    )
    entry_low_score = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Minor library bugfix release",
        url="https://example.com/minor",
        content_hash="hash_minor_1",
        category=Category.AI_TECH,
        summary="Bug fix update.",
        published_at=datetime.now(UTC),
        metadata={"ai_velocity_score": 45.0},
    )
    entry_high_score = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Seminal Foundation Model Release",
        url="https://example.com/major",
        content_hash="hash_major_1",
        category=Category.AI_MODELS,
        summary="Breakthrough reasoning capability.",
        published_at=datetime.now(UTC),
        metadata={"ai_velocity_score": 92.5},
    )
    assert high_score_rule.matches(entry_low_score) is False
    assert high_score_rule.matches(entry_high_score) is True


@pytest.mark.asyncio
async def test_alert_dedupe_per_story(test_uow):
    """Multiple entries from the same story cluster should only alert once."""
    service = WatchlistAlertService()
    story_id = uuid4()
    src_id = uuid4()

    rule = WatchlistRule(
        name="DeepSeek Story Alert",
        keywords=["deepseek"],
        channel="console",
        enabled=True,
    )

    entry1 = Entry(
        id=uuid4(),
        source_id=src_id,
        title="DeepSeek-R1 Released: Reasoning Model Announcement",
        url="https://example.com/deepseek-r1-launch",
        content_hash="hash_r1_1",
        category=Category.AI_MODELS,
        summary="DeepSeek announces R1 open reasoning models.",
        published_at=datetime.now(UTC),
    )

    entry2 = Entry(
        id=uuid4(),
        source_id=src_id,
        title="TechCrunch: DeepSeek Shakes AI Market With R1",
        url="https://example.com/deepseek-r1-techcrunch",
        content_hash="hash_r1_2",
        category=Category.AI_MODELS,
        summary="Aggregator coverage of the DeepSeek R1 release.",
        published_at=datetime.now(UTC),
    )

    async with test_uow as uow:
        await uow.watchlist.add(rule)

        # 1. First entry for story -> Dispatched
        res1 = await service.evaluate_entry(
            uow=uow,
            entry=entry1,
            story_id=story_id,
            rules=[rule],
            bypass_quiet_hours=True,
        )
        assert len(res1) == 1
        assert res1[0]["status"] == "dispatched"

        # 2. Second entry for same story -> Skipped (already alerted for story)
        res2 = await service.evaluate_entry(
            uow=uow,
            entry=entry2,
            story_id=story_id,
            rules=[rule],
            bypass_quiet_hours=True,
        )
        assert len(res2) == 1
        assert res2[0]["status"] == "skipped"
        assert res2[0]["reason"] == "already_alerted_story"


@pytest.mark.asyncio
async def test_alert_rate_limiting_hourly_cap(test_uow):
    """Dispatches should be capped when exceeding max_per_hour limit."""
    service = WatchlistAlertService(default_max_per_hour=3)
    src_id = uuid4()

    rule = WatchlistRule(
        name="Rate Limited Rule",
        keywords=["vllm"],
        channel="console",
        enabled=True,
    )

    now = datetime(2026, 10, 31, 14, 0, 0, tzinfo=UTC)

    async with test_uow as uow:
        await uow.watchlist.add(rule)

        # Send 3 alerts (limit is 3)
        for i in range(3):
            entry = Entry(
                id=uuid4(),
                source_id=src_id,
                title=f"vLLM Update #{i}",
                url=f"https://example.com/vllm-{i}",
                content_hash=f"hash_vllm_rate_{i}",
                category=Category.AI_TECH,
                summary="vLLM throughput optimization.",
                published_at=now,
            )
            res = await service.evaluate_entry(
                uow=uow,
                entry=entry,
                story_id=uuid4(),
                rules=[rule],
                bypass_quiet_hours=True,
                max_per_hour=3,
                now=now,
            )
            assert res[0]["status"] == "dispatched"

        # 4th entry in same hour -> Rate limited!
        entry_4 = Entry(
            id=uuid4(),
            source_id=src_id,
            title="vLLM Update #4",
            url="https://example.com/vllm-4",
            content_hash="hash_vllm_rate_4",
            category=Category.AI_TECH,
            summary="vLLM throughput optimization 4.",
            published_at=now,
        )
        res_4 = await service.evaluate_entry(
            uow=uow,
            entry=entry_4,
            story_id=uuid4(),
            rules=[rule],
            bypass_quiet_hours=True,
            max_per_hour=3,
            now=now,
        )
        assert res_4[0]["status"] == "skipped"
        assert res_4[0]["reason"] == "rate_limited_hourly_cap"


@pytest.mark.asyncio
async def test_quiet_hours_suppression_and_bypass(test_uow):
    """Alerts during quiet hours (22:00 to 08:00 UTC) should be suppressed unless bypassed."""
    service = WatchlistAlertService(quiet_hours_start=22, quiet_hours_end=8)
    src_id = uuid4()

    rule = WatchlistRule(
        name="Quiet Hours Rule",
        keywords=["claude"],
        channel="console",
        enabled=True,
    )

    night_time = datetime(2026, 10, 31, 23, 30, 0, tzinfo=UTC)
    entry = Entry(
        id=uuid4(),
        source_id=src_id,
        title="Anthropic Releases Claude 3.7 Sonnet",
        url="https://example.com/claude37",
        content_hash="hash_claude_night",
        category=Category.AI_MODELS,
        summary="Hybrid reasoning and standard generation model.",
        published_at=night_time,
    )

    async with test_uow as uow:
        await uow.watchlist.add(rule)

        # 1. Non-bypassed during quiet hours -> Suppressed
        res_night = await service.evaluate_entry(
            uow=uow,
            entry=entry,
            story_id=uuid4(),
            rules=[rule],
            bypass_quiet_hours=False,
            now=night_time,
        )
        assert res_night[0]["status"] == "skipped"
        assert res_night[0]["reason"] == "quiet_hours_suppressed"

        # 2. Bypassed during quiet hours -> Dispatched
        res_bypass = await service.evaluate_entry(
            uow=uow,
            entry=entry,
            story_id=uuid4(),
            rules=[rule],
            bypass_quiet_hours=True,
            now=night_time,
        )
        assert res_bypass[0]["status"] == "dispatched"


@pytest.mark.asyncio
async def test_source_health_alert_dispatch(test_uow):
    """Source health state transitions (OK -> STALE or DEAD) should trigger alerts."""
    service = WatchlistAlertService()
    source = Source(
        id=uuid4(),
        name="OpenAI Research Blog",
        category=Category.AI_RESEARCH,
        type=SourceType.RSS,
        url="https://openai.com/research/rss.xml",
        query=None,
        rate_limit_seconds=0,
        enabled=True,
    )

    async with test_uow as uow:
        # Daytime -> Dispatched
        day_time = datetime(2026, 10, 31, 15, 0, 0, tzinfo=UTC)
        res = await service.send_source_health_alert(
            uow=uow,
            source=source,
            old_status="ok",
            new_status="stale",
            channel="telegram",
            now=day_time,
        )
        assert res["status"] == "dispatched"
        assert "STALE" in res["title"]
        assert res["source_name"] == "OpenAI Research Blog"

        # Quiet hours -> Suppressed
        night_time = datetime(2026, 10, 31, 3, 0, 0, tzinfo=UTC)
        res_night = await service.send_source_health_alert(
            uow=uow,
            source=source,
            old_status="stale",
            new_status="dead",
            channel="telegram",
            bypass_quiet_hours=False,
            now=night_time,
        )
        assert res_night["status"] == "skipped"
        assert res_night["reason"] == "quiet_hours_suppressed"


def test_watchlist_api_endpoints(test_uow):
    """Verify FastAPI router endpoints for Watchlists and Alert history."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ai_security_monitor.infrastructure.database.unit_of_work import (
        get_unit_of_work,
    )
    from ai_security_monitor.presentation.api.routers.watchlist import (
        watchlist_router,
    )

    app = FastAPI()
    app.include_router(watchlist_router, prefix="/api")
    app.dependency_overrides[get_unit_of_work] = lambda: test_uow
    client = TestClient(app)

    # 1. Create rule with Feature 11 attributes
    payload = {
        "name": "Frontier Qwen Models",
        "keywords": ["coder"],
        "lab": "Alibaba",
        "model_family": "qwen",
        "region": "china",
        "min_score": 75.0,
        "channel": "slack",
        "channel_config": {"webhook_url": "https://hooks.slack.com/services/test"},
        "enabled": True,
    }
    resp = client.post("/api/watchlist", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["lab"] == "Alibaba"
    assert data["model_family"] == "qwen"
    assert data["channel"] == "slack"
    rule_id = data["id"]

    # 2. List rules
    resp_list = client.get("/api/watchlist")
    assert resp_list.status_code == 200
    rules = resp_list.json()["rules"]
    assert any(r["id"] == rule_id for r in rules)

    # 3. List rule alerts
    resp_alerts = client.get(f"/api/watchlist/{rule_id}/alerts")
    assert resp_alerts.status_code == 200
    assert resp_alerts.json()["count"] == 0

    # 4. List global alerts
    resp_all_alerts = client.get("/api/watchlist/alerts")
    assert resp_all_alerts.status_code == 200
