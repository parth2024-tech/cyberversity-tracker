"""Unit tests for idempotent LLM receipts, cache reuse, and retry caps."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.llm_receipt_service import (
    LLMReceiptService,
    compute_receipt_logical_key,
)
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.infrastructure.analyzers.llm_analyzer import LLMAnalyzer
from ai_security_monitor.infrastructure.database.connection import db_manager


def make_test_entry(title: str = "Test Model Release") -> Entry:
    return Entry(
        id=uuid4(),
        source_id=uuid4(),
        title=title,
        url=f"https://example.com/{title.replace(' ', '_')}",
        content_hash=f"hash_{title}",
        summary=f"Summary of {title}",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        metadata={"priority_score": 85},
    )


def test_receipt_logical_key_determinism_and_version_invalidation():
    """Logical key must be deterministic for identical inputs and change when prompt_version changes."""
    entry_id = uuid4()
    content_hash = "abc123hash"
    provider = "ollama"
    model = "qwen2:0.5b"

    key1 = compute_receipt_logical_key(
        entry_id=entry_id,
        content_hash=content_hash,
        provider=provider,
        model=model,
        prompt_version="v1.0",
    )
    key2 = compute_receipt_logical_key(
        entry_id=entry_id,
        content_hash=content_hash,
        provider=provider,
        model=model,
        prompt_version="v1.0",
    )
    # Determinism
    assert key1 == key2

    # Intentional cache invalidation on prompt bump
    key_v2 = compute_receipt_logical_key(
        entry_id=entry_id,
        content_hash=content_hash,
        provider=provider,
        model=model,
        prompt_version="v2.0",
    )
    assert key1 != key_v2

    # Different model yields different key
    key_other_model = compute_receipt_logical_key(
        entry_id=entry_id,
        content_hash=content_hash,
        provider=provider,
        model="llama3.1:8b",
        prompt_version="v1.0",
    )
    assert key1 != key_other_model


@pytest.mark.asyncio
async def test_receipt_lifecycle_and_poison_retry_limit():
    """Receipt service must record attempts, store successes, and cap retries at max_attempts (3)."""
    # Ensure database is initialized
    await db_manager.init_db()

    entry = make_test_entry("DeepSeek-R1 Open Release")
    receipt_service = LLMReceiptService()

    # Attempt 1: First try -> should_execute is True
    key, receipt1, should_call1 = await receipt_service.check_or_record_attempt(
        entry=entry,
        provider="ollama",
        model="qwen2:0.5b",
        prompt_version="v1.0",
        max_attempts=3,
    )
    assert should_call1 is True
    assert receipt1.status == "pending"
    assert receipt1.attempts == 1

    # Simulate failure 1
    await receipt_service.record_failure(key, "Connection timeout to Ollama")
    rec_after_fail1 = await receipt_service.get_receipt(key)
    assert rec_after_fail1 is not None
    assert rec_after_fail1.status == "failed"
    assert rec_after_fail1.is_retryable is True

    # Attempt 2: Retry -> should_execute is True
    _, receipt2, should_call2 = await receipt_service.check_or_record_attempt(
        entry=entry,
        provider="ollama",
        model="qwen2:0.5b",
        prompt_version="v1.0",
        max_attempts=3,
    )
    assert should_call2 is True
    assert receipt2.attempts == 2

    # Simulate failure 2
    await receipt_service.record_failure(key, "Out of VRAM error")

    # Attempt 3: Retry -> should_execute is True (final allowable attempt)
    _, receipt3, should_call3 = await receipt_service.check_or_record_attempt(
        entry=entry,
        provider="ollama",
        model="qwen2:0.5b",
        prompt_version="v1.0",
        max_attempts=3,
    )
    assert should_call3 is True
    assert receipt3.attempts == 3

    # Simulate failure 3
    await receipt_service.record_failure(key, "Malformed JSON syntax error")

    # Attempt 4: Exceeded max retries (3) -> poison entry detected!
    _, receipt4, should_call4 = await receipt_service.check_or_record_attempt(
        entry=entry,
        provider="ollama",
        model="qwen2:0.5b",
        prompt_version="v1.0",
        max_attempts=3,
    )
    assert should_call4 is False
    assert receipt4.status == "failed"
    assert receipt4.is_retryable is False

    is_poison = await receipt_service.is_poison_entry(
        entry, provider="ollama", model="qwen2:0.5b"
    )
    assert is_poison is True


@pytest.mark.asyncio
async def test_llm_analyzer_receipt_cache_reuse():
    """LLMAnalyzer must cache successful LLM outputs and return cached results without re-calling provider."""
    await db_manager.init_db()

    entry = make_test_entry("vLLM FP8 Inference Optimization")
    receipt_service = LLMReceiptService()

    analyzer = LLMAnalyzer(
        config={"provider": "ollama", "ollama_model": "qwen2:0.5b"},
        receipt_service=receipt_service,
    )

    mock_llm_response = {
        "attack_vector": "FP8 Kernel Acceleration",
        "risk_assessment": "High throughput inference milestone",
        "mitigation": "Deploy with vLLM 0.6+",
        "threat_velocity": 88,
        "severity_index": 82,
        "blast_radius_score": 75,
        "affected_ecosystem": ["vLLM", "PyTorch", "CUDA"],
        "is_pre_cve_warning": False,
        "attack_archetype": "Inference Runtime",
        "weaponization_potential": "Production Ready",
    }

    # First call: LLM provider is invoked
    with patch.object(analyzer, "_call_ollama", new_callable=AsyncMock) as mock_ollama:
        mock_ollama.return_value = mock_llm_response

        res1 = await analyzer.analyze(entry)
        assert mock_ollama.call_count == 1
        assert res1.attack_vector == "FP8 Kernel Acceleration"
        assert res1.threat_velocity == 88

    # Second call: LLM provider must NOT be invoked, cached receipt is reused!
    with patch.object(
        analyzer, "_call_ollama", new_callable=AsyncMock
    ) as mock_ollama_second:
        res2 = await analyzer.analyze(entry)
        assert mock_ollama_second.call_count == 0
        assert res2.attack_vector == "FP8 Kernel Acceleration"
        assert res2.threat_velocity == 88


@pytest.mark.asyncio
async def test_llm_analyzer_poison_entry_halts_llm_calls():
    """Poison entries that failed 3 times must immediately fallback to Heuristic without calling LLM."""
    await db_manager.init_db()

    entry = make_test_entry("Poison Malformed Article")
    receipt_service = LLMReceiptService()

    analyzer = LLMAnalyzer(
        config={"provider": "ollama", "ollama_model": "qwen2:0.5b"},
        receipt_service=receipt_service,
    )

    # Fail 3 times
    for _ in range(3):
        with patch.object(
            analyzer, "_call_ollama", side_effect=RuntimeError("Provider 500 Crash")
        ):
            await analyzer.analyze(entry)

    # 4th call: _call_ollama should NOT even be entered
    with patch.object(
        analyzer, "_call_ollama", new_callable=AsyncMock
    ) as mock_never_called:
        res = await analyzer.analyze(entry)
        assert mock_never_called.call_count == 0
        # Returned graceful heuristic fallback
        assert res.entry_id == entry.id
