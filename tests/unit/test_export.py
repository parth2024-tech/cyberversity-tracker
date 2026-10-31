"""
Unit and integration tests for Syndication Feeds and CSV Export (Feature 14).
Tests:
- RSS 2.0 XML generation and feedparser validation (/feed.xml, /rss.xml)
- JSON Feed 1.1 specification conformance (/feed.json)
- RFC 4180 CSV export validation (/api/export.csv, /export.csv)
- Multi-parameter filtering (category, search, lab, region, tier, date range)
- 14-day freshness guard enforcement
"""

import csv
import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import feedparser
import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.domain.entities import Category, Entry, Source, SourceType
from ai_security_monitor.infrastructure.cache import response_cache
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.presentation.api.main import app


@pytest.fixture
async def seed_test_entries():
    """Seed test sources and entries for export verification."""
    response_cache.clear()
    now = datetime.now(UTC)
    uid_suffix = uuid4().hex[:6]
    src_tier1 = Source(
        id=uuid4(),
        name=f"DeepSeek Research {uid_suffix}",
        type=SourceType.RSS,
        category=Category.AI_MODELS,
        url=f"https://api.deepseek.com/feed-{uid_suffix}",
        config={"tier": 1, "region": "china", "country": "CN"},
        enabled=True,
    )
    src_tier2 = Source(
        id=uuid4(),
        name=f"HuggingFace Trending {uid_suffix}",
        type=SourceType.HUGGINGFACE_TRENDING,
        category=Category.AI_TECH,
        url=f"https://huggingface.co/models-{uid_suffix}",
        config={"tier": 2, "region": "global", "country": "US"},
        enabled=True,
    )

    # Entry 1: DeepSeek Tier 1 Model Release
    e1 = Entry(
        id=uuid4(),
        source_id=src_tier1.id,
        title="DeepSeek-R1: Incentivizing Reasoning in LLMs via Reinforcement Learning",
        url="https://github.com/deepseek-ai/DeepSeek-R1",
        content_hash=f"hash_export_1_{uid_suffix}",
        category=Category.AI_MODELS,
        summary="Novel pure RL approach achieving competitive reasoning without supervised fine-tuning.",
        published_at=now - timedelta(days=2),
        tags=["deepseek", "reasoning", "rl"],
        metadata={
            "lab": "DeepSeek",
            "subject_region": "china",
            "region": "china",
            "heat_score": 95.5,
            "first_reported_by": "DeepSeek Research",
        },
    )

    # Entry 2: Hugging Face Trending Tool
    e2 = Entry(
        id=uuid4(),
        source_id=src_tier2.id,
        title="vLLM: High-Throughput Serving Engine with PagedAttention",
        url="https://github.com/vllm-project/vllm",
        content_hash=f"hash_export_2_{uid_suffix}",
        category=Category.CYBER_TOOLS,
        summary="Fast, memory-efficient LLM inference and serving architecture.",
        published_at=now - timedelta(days=5),
        tags=["vllm", "inference", "gpu"],
        metadata={
            "lab": "vLLM Team",
            "subject_region": "north_america",
            "region": "global",
            "heat_score": 88.0,
        },
    )

    # Entry 3: Stale entry (> 14 days old, should be excluded by freshness guard)
    e3_stale = Entry(
        id=uuid4(),
        source_id=src_tier1.id,
        title="Legacy DeepSeek Math Paper Archive",
        url="https://arxiv.org/abs/2401.00000",
        content_hash=f"hash_export_stale_{uid_suffix}",
        category=Category.AI_RESEARCH,
        summary="Old research published last month.",
        published_at=now - timedelta(days=20),
        tags=["archive", "stale"],
        metadata={"lab": "DeepSeek"},
    )

    async with SqlAlchemyUnitOfWork() as uow:
        await uow.sources.add(src_tier1)
        await uow.sources.add(src_tier2)
        await uow.entries.add(e1)
        await uow.entries.add(e2)
        await uow.entries.add(e3_stale)
        await uow.commit()

    yield {"src1": src_tier1, "src2": src_tier2, "e1": e1, "e2": e2, "stale": e3_stale}


