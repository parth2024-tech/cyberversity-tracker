"""
Test suite for China AI & Cybersecurity Intelligence Sources,
Heuristic bilingual analysis, and regional filtering.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.config.sources import load_sources
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.infrastructure.analyzers.heuristic_analyzer import (
    HeuristicAnalyzer,
)
from ai_security_monitor.presentation.api.main import create_app


def test_china_sources_configuration_loaded():
    """Verify that China AI and Cybersecurity sources are properly configured in YAML."""
    config = load_sources()
    china_sources = [
        s for s in config.sources if s.region == "china" or s.country in ("CN", "HK")
    ]

    # We configured 19 verified China sources
    assert len(china_sources) >= 15

    # Verify core AI frontier entities exist
    names = {s.name for s in china_sources}
    assert any("DeepSeek" in n for n in names)
    assert any("Qwen" in n for n in names)
    assert any("ModelScope" in n for n in names)
    assert any("InternLM" in n for n in names)
    assert any("GLM" in n for n in names)
    assert any("arXiv" in n for n in names)


@pytest.mark.asyncio
async def test_chinese_bilingual_threat_heuristics():
    """Verify that the heuristic analyzer correctly detects Chinese zero-days and AI models."""
    analyzer = HeuristicAnalyzer()
    entry = Entry(
        id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        title="DeepSeek-R1 曝出严重零日漏洞：提示注入实现远程代码执行在野利用",
        url="https://example.com/deepseek-rce",
        content_hash="china_test_hash_1",
        summary="奇安信技术研究院监测到针对开源大模型 DeepSeek 与 Qwen 的高危攻击利用链，攻击者利用越狱漏洞与系统提示词注入完成提权与任意代码执行。",
        published_at=datetime.now(UTC),
        category=Category.VULNERABILITIES,
        tags=["DeepSeek", "Qwen", "0day", "RCE"],
        metadata={"region": "china", "country": "CN"},
    )

    analysis = await analyzer.analyze(entry)

    # Velocity should be elevated due to 零日 / 远程代码执行 / 0day
    assert analysis.threat_velocity >= 50
    # Affected ecosystem should detect DeepSeek and Qwen
    eco_str = " ".join(analysis.affected_ecosystem or [])
    assert "DeepSeek" in eco_str or "Qwen" in eco_str


@pytest.mark.asyncio
async def test_api_entries_china_theatre_filter():
    """Verify that querying /api/entries with region=china returns Chinese intelligence."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from ai_security_monitor.domain.entities import Category, Entry
    from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
    from ai_security_monitor.infrastructure.database.unit_of_work import (
        SqlAlchemyUnitOfWork,
    )

    async with SqlAlchemyUnitOfWork() as uow:
        cn_items = await uow.entries.list(
            filters=EntryFilters(region="china"), pagination=PaginationParams(limit=1)
        )
        if not cn_items:
            all_srcs = await uow.sources.list(enabled_only=False)
            cn_src = next(
                (
                    s
                    for s in all_srcs
                    if s.config
                    and (
                        s.config.get("country") in ("CN", "HK")
                        or s.config.get("region") == "china"
                    )
                ),
                all_srcs[0],
            )
            await uow.entries.add(
                Entry(
                    id=uuid4(),
                    source_id=cn_src.id,
                    title="Qwen 2.5 Open Model Weights Announced",
                    url=f"https://test.cn/{uuid4()}",
                    content_hash=f"cn_{uuid4().hex[:16]}",
                    published_at=datetime.now(UTC),
                    category=Category.AI_MODELS,
                    metadata={"region": "china", "country": "CN"},
                    summary="Alibaba Qwen releases open weights.",
                )
            )
            await uow.commit()

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/entries?region=china&limit=20")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "total" in data
        assert data["total"] > 0

        # Check that returned entries have region china or country CN/HK
        entries = data["entries"]
        assert len(entries) > 0
        for e in entries:
            reg = e.get("region", "").lower()
            cntry = e.get("country", "").upper()
            assert reg == "china" or cntry in ("CN", "HK")


