"""
Unit tests for VaultFeedbackService.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.vault_feedback_service import (
    VaultFeedbackService,
)
from ai_security_monitor.domain.entities import (
    Analysis,
    AnalysisModel,
    Category,
    Entry,
)


@pytest.fixture
def mock_uow():
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.entries = MagicMock()
    return uow


@pytest.fixture
def sample_vault_entries():
    e1 = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="DeepSeek R1 Open Weights Architecture",
        url="https://github.com/deepseek-ai/DeepSeek-R1",
        content_hash="h1",
        summary="DeepSeek reasoning model with test-time compute reinforcement learning.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        analysis=Analysis(
            id=uuid4(),
            entry_id=uuid4(),
            attack_vector="N/A",
            risk_assessment="Low",
            mitigation="Sandbox",
            threat_velocity=40,
            severity_index=50,
            affected_ecosystem=["vLLM", "SGLang"],
            model=AnalysisModel.HEURISTIC,
        ),
    )
    e2 = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="vLLM High Performance Inference Engine",
        url="https://github.com/vllm-project/vllm",
        content_hash="h2",
        summary="Distributed inference runtime optimizing PagedAttention throughput.",
        published_at=datetime.now(UTC),
        category=Category.AI_TECH,
    )
    return [e1, e2]


@pytest.mark.asyncio
async def test_vault_feedback_initial_affinity():
    service = VaultFeedbackService()
    candidate = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Candidate Article",
        url="https://example.com/candidate",
        content_hash="hc",
        summary="Test summary",
        published_at=datetime.now(UTC),
        category=Category.AI_TECH,
    )
    # When no entries are vaulted, affinity should be 0.0
    assert service.calculate_affinity(candidate) == 0.0


@pytest.mark.asyncio
async def test_vault_feedback_refresh_and_affinity(mock_uow, sample_vault_entries):
    mock_uow.entries.list = AsyncMock(return_value=sample_vault_entries)
    service = VaultFeedbackService(uow_factory=lambda: mock_uow, cache_ttl_seconds=60)

    await service.refresh_profile(force=True)
    assert service._total_vaulted == 2
    assert "deepseek" in service._keyword_weights
    assert "vllm" in service._ecosystem_weights

    # Candidate with high keyword, ecosystem, and category overlap
    candidate = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="DeepSeek R1 Inference on vLLM and SGLang",
        url="https://example.com/deepseek-vllm",
        content_hash="hc1",
        summary="Optimizing reasoning models using PagedAttention on distributed clusters.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        analysis=Analysis(
            id=uuid4(),
            entry_id=uuid4(),
            attack_vector="N/A",
            risk_assessment="Low",
            mitigation="Sandbox",
            threat_velocity=30,
            severity_index=40,
            affected_ecosystem=["vllm", "sglang"],
            model=AnalysisModel.HEURISTIC,
        ),
    )

    affinity = service.calculate_affinity(candidate)
    assert affinity > 0.3
    assert affinity <= 1.0


@pytest.mark.asyncio
async def test_vault_feedback_ttl_cache(mock_uow, sample_vault_entries):
    mock_uow.entries.list = AsyncMock(return_value=sample_vault_entries)
    service = VaultFeedbackService(uow_factory=lambda: mock_uow, cache_ttl_seconds=300)

    # First refresh calls list
    await service.refresh_profile(force=False)
    assert mock_uow.entries.list.call_count == 1

    # Second refresh within TTL does nothing
    await service.refresh_profile(force=False)
    assert mock_uow.entries.list.call_count == 1

    # Force bypasses TTL
    await service.refresh_profile(force=True)
    assert mock_uow.entries.list.call_count == 2


@pytest.mark.asyncio
async def test_vault_feedback_refresh_error(mock_uow):
    mock_uow.entries.list = AsyncMock(side_effect=Exception("Database lock error"))
    service = VaultFeedbackService(uow_factory=lambda: mock_uow)

    # Should not raise exception, logs warning
    await service.refresh_profile(force=True)
    assert service._total_vaulted == 0
