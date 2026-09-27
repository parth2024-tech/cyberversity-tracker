"""
Tests for Permanent Important Vault and Deep Technical Analysis Dossier.
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.deep_analysis_service import (
    DeepAnalysisService,
    deep_analysis_service,
)
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.presentation.api.main import create_app


def test_deep_analysis_service_model_weights():
    service = DeepAnalysisService()
    entry = Entry(
        id=uuid4(),
        source_id="src-1",
        published_at=datetime.utcnow(),
        title="DeepSeek-R1-Distill-Qwen-32B: Reasoning Benchmark Breakthrough",
        url="https://github.com/deepseek-ai/DeepSeek-R1",
        content_hash="hash-ds-1",
        summary="DeepSeek-R1 32B model with 128k context window and FP8 / GGUF quantization support across vLLM.",
        category=Category.AI_MODELS,
    )

    dossier = service.generate_dossier(entry)
    assert dossier["entry_id"] == str(entry.id)
    assert "DeepSeek-R1" in dossier["title"]
    assert dossier["category"] == "ai_models"
    assert "32B" in dossier["compute_profile"]["parameter_scale"]
    assert (
        "128K" in dossier["executive_summary"] or "32B" in dossier["executive_summary"]
    )
    assert "KV-Cache" in dossier["architectural_deep_dive"]
    assert len(dossier["benchmarks"]) >= 3
    assert any("AIME" in b["benchmark"] for b in dossier["benchmarks"])
    assert len(dossier["actionable_checklist"]) >= 3
    assert (
        "vLLM" in dossier["actionable_checklist"][1]
        or "FP8" in dossier["actionable_checklist"][1]
    )
    assert dossier["is_important"] is True
    assert "Reasoning" in dossier["importance_reason"]


def test_deep_analysis_service_inference_runtime():
    entry = Entry(
        id=uuid4(),
        source_id="src-tools",
        published_at=datetime.utcnow(),
        title="vLLM: High-Throughput and Memory-Efficient LLM Serving Engine",
        url="https://github.com/vllm-project/vllm",
        content_hash="hash-vllm-1",
        summary="PagedAttention and continuous batching runtime optimized for CUDA GPU clusters.",
        category=Category.CYBER_TOOLS,
    )

    dossier = deep_analysis_service.generate_dossier(entry)
    assert "Continuous Batching" in dossier["architectural_deep_dive"]
    assert "Paged Attention" in dossier["architectural_deep_dive"]
    assert any("Throughput" in b["benchmark"] for b in dossier["benchmarks"])
    assert "Critical Inference Runtime" in dossier["importance_reason"]


def test_deep_analysis_service_arxiv_paper():
    entry = Entry(
        id=uuid4(),
        source_id="src-arxiv",
        published_at=datetime.utcnow(),
        title="Scaling Test-Time Compute in Mathematical Reasoning Models",
        url="https://arxiv.org/abs/2602.01234",
        content_hash="hash-arxiv-1",
        summary="A comprehensive empirical study of search trees and verification policies during inference.",
        category=Category.AI_RESEARCH,
    )

    dossier = deep_analysis_service.generate_dossier(entry)
    assert "seminal" in dossier["executive_summary"].lower()
    assert "Empirical Methodology" in dossier["architectural_deep_dive"]
    assert any("Methodology" in c for c in dossier["actionable_checklist"])


def test_deep_analysis_service_silicon_hardware():
    entry = Entry(
        id=uuid4(),
        source_id="src-hw",
        published_at=datetime.utcnow(),
        title="NVIDIA Blackwell B200 NVLink 5 Architecture and FP4 Tensor Core System",
        url="https://nvidia.com/blackwell",
        content_hash="hash-hw-1",
        summary="Next-generation silicon delivering 20 petaflops of FP4 inference throughput with 8TB/s memory bandwidth.",
        category=Category.CYBER_TOOLS,
    )

    dossier = deep_analysis_service.generate_dossier(entry)
    assert "accelerator hardware" in dossier["executive_summary"].lower() or "silicon" in dossier["executive_summary"].lower()
    assert "Low-Precision Tensor Compute" in dossier["architectural_deep_dive"]
    assert "Interconnect & Memory Bandwidth" in dossier["architectural_deep_dive"]
    assert any("Memory Bandwidth" in b["benchmark"] for b in dossier["benchmarks"])
    assert any("interconnect" in c.lower() for c in dossier["actionable_checklist"])
    assert "Hardware Accelerator" in dossier["importance_reason"]


def test_deep_analysis_service_multi_agent_system():
    entry = Entry(
        id=uuid4(),
        source_id="src-agent",
        published_at=datetime.utcnow(),
        title="LangGraph and CrewAI Multi-Agent Swarm Orchestration with MCP Server Support",
        url="https://github.com/langchain-ai/langgraph",
        content_hash="hash-agent-1",
        summary="Stateful multi-agent execution framework with persistent checkpoints and Model Context Protocol tooling.",
        category=Category.GITHUB_TRENDING,
    )

    dossier = deep_analysis_service.generate_dossier(entry)
    assert "agentic execution" in dossier["executive_summary"].lower()
    assert "Stateful Graph Execution" in dossier["architectural_deep_dive"]
    assert "Strict Tool-Calling Contracts" in dossier["architectural_deep_dive"]
    assert any("GAIA" in b["benchmark"] or "ToolBench" in b["benchmark"] for b in dossier["benchmarks"])
    assert any("mcp" in c.lower() or "schema" in c.lower() for c in dossier["actionable_checklist"])
    assert "Autonomous Multi-Agent" in dossier["importance_reason"]


def test_deep_analysis_service_embodied_robotics():
    entry = Entry(
        id=uuid4(),
        source_id="src-robot",
        published_at=datetime.utcnow(),
        title="Humanoid Locomotion and Manipulation via Vision-Language-Action Policy Rollouts",
        url="https://arxiv.org/abs/2603.09999",
        content_hash="hash-robot-1",
        summary="An embodied robotics policy capable of continuous real-time 30Hz closed-loop physical interaction.",
        category=Category.AI_RESEARCH,
    )

    dossier = deep_analysis_service.generate_dossier(entry)
    assert "physical artificial intelligence" in dossier["executive_summary"].lower() or "robotic" in dossier["executive_summary"].lower()
    assert "Vision-Language-Action" in dossier["architectural_deep_dive"]
    assert "Real-Time Latency Envelopes" in dossier["architectural_deep_dive"]
    assert "Physical AI" in dossier["importance_reason"]


def test_deep_analysis_service_sovereign_ai():
    entry = Entry(
        id=uuid4(),
        source_id="src-sov",
        published_at=datetime.utcnow(),
        title="National Sovereign AI Strategy: Domestic Cluster Expansion and Governance Framework",
        url="https://sovereign.ai/national-strategy",
        content_hash="hash-sov-1",
        summary="National deployment of sovereign compute infrastructure ensuring strict data residency compliance.",
        category=Category.AI_TECH,
    )

    dossier = deep_analysis_service.generate_dossier(entry)
    assert "sovereign" in dossier["executive_summary"].lower()
    assert "Independent Foundation Compute" in dossier["architectural_deep_dive"]
    assert "Cultural & Linguistic Alignment" in dossier["architectural_deep_dive"]
    assert "Global Sovereign AI" in dossier["importance_reason"]


@pytest.mark.asyncio
async def test_repository_permanent_vault_exemption_from_purge(test_uow):
    uow = test_uow
    # 1. Create a normal old entry (older than 7 days)
    old_time = datetime.utcnow() - timedelta(days=12)
    normal_old = Entry(
        id=uuid4(),
        source_id=uuid4(),
        published_at=old_time,
        title="Regular Temporary News Dispatch",
        url="https://example.com/temp-news",
        content_hash=f"hash-temp-{uuid4().hex[:8]}",
        summary="A regular dispatch that should be cleaned up by rolling retention.",
        category=Category.AI_TECH,
        metadata={"is_important": False},
    )
    normal_old.fetched_at = old_time
    await uow.entries.add(normal_old)

    # 2. Create a vaulted old entry (older than 7 days, but is_important=True)
    vaulted_old = Entry(
        id=uuid4(),
        source_id=uuid4(),
        published_at=old_time,
        title="Seminal Foundation Breakthrough (Vault Kept)",
        url="https://example.com/landmark-breakthrough",
        content_hash=f"hash-vault-{uuid4().hex[:8]}",
        summary="Landmark open-weights milestone that must survive all rolling purges permanently.",
        category=Category.AI_MODELS,
        metadata={
            "is_important": True,
            "importance_reason": "Frontier Landmark Milestone",
        },
    )
    vaulted_old.fetched_at = old_time
    await uow.entries.add(vaulted_old)
    await uow.commit()

    # Run purge older than 7 days
    purged = await uow.entries.purge_old_entries(older_than_days=7)
    await uow.commit()
    assert purged >= 1

    # Verify normal entry was purged, but vaulted entry remains intact
    check_normal = await uow.entries.get(normal_old.id)
    check_vaulted = await uow.entries.get(vaulted_old.id)

    assert check_normal is None, "Normal 12-day old entry should have been purged!"
    assert check_vaulted is not None, "Vaulted entry MUST survive rolling purge permanently!"
    assert check_vaulted.metadata.get("is_important") is True


@pytest.mark.asyncio
async def test_vault_toggle_and_user_notes_persistence():
    entry_id = uuid4()
    async with SqlAlchemyUnitOfWork() as uow:
        entry = Entry(
            id=entry_id,
            source_id=uuid4(),
            published_at=datetime.utcnow(),
            title="SGLang High-Performance Serving Framework",
            url="https://github.com/sgl-project/sglang",
            content_hash=f"hash-sglang-{uuid4().hex[:8]}",
            summary="Fast serving framework for Large Language Models and multi-modal models.",
            category=Category.CYBER_TOOLS,
        )
        await uow.entries.add(entry)
        await uow.commit()

    # 1. Toggle importance on
    async with SqlAlchemyUnitOfWork() as uow:
        updated = await uow.entries.toggle_importance(
            entry_id, reason="User Selected Key Tool"
        )
        await uow.commit()
        assert updated.metadata["is_important"] is True
        assert updated.metadata["importance_reason"] == "User Selected Key Tool"
        assert "saved_at" in updated.metadata

    # 2. Save personal user notes
    async with SqlAlchemyUnitOfWork() as uow:
        noted = await uow.entries.save_user_notes(
            entry_id,
            "Deployed on 4x RTX 4090 cluster with RadixAttention. Latency dropped by 45%.",
        )
        await uow.commit()
        assert "4x RTX 4090" in noted.metadata["user_notes"]
        assert "notes_updated_at" in noted.metadata

    # 3. Query with important_only filter
    async with SqlAlchemyUnitOfWork() as uow:
        filtered = await uow.entries.list(
            filters=EntryFilters(important_only=True),
            pagination=PaginationParams(limit=50, offset=0),
        )
        ids = [e.id for e in filtered]
        assert entry_id in ids


@pytest.mark.asyncio
async def test_api_vault_and_deep_analysis_endpoints():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Fetch entries to get an active ID
        res = await client.get("/api/entries?limit=10")
        assert res.status_code == 200
        data = res.json()
        assert len(data["entries"]) > 0
        target_entry = data["entries"][0]
        target_id = target_entry["id"]

        # 1. Test POST /api/entries/{id}/toggle-vault
        toggle_res = await client.post(
            f"/api/entries/{target_id}/toggle-vault?reason=Critical+Reasoning+Model"
        )
        assert toggle_res.status_code == 200
        toggle_data = toggle_res.json()
        assert toggle_data["status"] == "ok"
        assert "is_important" in toggle_data

        # 2. Test POST /api/entries/{id}/notes
        notes_payload = {
            "notes": "Verified locally: Token-per-second throughput is exceptional on modern TensorRT kernels."
        }
        notes_res = await client.post(
            f"/api/entries/{target_id}/notes", json=notes_payload
        )
        assert notes_res.status_code == 200
        notes_data = notes_res.json()
        assert notes_data["status"] == "ok"
        assert "Verified locally" in notes_data["user_notes"]

        # 3. Test GET /api/entries/{id}/deep-analysis
        analysis_res = await client.get(f"/api/entries/{target_id}/deep-analysis")
        assert analysis_res.status_code == 200
        analysis_data = analysis_res.json()
        assert analysis_data["entry_id"] == target_id
        assert "executive_summary" in analysis_data
        assert "architectural_deep_dive" in analysis_data
        assert "compute_profile" in analysis_data
        assert "benchmarks" in analysis_data
        assert "actionable_checklist" in analysis_data
        assert "Verified locally" in analysis_data["user_notes"]

        # 4. Test GET /api/entries?important_only=true
        vault_res = await client.get("/api/entries?important_only=true&limit=20")
        assert vault_res.status_code == 200
        vault_data = vault_res.json()
        assert "entries" in vault_data
        assert any(e["id"] == target_id for e in vault_data["entries"])


@pytest.mark.asyncio
async def test_manual_entry_deletion_and_batch_cleanup(test_uow):
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/entries?limit=10")
        assert res.status_code == 200
        entries = res.json()["entries"]
        assert len(entries) >= 2

        entry1_id = entries[0]["id"]
        entry2_id = entries[1]["id"]

        # Test single manual delete
        del_single = await client.delete(f"/api/entries/{entry1_id}")
        assert del_single.status_code == 200
        del_data = del_single.json()
        assert del_data["success"] is True
        assert del_data["deleted_id"] == entry1_id

        # Verify entry1 is gone
        get_res = await client.get(f"/api/entries/{entry1_id}")
        assert get_res.status_code == 404

        # Test batch delete
        batch_del = await client.post(
            "/api/entries/batch-delete",
            json={"entry_ids": [entry2_id], "hard_delete": True},
        )
        assert batch_del.status_code == 200
        batch_data = batch_del.json()
        assert batch_data["success"] is True
        assert batch_data["deleted_count"] == 1

        # Verify entry2 is gone
        get_res2 = await client.get(f"/api/entries/{entry2_id}")
        assert get_res2.status_code == 404


@pytest.mark.asyncio
async def test_purge_stale_entries_by_category(test_uow):
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Check retention count for specific category
        ret_res = await client.get("/api/stats/retention?days=0&categories=ai_models")
        assert ret_res.status_code == 200
        ret_data = ret_res.json()
        assert "candidates_count" in ret_data

        # Purge only specific category
        purge_res = await client.post(
            "/api/stats/purge?days=0&hard_delete=true&include_vaulted=true&categories=ai_models"
        )
        assert purge_res.status_code == 200
        purge_data = purge_res.json()
        assert purge_data["categories"] == ["ai_models"]


