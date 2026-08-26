"""
Unit tests for Autonomous LLM Triage Service and Queue Worker.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.autonomous_triage_service import (
    AutonomousTriageService,
)
from ai_security_monitor.domain.entities import (
    Analysis,
    AnalysisModel,
    Category,
    Entry,
)
from ai_security_monitor.infrastructure.analyzers.base import AnalysisResult


@pytest.mark.asyncio
async def test_triage_queue_deduplication():
    """Test that duplicate entry IDs are rejected by the triage queue."""
    service = AutonomousTriageService()
    test_id = uuid4()

    assert await service.enqueue(test_id) is True
    assert service.queue_size == 1

    # Second enqueue of same ID should return False and not increment queue
    assert await service.enqueue(test_id) is False
    assert service.queue_size == 1


@pytest.mark.asyncio
async def test_triage_service_status():
    """Test telemetry reporting of queue state."""
    service = AutonomousTriageService()
    test_id = uuid4()
    await service.enqueue(test_id)

    status = service.get_status()
    assert "queue_size" in status
    assert status["queue_size"] == 1
    assert status["total_enqueued"] == 1
    assert status["total_completed"] == 0
    assert "model" in status


@pytest.mark.asyncio
async def test_triage_worker_process_entry():
    """Test processing an entry upgrades analysis from heuristic to ollama."""
    test_entry_id = uuid4()
    from datetime import datetime
    mock_entry = Entry(
        id=test_entry_id,
        source_id=uuid4(),
        title="Novel Pre-CVE LLM Jailbreak Technique",
        url="https://arxiv.org/abs/2608.12345",
        content_hash="a" * 64,
        summary="Researchers present AST injection breaking LLM tool barriers.",
        category=Category.AI_RESEARCH,
        published_at=datetime.utcnow(),
    )

    mock_analysis = Analysis(
        entry_id=test_entry_id,
        attack_vector="Heuristic vector",
        risk_assessment="Heuristic risk",
        mitigation="Heuristic mitigation",
        threat_velocity=75,
        severity_index=60,
        blast_radius_score=40,
        model=AnalysisModel.HEURISTIC,
    )

    mock_uow = MagicMock()
    mock_uow.__aenter__.return_value = mock_uow
    mock_uow.__aexit__.return_value = None
    mock_uow.entries.get = AsyncMock(return_value=mock_entry)
    mock_uow.analyses.get_by_entry = AsyncMock(return_value=mock_analysis)
    mock_uow.analyses.update = AsyncMock()
    mock_uow.commit = AsyncMock()

    service = AutonomousTriageService(uow_factory=lambda: mock_uow)

    mock_llm_result = AnalysisResult(
        entry_id=test_entry_id,
        attack_vector="Dynamic Prompt AST Injection via unvalidated tool call parameter",
        risk_assessment="High risk: Arbitrary shell execution inside runtime container",
        mitigation="Implement AST input whitelist; run tool functions in microVM isolation",
        threat_velocity=88,
        severity_index=85,
        blast_radius_score=65,
        affected_ecosystem=["LangChain", "vLLM"],
        is_pre_cve_warning=True,
        attack_archetype="Jailbreak",
        weaponization_potential="PoC Verified",
        model=AnalysisModel.OLLAMA,
    )

    mock_analyzer = MagicMock()
    mock_analyzer.analyze = AsyncMock(return_value=mock_llm_result)

    await service._process_entry(test_entry_id, mock_analyzer)

    # Verify analysis was updated with real LLM data
    assert mock_analysis.model == AnalysisModel.OLLAMA
    assert mock_analysis.threat_velocity == 88
    assert mock_analysis.attack_vector == "Dynamic Prompt AST Injection via unvalidated tool call parameter"
    assert mock_analysis.is_pre_cve_warning is True
    assert "LangChain" in mock_analysis.affected_ecosystem
    mock_uow.analyses.update.assert_called_once_with(mock_analysis)
    mock_uow.commit.assert_called_once()