def test_modelscope_fetcher_handles_string_params_and_metrics():
    """ModelScopeFetcher._parse_entry must handle raw['params'] being a string ('7B') without crashing format string."""
    from ai_security_monitor.domain.entities import Source, SourceType
    from ai_security_monitor.infrastructure.fetchers.modelscope_fetcher import (
        ModelScopeFetcher,
    )

    dummy_source = Source(
        id=uuid.uuid4(),
        name="ModelScope Hub",
        category=Category.AI_MODELS,
        type=SourceType.MODELSCOPE,
        url="https://modelscope.cn",
    )
    fetcher = ModelScopeFetcher(dummy_source)

    # String params and string metrics
    raw_item = {
        "id": "qwen/Qwen2.5-7B-Instruct",
        "name": "Qwen2.5-7B-Instruct",
        "description": "Alibaba foundation model",
        "params": "7B",
        "downloads": "120000",
        "likes": "4500",
        "tasks": ["text-generation"],
        "license": "Apache-2.0",
    }
    entry = fetcher._parse_entry(raw_item)
    assert (
        entry.title
        == "[ModelScope] qwen/Qwen2.5-7B-Instruct (7B Params) - text-generation"
    )
    assert "7B" in entry.summary
    assert entry.metadata["parameters"] == "7B"
    assert entry.metadata["downloads"] == 120000
    assert entry.metadata["likes"] == 4500

    # Non-numeric string metrics
    raw_invalid_metrics = {
        "id": "deepseek/DeepSeek-V3",
        "params": "236B",
        "downloads": "N/A",
        "likes": None,
    }
    entry_invalid = fetcher._parse_entry(raw_invalid_metrics)
    assert entry_invalid.metadata["downloads"] == 0
    assert entry_invalid.metadata["likes"] == 0


def test_huggingface_china_fetcher_orgs_and_quantization_filtering():
    """HuggingFaceChinaFetcher must include all 2026 frontier Chinese labs and filter derivatives."""
    from ai_security_monitor.infrastructure.fetchers.huggingface_china_fetcher import (
        HuggingFaceChinaFetcher,
    )

    authors = HuggingFaceChinaFetcher.DEFAULT_AUTHORS
    assert "deepseek-ai" in authors
    assert "Qwen" in authors
    assert "zai-org" in authors
    assert "moonshotai" in authors
    assert "MiniMaxAI" in authors
    assert "stepfun-ai" in authors
    assert "ByteDance-Seed" in authors

    # Quantization detection
    assert HuggingFaceChinaFetcher._is_derivative_or_quantization(
        "Qwen/Qwen2.5-72B-Instruct-GGUF"
    )
    assert HuggingFaceChinaFetcher._is_derivative_or_quantization(
        "deepseek-ai/DeepSeek-V3-FP8"
    )
    assert HuggingFaceChinaFetcher._is_derivative_or_quantization(
        "moonshotai/Kimi-k1.5-AWQ"
    )
    assert not HuggingFaceChinaFetcher._is_derivative_or_quantization(
        "deepseek-ai/DeepSeek-V3"
    )
    assert not HuggingFaceChinaFetcher._is_derivative_or_quantization(
        "Qwen/Qwen2.5-72B-Instruct"
    )


def test_modelscope_fetcher_org_level_polling_defaults():
    """ModelScopeFetcher must have default owners covering top Chinese AI labs."""
    from ai_security_monitor.infrastructure.fetchers.modelscope_fetcher import (
        ModelScopeFetcher,
    )

    owners = ModelScopeFetcher.DEFAULT_OWNERS
    assert "deepseek-ai" in owners
    assert "Qwen" in owners
    assert "Shanghai_AI_Laboratory" in owners
    assert "ZhipuAI" in owners
    assert "moonshotai" in owners
