"""
Unit tests for Structured AI Entity & Benchmark Knowledge Graph (Pillar 4).
Tests deterministic entity extraction, repository persistence, MCP tools, and REST API.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.ai_entity_extractor import (
    AIEntityExtractor,
    ai_entity_extractor,
)
from ai_security_monitor.domain.entities import (
    AIEntity,
    Category,
    EntityType,
    Entry,
)
from ai_security_monitor.infrastructure.database.models import EntryModel, SourceModel
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.presentation.api.main import create_app
from ai_security_monitor.presentation.mcp.server import MCPServer


@pytest.fixture
def sample_entry() -> Entry:
    return Entry(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        source_id=uuid4(),
        title="DeepSeek-R1: Incentivizing Reasoning in LLMs via Reinforcement Learning",
        url="https://arxiv.org/abs/2501.12948",
        content_hash="c" * 64,
        summary=(
            "DeepSeek introduces DeepSeek-R1, demonstrating 79.8% on AIME 2024 and 49.2% on SWE-bench. "
            "Trained using NVIDIA H100 clusters. Code open at https://github.com/deepseek-ai/DeepSeek-R1."
        ),
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        tags=["deepseek", "reasoning", "benchmarks"],
    )


def test_ai_entity_extractor_deterministic(sample_entry: Entry):
    """Verify high-precision extraction of Models, Repos, ArXiv IDs, Benchmarks, Orgs, and Hardware."""
    entities = ai_entity_extractor.extract_entities(sample_entry)
    assert len(entities) >= 5

    type_to_entities: dict[EntityType, list[AIEntity]] = {}
    for e in entities:
        type_to_entities.setdefault(e.entity_type, []).append(e)

    # 1. Models
    assert EntityType.MODEL in type_to_entities
    model_names = [e.name for e in type_to_entities[EntityType.MODEL]]
    assert "deepseek-r1" in model_names

    # 2. Benchmarks & metric scores
    assert EntityType.BENCHMARK in type_to_entities
    benchmarks = {
        e.display_name: e.metric_value for e in type_to_entities[EntityType.BENCHMARK]
    }
    assert "AIME 2024" in benchmarks
    assert benchmarks["AIME 2024"] == "79.8%"
    assert "SWE-bench" in benchmarks
    assert benchmarks["SWE-bench"] == "49.2%"

    # 3. Repositories
    assert EntityType.REPOSITORY in type_to_entities
    repo_names = [e.name for e in type_to_entities[EntityType.REPOSITORY]]
    assert "deepseek-ai/deepseek-r1" in repo_names

    # 4. ArXiv
    assert EntityType.ARXIV in type_to_entities
    arxiv_names = [e.name for e in type_to_entities[EntityType.ARXIV]]
    assert "2501.12948" in arxiv_names

    # 5. Organizations
    assert EntityType.ORGANIZATION in type_to_entities
    org_names = [e.name for e in type_to_entities[EntityType.ORGANIZATION]]
    assert "deepseek" in org_names

    # 6. Hardware
    assert EntityType.HARDWARE in type_to_entities
    hw_names = [e.name for e in type_to_entities[EntityType.HARDWARE]]
    assert any("h100" in h for h in hw_names)


def test_ai_entity_extractor_deduplication():
    """Verify identical entity mentions are deduplicated per entry."""
    text = (
        "DeepSeek-R1 was tested against DeepSeek-R1 on MMLU-Pro (84.2%) and MMLU-Pro."
    )
    extracted = AIEntityExtractor.extract_from_text(text, entry_id=uuid4())
    models = [e for e in extracted if e.entity_type == EntityType.MODEL]
    benchmarks = [e for e in extracted if e.entity_type == EntityType.BENCHMARK]
    assert len(models) == 1
    assert len(benchmarks) == 1
    assert benchmarks[0].metric_value == "84.2%"


@pytest.mark.asyncio
async def test_entity_repository_crud_and_timeline():
    """Verify adding entities, querying by entry, querying timeline, and top entities aggregation."""
    async with SqlAlchemyUnitOfWork() as uow:
        # Create a fresh test source & entry
        source_id = str(uuid4())
        src_m = SourceModel(
            id=source_id,
            name="vLLM Project",
            url="https://github.com/vllm-project/vllm",
            category="ai_tech",
            type="github_org",
        )
        uow.session.add(src_m)

        entry_id = uuid4()
        entry_m = EntryModel(
            id=str(entry_id),
            source_id=source_id,
            title="vLLM 0.7.0 High-Throughput Inference Engine",
            url="https://github.com/vllm-project/vllm",
            content_hash=uuid4().hex + uuid4().hex,
            summary="vLLM achieves 2.5x higher throughput on RTX 4090 and H100.",
            published_at=datetime.now(UTC) - timedelta(days=2),
            category="ai_tech",
            tags=["vllm", "inference"],
        )
        uow.session.add(entry_m)
        await uow.session.flush()

        # Add entities
        e1 = AIEntity(
            entry_id=entry_id,
            entity_type=EntityType.REPOSITORY,
            name="vllm-project/vllm",
            display_name="vllm-project/vllm",
            context="High-Throughput Inference Engine",
        )
        e2 = AIEntity(
            entry_id=entry_id,
            entity_type=EntityType.HARDWARE,
            name="rtx-4090",
            display_name="RTX 4090",
            context="achieves 2.5x higher throughput on RTX 4090",
        )
        e3 = AIEntity(
            entry_id=entry_id,
            entity_type=EntityType.HARDWARE,
            name="h100",
            display_name="H100",
            context="RTX 4090 and H100",
        )

        saved = await uow.entities.add_all([e1, e2, e3])
        assert len(saved) == 3
        await uow.commit()

    async with SqlAlchemyUnitOfWork() as uow:
        # 1. Get by entry
        by_entry = await uow.entities.get_by_entry(entry_id)
        assert len(by_entry) == 3

        # 2. Query timeline
        timeline = await uow.entities.query_timeline(name="vllm", days=14)
        assert len(timeline) >= 1
        assert timeline[0]["name"] == "vllm-project/vllm"
        assert "vLLM 0.7.0" in timeline[0]["entry_title"]

        # 3. Query top entities
        top_hw = await uow.entities.get_top_entities(
            entity_type=EntityType.HARDWARE, days=14
        )
        assert len(top_hw) >= 1
        names = [t["name"] for t in top_hw]
        assert "rtx-4090" in names or "h100" in names


@pytest.mark.asyncio
async def test_mcp_server_entity_tools():
    """Verify MCP tools query_ai_entity_timeline and get_top_ai_entities."""
    server = MCPServer()

    # 1. query_ai_entity_timeline
    res_timeline = await server._execute_tool(
        "query_ai_entity_timeline",
        {"name": "vllm", "days": 14, "limit": 10},
    )
    assert not res_timeline.startswith("Error")
    data_tl = json.loads(res_timeline)
    assert isinstance(data_tl, list)

    # 2. get_top_ai_entities
    res_top = await server._execute_tool(
        "get_top_ai_entities",
        {"days": 14, "limit": 10},
    )
    assert not res_top.startswith("Error")
    data_top = json.loads(res_top)
    assert isinstance(data_top, list)


@pytest.mark.asyncio
async def test_rest_api_entity_routes():
    """Verify REST API /entities/timeline and /entities/top."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Timeline
        resp_tl = await client.get("/api/v1/entities/timeline?name=vllm&days=14")
        assert resp_tl.status_code == 200
        tl_json = resp_tl.json()
        assert "timeline" in tl_json
        assert tl_json["query"] == "vllm"

        # 2. Top
        resp_top = await client.get("/api/v1/entities/top?days=14")
        assert resp_top.status_code == 200
        top_json = resp_top.json()
        assert "entities" in top_json
