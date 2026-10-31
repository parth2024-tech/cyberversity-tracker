"""
Unit and integration tests for SQLite FTS5 Trigram Search and Multi-parameter Filters (Feature 13).
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ai_security_monitor.domain.entities import Category, Entry, Source, SourceType
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.database.models import Base
from ai_security_monitor.infrastructure.database.repositories import (
    SQLAlchemyEntryRepository,
    SQLAlchemySourceRepository,
)
from ai_security_monitor.presentation.api.main import app


@pytest.fixture
async def fts_engine():
    """Create in-memory SQLite engine equipped with FTS5 trigram virtual table and sync triggers."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5("
                "title, summary, category, translated_text, entry_id UNINDEXED, tokenize='trigram'"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN "
                "INSERT INTO entries_fts(entry_id, title, summary, category, translated_text) "
                "VALUES ("
                "new.id, new.title, new.summary, new.category, "
                "coalesce(json_extract(new.metadata_json, '$.translated_text'), '')"
                "); "
                "END;"
            )
        )
        await conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN "
                "DELETE FROM entries_fts WHERE entry_id = old.id; "
                "INSERT INTO entries_fts(entry_id, title, summary, category, translated_text) "
                "VALUES ("
                "new.id, new.title, new.summary, new.category, "
                "coalesce(json_extract(new.metadata_json, '$.translated_text'), '')"
                "); "
                "END;"
            )
        )
    yield engine
    await engine.dispose()


@pytest.fixture
async def fts_session(fts_engine):
    session_factory = async_sessionmaker(
        fts_engine, class_=AsyncSession, expire_on_commit=False
    )
    session = session_factory()
    yield session
    await session.close()


@pytest.mark.asyncio
async def test_fts_bm25_ranking(fts_session):
    """Verify BM25 ranking orders entries with denser matches higher."""
    entry_repo = SQLAlchemyEntryRepository(fts_session)
    src_id = uuid4()

    # Entry 1: High term frequency for 'vLLM'
    e1 = Entry(
        id=uuid4(),
        source_id=src_id,
        title="vLLM: High-Throughput Serving and Memory PagedAttention with vLLM",
        url="https://example.com/vllm-high",
        content_hash="h_vllm_1",
        category=Category.CYBER_TOOLS,
        summary="vLLM delivers state-of-the-art serving throughput. Explore vLLM benchmarks.",
        published_at=datetime.now(UTC) - timedelta(hours=2),
    )

    # Entry 2: Single incidental mention of 'vLLM'
    e2 = Entry(
        id=uuid4(),
        source_id=src_id,
        title="Comparison of LLM Engines",
        url="https://example.com/vllm-low",
        content_hash="h_vllm_2",
        category=Category.CYBER_TOOLS,
        summary="General evaluation of runtimes including vLLM and TensorRT.",
        published_at=datetime.now(UTC) - timedelta(hours=1),
    )

    # Entry 3: Unrelated
    e3 = Entry(
        id=uuid4(),
        source_id=src_id,
        title="PostgreSQL 17 Vector Extensions",
        url="https://example.com/postgres",
        content_hash="h_pg_3",
        category=Category.AI_TECH,
        summary="Relational database vector capabilities overview.",
        published_at=datetime.now(UTC),
    )

    await entry_repo.add(e1)
    await entry_repo.add(e2)
    await entry_repo.add(e3)
    await fts_session.commit()

    results = await entry_repo.search_fts("vLLM", limit=10)
    assert len(results) == 2
    # e1 has higher term density than e2, so BM25 score ranks it first
    assert results[0].id == e1.id
    assert results[1].id == e2.id


@pytest.mark.asyncio
async def test_fts_chinese_tokenization_and_translation(fts_session):
    """Verify CJK Chinese characters are matched via trigram FTS5 and translated_text field."""
    entry_repo = SQLAlchemyEntryRepository(fts_session)
    src_id = uuid4()

    # Chinese entry with translated_text in metadata
    cn_entry = Entry(
        id=uuid4(),
        source_id=src_id,
        title="深度求索发布全新多模态推理模型架构",
        url="https://example.com/deepseek-release",
        content_hash="h_cn_1",
        category=Category.AI_MODELS,
        summary="深度求索团队开源了最新一代推理权重，全面提升多模态能力与长文本理解。",
        published_at=datetime.now(UTC),
        metadata={
            "translated_text": "DeepSeek releases new multimodal reasoning model architecture and open weights.",
            "region": "china",
            "lab": "DeepSeek",
        },
    )

    qwen_entry = Entry(
        id=uuid4(),
        source_id=src_id,
        title="通义千问 Qwen2.5-Coder 突破代码基准测试",
        url="https://example.com/qwen-eval",
        content_hash="h_cn_2",
        category=Category.AI_RESEARCH,
        summary="阿里云通义实验室发布最新代码模型评测结果，达到业内前沿水平。",
        published_at=datetime.now(UTC),
        metadata={
            "translated_text": "Alibaba Tongyi Qwen2.5-Coder surpasses code generation benchmarks.",
            "region": "china",
            "lab": "Qwen",
        },
    )

    await entry_repo.add(cn_entry)
    await entry_repo.add(qwen_entry)
    await fts_session.commit()

    # Search by Chinese query: "深度求索"
    res_cn = await entry_repo.search_fts("深度求索", limit=5)
    assert len(res_cn) >= 1
    assert any(e.id == cn_entry.id for e in res_cn)

    # Search by English translation query: "multimodal reasoning"
    res_en = await entry_repo.search_fts("multimodal reasoning", limit=5)
    assert len(res_en) >= 1
    assert any(e.id == cn_entry.id for e in res_en)

    # Search by short Chinese keyword fallback: "开源"
    res_short = await entry_repo.search_fts("开源", limit=5)
    assert len(res_short) >= 1
    assert any(e.id == cn_entry.id for e in res_short)


