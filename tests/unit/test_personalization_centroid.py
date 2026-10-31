"""
Unit tests for Active Personalization Loop and Rocchio Vector Centroid (Pillar 2).
Verifies positive vaulted and negative dismissed feedback loops, dynamic preference vectors,
and triage priority scoring integration.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ai_security_monitor.application.services.triage_scoring_pipeline import (
    ScoringPipeline,
    VaultAffinitySignal,
)
from ai_security_monitor.application.services.vault_feedback_service import (
    VaultFeedbackService,
    vault_feedback_service,
)
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.infrastructure.analyzers.embedding_service import (
    embedding_service,
)
from ai_security_monitor.presentation.api.main import app


def test_rocchio_centroid_calculation_and_penalty():
    """Verify Rocchio formula: c_user = c_pos - alpha * c_neg normalized to unit length."""
    service = VaultFeedbackService(rocchio_alpha=0.35)

    # 1. Positive entries (Vaulted interest: vLLM, inference engines)
    entry_pos1 = Entry(
        source_id=uuid4(),
        title="vLLM high throughput inference engine with PagedAttention",
        url="https://github.com/vllm-project/vllm",
        summary="Ultra-fast serving library for open-weight foundation models.",
        content_hash="h_pos1",
        published_at=datetime.now(UTC),
        category=Category.CYBER_TOOLS,
        metadata={"is_important": True},
    )
    entry_pos2 = Entry(
        source_id=uuid4(),
        title="SGLang fast inference runtime and structured decoding",
        url="https://github.com/sgl-project/sglang",
        summary="Inference server optimizing memory and latency for LLMs.",
        content_hash="h_pos2",
        published_at=datetime.now(UTC),
        category=Category.CYBER_TOOLS,
        metadata={"is_important": True},
    )

    # 2. Negative entries (Dismissed / purged)
    entry_neg1 = Entry(
        source_id=uuid4(),
        title="Crypto coin token ICO blockchain launch",
        url="https://example.com/crypto-coin",
        summary="A new token project launching decentralized coin currency.",
        content_hash="h_neg1",
        published_at=datetime.now(UTC),
        category=Category.CYBER_TOOLS,
        is_purged=True,
    )

    # Mock unit of work factory
    mock_uow = AsyncMock()
    mock_uow.entries.list.side_effect = [
        [entry_pos1, entry_pos2],  # Positive vaulted
        [entry_neg1],  # Negative dismissed
    ]
    mock_factory = MagicMock(return_value=mock_uow)
    mock_uow.__aenter__.return_value = mock_uow
    mock_uow.__aexit__.return_value = None

    service._uow_factory = mock_factory

    import asyncio

    asyncio.run(service.refresh_profile(force=True))

    summary = service.get_centroid_summary()
    assert summary["total_vaulted"] == 2
    assert summary["total_dismissed"] == 1
    assert summary["centroid_active"] is True
    assert summary["centroid_dimension"] == 384
    assert service.user_centroid is not None

    centroid_norm = math.sqrt(sum(x * x for x in service.user_centroid))
    assert pytest.approx(centroid_norm, rel=1e-3) == 1.0

    # 3. Candidate evaluation:
    # A candidate about inference serving should have high affinity
    cand_good = Entry(
        source_id=uuid4(),
        title="llama.cpp local quantized inference serving and kernel optimizations",
        url="https://github.com/ggerganov/llama.cpp",
        summary="High-speed inference on CPU and Apple Silicon with zero latency.",
        content_hash="h_cand_good",
        published_at=datetime.now(UTC),
        category=Category.CYBER_TOOLS,
    )
    affinity_good = service.calculate_affinity(cand_good)
    assert affinity_good > 0.40

    # A candidate matching dismissed crypto topic should have lower affinity
    cand_bad = Entry(
        source_id=uuid4(),
        title="Decentralized token yield farming crypto wallet",
        url="https://example.com/wallet-token",
        summary="Blockchain token finance protocols.",
        content_hash="h_cand_bad",
        published_at=datetime.now(UTC),
        category=Category.CYBER_TOOLS,
    )
    affinity_bad = service.calculate_affinity(cand_bad)
    assert affinity_bad < affinity_good


def test_triage_scoring_boost_from_personal_affinity():
    """Triage scoring pipeline elevates priority score when personal affinity is high."""
    service = VaultFeedbackService()
    # Inject a preference vector aligned with frontier reasoning models
    vec = embedding_service.embed_text(
        "DeepSeek-R1 test-time compute reasoning architecture"
    )
    service.set_user_centroid(vec)
    service._total_vaulted = 5

    signal = VaultAffinitySignal()

    # Candidate aligned with preference
    aligned_entry = Entry(
        source_id=uuid4(),
        title="Reinforcement learning incentives for extended reasoning steps",
        url="https://arxiv.org/abs/2501.99999",
        summary="Empirical evaluation of test-time compute scaling in reasoning LLMs.",
        content_hash="h_aligned",
        published_at=datetime.now(UTC),
        category=Category.AI_RESEARCH,
    )

    # Use the test service for evaluation
    old_singleton = vault_feedback_service._user_centroid
    try:
        vault_feedback_service._user_centroid = service.user_centroid
        vault_feedback_service._total_vaulted = 5

        score, reason = signal.evaluate(aligned_entry)
        assert score >= 0.50
        assert "Vault preferences" in reason

        pipeline = ScoringPipeline()
        result = pipeline.score(aligned_entry)
        assert result.composite_score > 60.0
        assert "vault_affinity" in result.breakdown
    finally:
        vault_feedback_service._user_centroid = old_singleton


def test_vault_profile_api_endpoints():
    """Verify /api/vault/profile and /api/vault/profile/refresh REST endpoints."""
    client = TestClient(app)

    # GET /api/vault/profile
    res = client.get("/api/vault/profile")
    assert res.status_code == 200
    data = res.json()
    assert "total_vaulted" in data
    assert "centroid_active" in data
    assert "rocchio_alpha" in data

    # POST /api/vault/profile/refresh
    res_refresh = client.post("/api/vault/profile/refresh")
    assert res_refresh.status_code == 200
    refresh_data = res_refresh.json()
    assert refresh_data["status"] == "success"
    assert "profile" in refresh_data
