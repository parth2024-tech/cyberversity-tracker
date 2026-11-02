"""
Unit tests for Semantic Cluster Graph & Precision Gate (Workstream B2).
Tests precision gate verification, kNN edge generation, cross-lingual story clustering,
node capping (<= 500), regional classification, REST API endpoints, and MCP tool.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.cluster_graph_service import (
    ClusterGraphService,
    cluster_graph_service,
)
from ai_security_monitor.domain.entities import Category, Entry, Source, SourceType
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.presentation.api.main import create_app
from ai_security_monitor.presentation.mcp.server import MCPServer


def test_precision_gate_verification():
    """Verify that ClusterGraphService passes the precision gate >= 0.90 with zero false positives."""
    svc = ClusterGraphService()
    assert svc.verify_precision_gate() is True


def test_region_classification():
    """Verify regional classification into US, CN, and EU/Global."""
    svc = ClusterGraphService()

    # China Corridor (Chinese characters)
    entry_cn = Entry(
        source_id=uuid4(),
        title="深度求索正式开源DeepSeek-R1推理大模型",
        url="https://weixin.qq.com/s/123",
        content_hash="h1" * 32,
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )
    assert svc.classify_region(entry_cn, source_name="Weixin / 机器之心") == "CN"

    # EU / Sovereign AI
    entry_eu = Entry(
        source_id=uuid4(),
        title="Mistral AI releases Mistral Large 2 with 128k context",
        url="https://mistral.ai/news/large-2",
        content_hash="h2" * 32,
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )
    assert svc.classify_region(entry_eu, source_name="Mistral News") == "EU/Global"

    # US / North America
    entry_us = Entry(
        source_id=uuid4(),
        title="OpenAI launches o1 reasoning model with chain of thought",
        url="https://openai.com/index/o1",
        content_hash="h3" * 32,
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )
    assert svc.classify_region(entry_us, source_name="HackerNews") == "US"


def test_velocity_heuristic():
    """Verify velocity score calculation based on recency within freshness window."""
    svc = ClusterGraphService()
    now = datetime.now(UTC)

    fresh_entry = Entry(
        source_id=uuid4(),
        title="Breaking model release",
        url="https://example.com/1",
        content_hash="h4" * 32,
        published_at=now - timedelta(hours=2),
        category=Category.AI_MODELS,
    )
    vel_fresh = svc.extract_entry_velocity(fresh_entry)
    assert 70 <= vel_fresh <= 95

    older_entry = Entry(
        source_id=uuid4(),
        title="Older paper release",
        url="https://example.com/2",
        content_hash="h5" * 32,
        published_at=now - timedelta(days=12),
        category=Category.AI_RESEARCH,
    )
    vel_older = svc.extract_entry_velocity(older_entry)
    assert 15 <= vel_older < 50


@pytest.mark.asyncio
async def test_cluster_graph_generation_and_cross_lingual_edges():
    """Verify that semantic cluster graph generates nodes, kNN edges, and cross-lingual matches."""
    now = datetime.now(UTC)

    async with SqlAlchemyUnitOfWork() as uow:
        # Create test source
        src = Source(
            name=f"Test AI Lab {uuid4().hex[:6]}",
            category=Category.AI_MODELS,
            type=SourceType.RSS,
        )
        await uow.sources.add(src)

        # 1. Chinese DeepSeek dispatch
        e1 = Entry(
            source_id=src.id,
            title="深度求索正式开源DeepSeek-R1推理大模型，强化学习突破新高度",
            url=f"https://example.com/cn/{uuid4().hex[:6]}",
            content_hash=uuid4().hex * 2,
            summary="DeepSeek-R1 推理大模型正式开源，性能比肩 o1",
            published_at=now + timedelta(minutes=5),
            category=Category.AI_MODELS,
        )
        # 2. English DeepSeek dispatch (should form a cross_lingual_match edge with e1)
        e2 = Entry(
            source_id=src.id,
            title="DeepSeek open-sources DeepSeek-R1 reasoning model, matching o1 performance",
            url=f"https://example.com/en/{uuid4().hex[:6]}",
            content_hash=uuid4().hex * 2,
            summary="DeepSeek-R1 reasoning model open sourced with full weights",
            published_at=now + timedelta(minutes=4),
            category=Category.AI_MODELS,
        )
        # 3. Mistral release (EU)
        e3 = Entry(
            source_id=src.id,
            title="Mistral AI releases Mistral Large 2 with 128k context",
            url=f"https://example.com/mistral/{uuid4().hex[:6]}",
            content_hash=uuid4().hex * 2,
            summary="Mistral Large 2 advanced frontier model with extended context",
            published_at=now + timedelta(minutes=3),
            category=Category.AI_MODELS,
        )
        # 4. Cybersecurity item (MUST be filtered out per worldwide AI ecosystem directive)
        e4 = Entry(
            source_id=src.id,
            title="Critical remote code execution vulnerability in web server",
            url=f"https://example.com/cve/{uuid4().hex[:6]}",
            content_hash=uuid4().hex * 2,
            summary="CVE-2026-9999 allows unauthorized command execution",
            published_at=now + timedelta(minutes=6),
            category=Category.CYBERSECURITY,
        )

        for entry in (e1, e2, e3, e4):
            await uow.entries.add(entry)
        await uow.commit()

        # Compute graph
        graph = await cluster_graph_service.get_graph(days=14, max_nodes=500, uow=uow)

        assert graph["precision_gate_passed"] is True
        assert graph["count_nodes"] >= 3

        # Verify e4 (cybersecurity) was filtered out
        node_ids = {n["id"] for n in graph["nodes"]}
        assert str(e4.id) not in node_ids
        assert str(e1.id) in node_ids
        assert str(e2.id) in node_ids
        assert str(e3.id) in node_ids

        # Check cross-lingual edge between e1 and e2
        cross_edges = [
            ed
            for ed in graph["edges"]
            if ed.get("type") == "cross_lingual_match"
            and {ed["source"], ed["target"]} == {str(e1.id), str(e2.id)}
        ]
        assert len(cross_edges) >= 1
        assert cross_edges[0]["similarity"] >= 0.95

        # Verify cluster summary
        clusters = graph["clusters"]
        assert len(clusters) >= 1

        # Check that e1 and e2 belong to the same cluster
        e1_node = next(n for n in graph["nodes"] if n["id"] == str(e1.id))
        e2_node = next(n for n in graph["nodes"] if n["id"] == str(e2.id))
        assert e1_node["cluster_id"] == e2_node["cluster_id"]

        # Check cluster language mix contains both zh and en
        shared_cluster = next(
            c for c in clusters if c["cluster_id"] == e1_node["cluster_id"]
        )
        assert "zh" in shared_cluster["languages"]
        assert "en" in shared_cluster["languages"]


@pytest.mark.asyncio
async def test_cluster_graph_summary_endpoint():
    """Verify high-level summary endpoint aggregation."""
    summary = await cluster_graph_service.get_summary(days=14)
    assert "total_nodes" in summary
    assert "total_edges" in summary
    assert "total_clusters" in summary
    assert "cross_lingual_cluster_rate" in summary
    assert "regional_distribution" in summary
    assert "precision_gate_passed" in summary
    assert summary["precision_gate_passed"] is True


@pytest.mark.asyncio
async def test_clusters_rest_api():
    """Verify FastAPI endpoints /api/clusters/graph and /api/clusters/summary."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Graph endpoint
        resp_graph = await client.get("/api/clusters/graph?days=14&max_nodes=100")
        assert resp_graph.status_code == 200
        data = resp_graph.json()
        assert "nodes" in data
        assert "edges" in data
        assert "clusters" in data
        assert "precision_gate_passed" in data
        assert data["precision_gate_passed"] is True

        # 2. Summary endpoint
        resp_summary = await client.get("/api/clusters/summary?days=14")
        assert resp_summary.status_code == 200
        sum_data = resp_summary.json()
        assert "total_nodes" in sum_data
        assert "regional_distribution" in sum_data


@pytest.mark.asyncio
async def test_mcp_cluster_graph_tool():
    """Verify MCP tool get_semantic_cluster_graph invocation via JSON-RPC."""
    server = MCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": "mcp-test-1",
        "method": "tools/call",
        "params": {
            "name": "get_semantic_cluster_graph",
            "arguments": {"days": 14, "max_nodes": 50, "min_similarity": 0.70},
        },
    }
    resp = await server.handle_request(req)
    assert resp is not None
    assert resp.get("id") == "mcp-test-1"
    res_str = resp["result"]["content"][0]["text"]
    parsed = json.loads(res_str)
    assert "nodes" in parsed
    assert "edges" in parsed
    assert "clusters" in parsed
    assert parsed["precision_gate_passed"] is True