@pytest.mark.asyncio
async def test_filter_combinations_region_lab_tier_dates(fts_session):
    """Verify multi-parameter filtering across lab, subject_region, tier, category, and date bounds."""
    entry_repo = SQLAlchemyEntryRepository(fts_session)
    source_repo = SQLAlchemySourceRepository(fts_session)

    src_tier1 = Source(
        id=uuid4(),
        name="DeepSeek Official Newsroom",
        type=SourceType.RSS,
        category=Category.AI_MODELS,
        url="https://api.deepseek.com/news",
        config={"tier": 1, "region": "china", "country": "CN"},
        enabled=True,
    )
    src_tier2 = Source(
        id=uuid4(),
        name="AI Aggregator",
        type=SourceType.RSS,
        category=Category.AI_TECH,
        url="https://aggregator.ai/feed",
        config={"tier": 2, "region": "global", "country": "US"},
        enabled=True,
    )
    await source_repo.add(src_tier1)
    await source_repo.add(src_tier2)

    now = datetime.now(UTC)

    # Match: Lab=DeepSeek, Tier=1, Region=china, between 3 days ago and 1 day ago
    e_target = Entry(
        id=uuid4(),
        source_id=src_tier1.id,
        title="DeepSeek-R1 Architecture Details",
        url="https://deepseek.com/r1",
        content_hash="hash_target",
        category=Category.AI_MODELS,
        summary="In-depth breakdown of DeepSeek reasoning reinforcement learning.",
        published_at=now - timedelta(days=2),
        metadata={"lab": "DeepSeek", "subject_region": "china"},
    )

    # Wrong date (too old: 10 days ago)
    e_old = Entry(
        id=uuid4(),
        source_id=src_tier1.id,
        title="DeepSeek-V2 Archive",
        url="https://deepseek.com/v2",
        content_hash="hash_old",
        category=Category.AI_MODELS,
        summary="Legacy DeepSeek model report.",
        published_at=now - timedelta(days=10),
        metadata={"lab": "DeepSeek", "subject_region": "china"},
    )

    # Wrong tier (tier 2 source) and wrong lab
    e_other = Entry(
        id=uuid4(),
        source_id=src_tier2.id,
        title="OpenAI o1 Analysis",
        url="https://aggregator.ai/o1",
        content_hash="hash_other",
        category=Category.AI_MODELS,
        summary="Discussion on OpenAI o1 model series.",
        published_at=now - timedelta(days=2),
        metadata={"lab": "OpenAI", "subject_region": "north_america"},
    )

    await entry_repo.add(e_target)
    await entry_repo.add(e_old)
    await entry_repo.add(e_other)
    await fts_session.commit()

    # Query with combined filters
    filters = EntryFilters(
        lab="DeepSeek",
        subject_region="china",
        tier=1,
        category=Category.AI_MODELS,
        since=now - timedelta(days=5),
        until=now - timedelta(days=1),
    )
    matched = await entry_repo.list(
        filters=filters, pagination=PaginationParams(limit=10, offset=0)
    )
    assert len(matched) == 1
    assert matched[0].id == e_target.id

    count = await entry_repo.count(filters=filters)
    assert count == 1


@pytest.mark.asyncio
async def test_api_entries_search_and_filters_endpoint():
    """Verify GET /api/entries handles q, lab, tier, subject_region, from, to query params and returns first_reported_by."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Basic query with q and lab
        res = await client.get(
            "/api/entries", params={"q": "DeepSeek", "lab": "DeepSeek", "tier": 1}
        )
        assert res.status_code == 200
        data = res.json()
        assert "entries" in data
        assert "total" in data
        assert isinstance(data["entries"], list)

        # 2. Date range query
        now_iso = datetime.now(UTC).isoformat()
        week_ago_iso = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        res_date = await client.get(
            "/api/entries", params={"from": week_ago_iso, "to": now_iso, "limit": 10}
        )
        assert res_date.status_code == 200
        data_date = res_date.json()
        assert "entries" in data_date

        # 3. Check first_reported_by field presence
        if data_date["entries"]:
            assert "first_reported_by" in data_date["entries"][0]
