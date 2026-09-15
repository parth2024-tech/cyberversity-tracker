"""
Integration and unit tests verifying enterprise top-tier pipelines for worldwide AI intelligence.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.autonomous_triage_service import (
    AutonomousTriageService,
)
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.infrastructure.analyzers.blast_radius_analyzer import (
    BlastRadiusAnalyzer,
)
from ai_security_monitor.infrastructure.analyzers.heuristic_analyzer import (
    HeuristicAnalyzer,
)


@pytest.mark.asyncio
async def test_blast_radius_ai_framework_compatibility_mode():
    """Verify that BlastRadiusAnalyzer recognizes AI items, sets blast_radius=0, and extracts frameworks."""
    analyzer = BlastRadiusAnalyzer()
    entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="vLLM: High-Throughput and Memory-Efficient Inference Engine for LLMs with PagedAttention",
        url="https://github.com/vllm-project/vllm",
        content_hash="hash_vllm_test",
        summary="vLLM supports PyTorch, HuggingFace transformers, and CUDA inference acceleration with state-of-the-art serving performance.",
        published_at=datetime.now(UTC),
        category=Category.CYBER_TOOLS,
    )

    res = await analyzer.analyze(entry)
    assert res.blast_radius_score == 0
    assert res.is_pre_cve_warning is False
    assert res.attack_archetype == "Developer AI Tool"
    assert "PyTorch" in res.affected_ecosystem or "HuggingFace" in res.affected_ecosystem
    assert "Compatible Architecture" in res.attack_vector
    assert res.weaponization_potential == "Production Ready"


@pytest.mark.asyncio
async def test_heuristic_frontier_model_scoring():
    """Verify HeuristicAnalyzer correctly classifies frontier models with high adoption velocity."""
    analyzer = HeuristicAnalyzer()
    entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning",
        url="https://github.com/deepseek-ai/DeepSeek-R1",
        content_hash="hash_deepseek_r1_test",
        summary="DeepSeek-R1 demonstrates open reasoning weights matching OpenAI o1 on math benchmarks and code generation.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )

    res = await analyzer.analyze(entry)
    assert res.threat_velocity >= 85
    assert res.attack_archetype == "AI Model Release"
    assert res.weaponization_potential == "Open Weights Available"
    assert res.blast_radius_score == 0
    assert res.is_pre_cve_warning is False


@pytest.mark.asyncio
async def test_triage_priority_scoring_precedence():
    """Verify triage service prioritizes Frontier Models (P0) over developer tools (P1) and general tech (P2)."""
    triage_svc = AutonomousTriageService()

    frontier_entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Qwen2.5-Coder-32B Open Foundation Checkpoint Released",
        url="https://huggingface.co/Qwen",
        content_hash="hash_qwen_test",
        summary="Weights released for Qwen2.5-Coder.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )
    p0 = triage_svc.calculate_priority(frontier_entry)
    assert p0 == 0

    tool_entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Ollama 0.5.8 Local Inference Runtime Update",
        url="https://ollama.com",
        content_hash="hash_ollama_test",
        summary="Local engine serving llama3.1 models.",
        published_at=datetime.now(UTC),
        category=Category.CYBER_TOOLS,
    )
    p1 = triage_svc.calculate_priority(tool_entry)
    assert p1 == 1

    general_entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Tech Policy Roundtable on Regional Silicon Investments",
        url="https://example.com/policy",
        content_hash="hash_general_test",
        summary="General policy discussion.",
        published_at=datetime.now(UTC),
        category=Category.AI_TECH,
    )
    p2 = triage_svc.calculate_priority(general_entry)
    assert p2 == 2


@pytest.mark.asyncio
async def test_triage_metadata_enrichment():
    """Verify triage queue enqueue and status tracking."""
    triage_svc = AutonomousTriageService()
    test_id = uuid4()
    enqueued = await triage_svc.enqueue(test_id, priority=0)
    assert enqueued is True
    assert triage_svc.queue_size == 1

    status = triage_svc.get_status()
    assert status["queue_size"] == 1
    assert status["total_enqueued"] == 1

    cleared = triage_svc.clear_queue()
    assert cleared == 1
    assert triage_svc.queue_size == 0
