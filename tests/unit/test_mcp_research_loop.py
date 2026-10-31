"""
Unit tests for Autonomous Research Loop MCP Tool (Step A.1 / Pillar 4).
Tests:
1. Tool definition registration in TOOLS_REGISTRY and schema conformance.
2. Input validation for query parameter.
3. Multi-source hybrid retrieval (sqlite-vec KNN, entity graph timeline, heat & velocity ranking).
4. Strict 14-day freshness window enforcement.
5. Structured research dossier synthesis with all 4 required sections.
6. JSON-RPC 2.0 MCP server integration.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from ai_security_monitor.application.services.autonomous_research_service import (
    AutonomousResearchService,
)
from ai_security_monitor.domain.entities import (
    AIEntity,
    Analysis,
    Category,
    EntityType,
    Entry,
)
from ai_security_monitor.presentation.mcp.server import TOOLS_REGISTRY, MCPServer


@pytest.fixture
def sample_entry_fresh() -> Entry:
    """A fresh entry within the 14-day window with entities and decision brief."""
    eid = UUID("11111111-1111-1111-1111-111111111111")
    analysis = Analysis(
        id=uuid4(),
        entry_id=eid,
        attack_vector="Inference Latency Optimization",
        threat_velocity=85,
        severity_index=75,
        blast_radius_score=70,
        risk_assessment="Performance breakthrough",
        mitigation="Evaluate deployment",
        decision_brief={
            "event_summary": "vLLM 0.7.2 introduces chunked prefill and multi-tier KV cache.",
            "technical_significance": "Reduces time-to-first-token (TTFT) by 45% on A100/H100 clusters.",
            "novelty_assessment": {
                "novelty_type": "INCREMENTAL_UPDATE",
                "summary": "Builds directly on previous vLLM paged attention scheduler.",
            },
            "recommended_action": "TEST_IN_SANDBOX",
        },
    )
    entities = [
        AIEntity(
            entry_id=eid,
            entity_type=EntityType.REPOSITORY,
            name="vllm-project/vllm",
            display_name="vLLM Project",
            context="High-throughput LLM serving engine",
        ),
        AIEntity(
            entry_id=eid,
            entity_type=EntityType.MODEL,
            name="deepseek-r1",
            display_name="DeepSeek-R1",
            context="Reasoning foundation model",
        ),
        AIEntity(
            entry_id=eid,
            entity_type=EntityType.BENCHMARK,
            name="swe-bench",
            display_name="SWE-bench",
            metric_value="49.2%",
            context="SWE-bench evaluation score",
        ),
    ]
    return Entry(
        id=eid,
        source_id=uuid4(),
        title="vLLM 0.7.2: High-Performance Inference Engine with Chunked Prefill",
        url="https://github.com/vllm-project/vllm/releases/tag/v0.7.2",
        content_hash="1" * 64,
        summary="vLLM 0.7.2 release improves serving latency and adds native DeepSeek-R1 support.",
        published_at=datetime.now(UTC) - timedelta(days=2),
        category=Category.AI_TECH,
        tags=["vllm", "inference", "deepseek"],
        analysis=analysis,
        entities=entities,
    )


@pytest.fixture
def sample_entry_stale() -> Entry:
    """A stale entry published 20 days ago (must be filtered out by 14-day freshness guard)."""
    eid = UUID("99999999-9999-9999-9999-999999999999")
    return Entry(
        id=eid,
        source_id=uuid4(),
        title="Historical AI Milestone from Last Month",
        url="https://example.com/stale-news",
        content_hash="9" * 64,
        summary="Stale archive dump older than 14 days.",
        published_at=datetime.now(UTC) - timedelta(days=20),
        category=Category.AI_MODELS,
        tags=["stale"],
    )


# ==============================================================================
# 1. MCP Tool Registration & Schema Tests
# ==============================================================================


def test_mcp_tool_registration():
    """Verify run_autonomous_research_loop is registered in TOOLS_REGISTRY."""
    tool = next(
        (t for t in TOOLS_REGISTRY if t["name"] == "run_autonomous_research_loop"),
        None,
    )
    assert tool is not None
    props = tool["inputSchema"]["properties"]
    assert "query" in props
    assert "max_sources" in props
    assert "include_entities" in props
    assert tool["inputSchema"]["required"] == ["query"]


@pytest.mark.asyncio
async def test_mcp_tool_empty_query_validation():
    """Empty or whitespace query returns a descriptive error message."""
    server = MCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 101,
        "method": "tools/call",
        "params": {
            "name": "run_autonomous_research_loop",
            "arguments": {"query": "   "},
        },
    }
    resp = await server.handle_request(req)
    assert resp is not None
    content = resp["result"]["content"][0]["text"]
    assert "Error: 'query' parameter is required" in content


# ==============================================================================
# 2. Hybrid Retrieval Pipeline Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_hybrid_retrieval_semantic_and_entity_fusion(sample_entry_fresh: Entry):
    """Test multi-source retrieval fusing vector KNN, entity knowledge graph, and heat ranking."""
    service = AutonomousResearchService(max_freshness_days=14)

    mock_uow = MagicMock()
    # Mock sqlite-vec executing query returning row for sample_entry_fresh
    mock_vec_row = (str(sample_entry_fresh.id), 0.25)
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_vec_row]

    mock_uow.session.execute = AsyncMock(return_value=mock_result)
    mock_uow.entries.get = AsyncMock(return_value=sample_entry_fresh)
    mock_uow.entries.list = AsyncMock(return_value=[sample_entry_fresh])

    # Mock entity timeline match
    mock_uow.entities.query_timeline = AsyncMock(
        return_value=[
            {
                "entry_id": sample_entry_fresh.id,
                "entity_type": "model",
                "name": "deepseek-r1",
                "display_name": "DeepSeek-R1",
                "metric_value": "49.2%",
                "context": "vLLM DeepSeek-R1 serving benchmark",
                "entry_title": sample_entry_fresh.title,
                "entry_url": sample_entry_fresh.url,
            }
        ]
    )

    retrieval = await service.retrieve_hybrid_context(
        query="Analyze recent breakthroughs in test-time compute and vLLM",
        max_sources=5,
        include_entities=True,
        uow=mock_uow,
    )

    assert len(retrieval["entries"]) == 1
    assert retrieval["entries"][0].id == sample_entry_fresh.id
    assert len(retrieval["matched_entities"]) >= 1

    scores = retrieval["scores"][str(sample_entry_fresh.id)]
    assert scores["semantic"] > 0.0
    assert scores["entity"] > 0.0
    assert scores["velocity"] > 0.0
    assert scores["combined"] > 0.0


# ==============================================================================
# 3. Freshness Window Invariant Test
# ==============================================================================


@pytest.mark.asyncio
async def test_freshness_window_strictly_enforced(
    sample_entry_fresh: Entry, sample_entry_stale: Entry
):
    """Verify items older than 14 days are completely omitted from the research dossier."""
    service = AutonomousResearchService(max_freshness_days=14)

    mock_uow = MagicMock()
    # Simulate vector query returning both fresh and stale items
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        (str(sample_entry_fresh.id), 0.1),
        (str(sample_entry_stale.id), 0.05),
    ]
    mock_uow.session.execute = AsyncMock(return_value=mock_result)

    async def mock_get(eid):
        if eid == sample_entry_fresh.id:
            return sample_entry_fresh
        if eid == sample_entry_stale.id:
            return sample_entry_stale
        return None

    mock_uow.entries.get = AsyncMock(side_effect=mock_get)
    mock_uow.entries.list = AsyncMock(return_value=[sample_entry_fresh, sample_entry_stale])
    mock_uow.entities.query_timeline = AsyncMock(return_value=[])

    retrieval = await service.retrieve_hybrid_context(
        query="test stale filter",
        max_sources=10,
        include_entities=False,
        uow=mock_uow,
    )

    entry_ids = [e.id for e in retrieval["entries"]]
    assert sample_entry_fresh.id in entry_ids
    assert sample_entry_stale.id not in entry_ids, "Stale entry (> 14 days) leaked through guard!"


# ==============================================================================
# 4. Structured Research Dossier Synthesis Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_dossier_synthesis_all_four_sections(sample_entry_fresh: Entry):
    """Verify that synthesized dossier contains all 4 mandatory sections."""
    service = AutonomousResearchService(max_freshness_days=14)

    mock_uow = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [(str(sample_entry_fresh.id), 0.2)]
    mock_uow.session.execute = AsyncMock(return_value=mock_result)
    mock_uow.entries.get = AsyncMock(return_value=sample_entry_fresh)
    mock_uow.entries.list = AsyncMock(return_value=[sample_entry_fresh])
    mock_uow.entities.query_timeline = AsyncMock(return_value=[])

    report = await service.run_research_loop(
        query="Analyze vLLM chunked prefill optimization",
        max_sources=5,
        include_entities=True,
        uow=mock_uow,
    )

    # 1. Header & Executive Summary
    assert "# 🔬 Autonomous AI Research Dossier: Analyze vLLM chunked prefill optimization" in report
    assert "## 📌 Executive Summary" in report
    assert "**Freshness Guard:** ≤ 14 Days (Active)" in report

    # 2. Synthesized Findings & Technical Implications
    assert "## ⚙️ Synthesized Findings & Technical Implications" in report
    assert "vLLM 0.7.2" in report
    assert "What Happened:" in report
    assert "Technical Significance:" in report
    assert "Decision Vector:" in report
    assert "Inference / Engine Stack:" in report

    # 3. Corroborating Evidence & Knowledge Graph Entities
    assert "## 🌐 Corroborating Evidence & Knowledge Graph Entities" in report
    assert "| Entity Name | Type | Metric / Benchmark Value | Source Context |" in report
    assert "DeepSeek-R1" in report
    assert "49.2%" in report

    # 4. Source Citations & References
    assert "## 📚 Source Citations & References" in report
    assert f"**Entry UUID:** `{sample_entry_fresh.id}`" in report
    assert sample_entry_fresh.url in report


# ==============================================================================
# 5. Full MCP Server JSON-RPC 2.0 Integration Test
# ==============================================================================


@pytest.mark.asyncio
async def test_mcp_server_run_autonomous_research_loop_rpc(sample_entry_fresh: Entry):
    """Verify standard MCP client call to run_autonomous_research_loop via JSON-RPC 2.0."""
    server = MCPServer()

    with patch(
        "ai_security_monitor.application.services.autonomous_research_service.AutonomousResearchService.run_research_loop",
        new=AsyncMock(return_value="# 🔬 Autonomous AI Research Dossier: Test Topic\n\n## 📌 Executive Summary\nSuccess"),
    ):
        req = {
            "jsonrpc": "2.0",
            "id": 999,
            "method": "tools/call",
            "params": {
                "name": "run_autonomous_research_loop",
                "arguments": {
                    "query": "Test Topic",
                    "max_sources": 5,
                    "include_entities": True,
                },
            },
        }
        resp = await server.handle_request(req)
        assert resp is not None
        assert resp["id"] == 999
        content = resp["result"]["content"][0]["text"]
        assert "# 🔬 Autonomous AI Research Dossier: Test Topic" in content
        assert "## 📌 Executive Summary" in content