@pytest.mark.asyncio
async def test_rss_feed_xml_validity(seed_test_entries):
    """Verify GET /feed.xml and GET /rss.xml produce valid RSS 2.0 XML parsable by feedparser."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/feed.xml", "/rss.xml", "/feed/rss"):
            res = await client.get(path)
            assert res.status_code == 200
            assert "application/rss+xml" in res.headers["content-type"]
            xml_text = res.text
            assert "<?xml" in xml_text
            assert '<rss version="2.0"' in xml_text
            assert "<channel>" in xml_text
            assert "<atom:link" in xml_text

            # Parse with feedparser to verify RFC-822 dates and XML conformance
            feed = feedparser.parse(xml_text)
            assert feed.bozo == 0 or feed.version in ("rss20", "rss2")
            assert len(feed.entries) >= 2
            # Stale entry (> 14 days) must be filtered out
            stale_id = str(seed_test_entries["stale"].id)
            assert not any(
                getattr(item, "guid", "") == stale_id for item in feed.entries
            )


@pytest.mark.asyncio
async def test_json_feed_conformance(seed_test_entries):
    """Verify GET /feed.json conforms strictly to JSON Feed 1.1 specification."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/feed.json", "/feed/json"):
            res = await client.get(path)
            assert res.status_code == 200
            assert "application/feed+json" in res.headers["content-type"]
            data = res.json()
            assert data["version"] == "https://jsonfeed.org/version/1.1"
            assert data["title"] == "AETHERGUARD Worldwide AI Ecosystem"
            assert "items" in data
            assert isinstance(data["items"], list)
            assert len(data["items"]) >= 2

            item = data["items"][0]
            assert "id" in item
            assert "url" in item
            assert "title" in item
            assert "content_text" in item
            assert "date_published" in item
            assert "category" in item
            assert "_aetherguard" in item


@pytest.mark.asyncio
async def test_csv_export_rfc4180(seed_test_entries):
    """Verify GET /api/export.csv and GET /export.csv output valid RFC 4180 CSV with correct headers."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/api/export.csv", "/export.csv", "/feed.csv"):
            res = await client.get(path)
            assert res.status_code == 200
            assert "text/csv" in res.headers["content-type"]
            assert "attachment; filename=" in res.headers["content-disposition"]

            reader = csv.reader(io.StringIO(res.text))
            rows = list(reader)
            assert len(rows) >= 3  # Header + at least 2 entries

            expected_headers = [
                "id",
                "title",
                "url",
                "category",
                "published_at",
                "source_name",
                "region",
                "lab",
                "tier",
                "heat_score",
                "first_reported_by",
                "summary",
                "tags",
            ]
            assert rows[0] == expected_headers

        # CSV export allows full historical data without forced 14-day rolling clamp
        res_stale = await client.get(
            "/api/export.csv", params={"search": "Legacy DeepSeek Math"}
        )
        assert res_stale.status_code == 200
        rows_stale = list(csv.reader(io.StringIO(res_stale.text)))
        stale_id = str(seed_test_entries["stale"].id)
        assert any(row[0] == stale_id for row in rows_stale[1:])


@pytest.mark.asyncio
async def test_export_filters(seed_test_entries):
    """Verify lab, search, category, tier, and region filters in CSV export and feeds."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Filter by lab=DeepSeek
        res_lab = await client.get("/api/export.csv", params={"lab": "DeepSeek"})
        assert res_lab.status_code == 200
        rows_lab = list(csv.reader(io.StringIO(res_lab.text)))
        assert len(rows_lab) >= 2  # Header + DeepSeek entry
        for r in rows_lab[1:]:
            assert "DeepSeek" in r[1] or "DeepSeek" in r[7]

        # 2. Filter by search=vLLM
        res_q = await client.get("/feed.json", params={"q": "vLLM"})
        assert res_q.status_code == 200
        data_q = res_q.json()
        assert len(data_q["items"]) >= 1
        assert any("vLLM" in item["title"] for item in data_q["items"])

        # 3. Filter by tier=1
        res_tier = await client.get("/feed.xml", params={"tier": 1})
        assert res_tier.status_code == 200
        feed_tier = feedparser.parse(res_tier.text)
        assert len(feed_tier.entries) >= 1


@pytest.mark.asyncio
async def test_csv_formula_injection_defense():
    """Verify cells starting with =, +, -, @ are sanitized with single quote."""
    from ai_security_monitor.presentation.api.routers.feed import _sanitize_csv_cell

    assert _sanitize_csv_cell("=1+1") == "'=1+1"
    assert _sanitize_csv_cell("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
    assert _sanitize_csv_cell("-123") == "'-123"
    assert _sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
    assert _sanitize_csv_cell("DeepSeek-R1") == "DeepSeek-R1"
    assert _sanitize_csv_cell("") == ""
    assert _sanitize_csv_cell(None) == ""

