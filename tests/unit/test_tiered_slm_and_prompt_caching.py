"""
Unit tests for Pillar 3: Tiered Local SLM Routing & Ephemeral Prompt Caching.
Tests tiered routing, fast-fail circuit breaker, prompt caching prefix headers,
resilient small model JSON extraction, token savings telemetry, and SLM translation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.claim_verifier import (
    STATIC_CLAIM_VERIFIER_SYSTEM_PROMPT,
    build_claim_verifier_prompt_messages,
)
from ai_security_monitor.application.services.deep_analysis_service import (
    STATIC_DOSSIER_SYSTEM_PROMPT,
    build_deep_analysis_prompt_messages,
)
from ai_security_monitor.application.services.llm_receipt_service import (
    LLMReceiptService,
)
from ai_security_monitor.application.services.translation_service import (
    TranslationService,
)
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.infrastructure.analyzers.llm_analyzer import LLMAnalyzer
from ai_security_monitor.infrastructure.analyzers.prompt_cache import (
    build_cached_prompt_messages,
)
from ai_security_monitor.infrastructure.analyzers.slm_circuit_breaker import (
    CircuitState,
    SLMCircuitBreaker,
    slm_circuit_breaker,
)
from ai_security_monitor.infrastructure.analyzers.structured_output_parser import (
    clean_markdown_fences,
    extract_balanced_json_object,
    normalize_slm_analysis_payload,
    parse_slm_json,
    remove_trailing_commas,
)
from ai_security_monitor.presentation.api.main import create_app


@pytest.fixture
def sample_ai_entry() -> Entry:
    return Entry(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        source_id=uuid4(),
        title="vLLM 0.7.0 Released with SGLang Kernel Integration",
        url="https://github.com/vllm-project/vllm/releases/tag/v0.7.0",
        content_hash="c" * 64,
        summary="High-throughput inference engine adds FlashAttention-3 and FP8 paged attention.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        tags=["vllm", "inference", "fp8", "cuda"],
        metadata={"region": "global"},
    )


# ============================================================================
# 1. Structured Output Guardrails for Small Models
# ============================================================================


def test_clean_markdown_fences():
    """Verify markdown code fence stripping."""
    raw = '```json\n{"attack_vector": "GRPO"}\n```'
    assert clean_markdown_fences(raw) == '{"attack_vector": "GRPO"}'

    raw_no_lang = '```\n{"attack_vector": "FlashAttention"}\n```'
    assert clean_markdown_fences(raw_no_lang) == '{"attack_vector": "FlashAttention"}'


def test_remove_trailing_commas():
    """Verify trailing commas before closing braces/brackets are removed."""
    raw = '{"item1": 1, "item2": 2, }'
    assert remove_trailing_commas(raw) == '{"item1": 1, "item2": 2}'

    raw_arr = '{"list": [1, 2, 3, ]}'
    assert remove_trailing_commas(raw_arr) == '{"list": [1, 2, 3]}'


def test_extract_balanced_json_object():
    """Verify scanning for balanced outermost curly braces amid commentary."""
    commentary = (
        "Here is the generated analysis:\n\n"
        '{"attack_vector": "Paged Attention", "threat_velocity": 85}\n\n'
        "Hope this helps your research!"
    )
    extracted = extract_balanced_json_object(commentary)
    assert extracted == '{"attack_vector": "Paged Attention", "threat_velocity": 85}'


def test_parse_slm_json_messy_outputs():
    """Verify multi-stage parser recovers from messy small-model outputs."""
    # Case 1: Markdown code block with preamble and trailing comma
    messy_1 = (
        "Sure, here is the JSON telemetry:\n"
        "```json\n"
        "{\n"
        '  "attack_vector": "Test-Time Compute",\n'
        '  "threat_velocity": 90,\n'
        '  "severity_index": 85,\n'
        "}\n"
        "```\n"
        "Let me know if you need anything else!"
    )
    parsed_1 = parse_slm_json(messy_1)
    assert parsed_1 is not None
    assert parsed_1["attack_vector"] == "Test-Time Compute"
    assert parsed_1["threat_velocity"] == 90

    # Case 2: Single quotes used by small model
    messy_2 = "{'attack_vector': 'Speculative Decoding', 'threat_velocity': 75}"
    parsed_2 = parse_slm_json(messy_2)
    assert parsed_2 is not None
    assert parsed_2["attack_vector"] == "Speculative Decoding"


def test_normalize_slm_analysis_payload_clamping():
    """Verify numerical scores are clamped between 1-100 and default fallbacks applied."""
    raw = {
        "attack_vector": "Sparse MoE Routing",
        "threat_velocity": 150,  # Out of bounds (>100)
        "severity_index": -10,  # Out of bounds (<1)
        "blast_radius_score": "80",
    }
    normalized = normalize_slm_analysis_payload(raw, default_title="MoE Paper")
    assert normalized["threat_velocity"] == 100
    assert normalized["severity_index"] == 1
    assert normalized["blast_radius_score"] == 80
    assert normalized["attack_vector"] == "Sparse MoE Routing"
    assert normalized["is_pre_cve_warning"] is False


# ============================================================================
# 2. Fast-Fail Circuit Breaker for Local SLM
# ============================================================================


def test_circuit_breaker_transitions():
    """Verify circuit breaker transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    breaker = SLMCircuitBreaker(cooldown_seconds=1.0, connect_timeout=0.1)
    assert breaker.state == CircuitState.CLOSED
    assert not breaker.is_tripped

    # Trip breaker on connection refusal
    breaker.record_failure("Connection refused on port 11434")
    assert breaker.state == CircuitState.OPEN
    assert breaker.is_tripped
    assert breaker.cooldown_remaining > 0.0

    # Fast-fail check: when OPEN, returns False immediately without network
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(breaker.check_availability())
        assert res is False
    finally:
        loop.close()

    # Manual reset
    breaker.reset()
    assert breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_circuit_breaker_availability_offline():
    """Verify check_availability trips when endpoint is unreachable."""
    breaker = SLMCircuitBreaker(cooldown_seconds=60.0, connect_timeout=0.1)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        is_avail = await breaker.check_availability(
            endpoint="http://localhost:11434", force_probe=True
        )

    assert is_avail is False
    assert breaker.state == CircuitState.OPEN
    assert breaker.is_tripped


# ============================================================================
# 3. Prompt Prefix & Ephemeral Cache Structuring
# ============================================================================


def test_prompt_caching_isolation_and_headers():
    """Ensure static system instructions are isolated at index 0 with provider cache headers."""
    static_prompt = "STATIC_INSTRUCTION_SET_V1"
    dynamic_user = "Title: DeepSeek-V3 Release\nSummary: 671B MoE architecture"

    # 1. Anthropic provider: cache_control ephemeral block
    anthropic_msgs = build_cached_prompt_messages(
        static_system=static_prompt,
        dynamic_user=dynamic_user,
        provider="anthropic",
        enable_caching=True,
    )
    assert len(anthropic_msgs) == 2
    assert anthropic_msgs[0]["role"] == "system"
    assert isinstance(anthropic_msgs[0]["content"], list)
    assert anthropic_msgs[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert anthropic_msgs[1]["role"] == "user"
    assert anthropic_msgs[1]["content"] == dynamic_user

    # 2. OpenAI / Groq / Ollama: static system prompt at index 0 for native prefix caching
    openai_msgs = build_cached_prompt_messages(
        static_system=static_prompt,
        dynamic_user=dynamic_user,
        provider="openai",
    )
    assert len(openai_msgs) == 2
    assert openai_msgs[0]["role"] == "system"
    assert openai_msgs[0]["content"] == static_prompt
    assert openai_msgs[1]["role"] == "user"
    assert openai_msgs[1]["content"] == dynamic_user


def test_claim_verifier_and_deep_analysis_prompt_messages(sample_ai_entry: Entry):
    """Verify claim verifier and deep analysis expose cached prompt builders."""
    claim_msgs = build_claim_verifier_prompt_messages(
        claim="HumanEval score 90.2%",
        context="Evaluation results indicate HumanEval 90.2% on pass@1.",
        provider="anthropic",
    )
    assert len(claim_msgs) == 2
    assert claim_msgs[0]["content"][0]["text"] == STATIC_CLAIM_VERIFIER_SYSTEM_PROMPT

    dossier_msgs = build_deep_analysis_prompt_messages(
        entry=sample_ai_entry,
        provider="openai",
    )
    assert len(dossier_msgs) == 2
    assert dossier_msgs[0]["content"] == STATIC_DOSSIER_SYSTEM_PROMPT
    assert "vLLM" in dossier_msgs[1]["content"]


# ============================================================================
# 4. Tiered Model Routing & Circuit-Breaker Fallback
# ============================================================================


@pytest.mark.asyncio
async def test_llm_analyzer_tier1_local_slm_success(sample_ai_entry: Entry):
    """Verify Tier 1 uses local SLM and records 'local_slm' execution tier receipt."""
    slm_circuit_breaker.reset()
    mock_receipt_service = MagicMock()
    mock_receipt_service.check_or_record_attempt = AsyncMock(
        return_value=("key_1", MagicMock(status="pending"), True)
    )
    mock_receipt_service.record_success = AsyncMock()

    analyzer = LLMAnalyzer(
        config={"provider": "tiered", "tier": "local_slm"},
        receipt_service=mock_receipt_service,
    )

    mock_slm_resp = {
        "attack_vector": "PagedAttention CUDA Kernels",
        "risk_assessment": "High inference throughput improvement",
        "mitigation": "Deploy vLLM 0.7.0 with FP8",
        "threat_velocity": 85,
        "severity_index": 80,
        "blast_radius_score": 75,
        "affected_ecosystem": ["vLLM", "CUDA", "PyTorch"],
    }

    with patch.object(
        analyzer, "_call_ollama", new_callable=AsyncMock, return_value=mock_slm_resp
    ):
        res = await analyzer.analyze(sample_ai_entry)

    assert res.attack_vector == "PagedAttention CUDA Kernels"
    assert res.threat_velocity == 85
    mock_receipt_service.record_success.assert_called_once()
    call_kwargs = mock_receipt_service.record_success.call_args[1]
    assert call_kwargs["execution_tier"] == "local_slm"


@pytest.mark.asyncio
async def test_llm_analyzer_circuit_breaker_offline_fallback(sample_ai_entry: Entry):
    """Verify offline SLM immediately trips breaker and falls back to HeuristicAnalyzer."""
    slm_circuit_breaker.reset()
    mock_receipt_service = MagicMock()
    mock_receipt_service.check_or_record_attempt = AsyncMock(
        return_value=("key_2", MagicMock(status="pending"), True)
    )
    mock_receipt_service.record_failure = AsyncMock()

    analyzer = LLMAnalyzer(
        config={"provider": "tiered", "tier": "local_slm"},
        receipt_service=mock_receipt_service,
    )

    # Simulate connection refusal on Ollama
    with patch(
        "httpx.AsyncClient.post",
        side_effect=httpx.ConnectError("Connection refused on port 11434"),
    ):
        res = await analyzer.analyze(sample_ai_entry)

    # Circuit breaker should now be tripped
    assert slm_circuit_breaker.is_tripped
    # Fallback to heuristic analyzer produced a valid result
    assert res.attack_vector is not None
    assert res.threat_velocity >= 1
    mock_receipt_service.record_failure.assert_called_once()


@pytest.mark.asyncio
async def test_llm_analyzer_tier2_cloud_frontier_routing(sample_ai_entry: Entry):
    """Verify high-priority item routes to Cloud Frontier with prompt cache tracking."""
    sample_ai_entry.metadata = {"force_frontier": True}
    mock_receipt_service = MagicMock()
    mock_receipt_service.check_or_record_attempt = AsyncMock(
        return_value=("key_3", MagicMock(status="pending"), True)
    )
    mock_receipt_service.record_success = AsyncMock()

    analyzer = LLMAnalyzer(
        config={"provider": "groq", "tier": "cloud_frontier"},
        receipt_service=mock_receipt_service,
    )
    analyzer.client = MagicMock()

    mock_cloud_resp = {
        "attack_vector": "Frontier GRPO Reasoning",
        "risk_assessment": "Substantial paradigm shift in test-time compute",
        "mitigation": "Fine-tune with verifiable rewards",
        "threat_velocity": 95,
        "severity_index": 92,
        "blast_radius_score": 88,
    }

    # Simulate 350 cached tokens on cloud API call
    with patch.object(
        analyzer,
        "_call_groq",
        new_callable=AsyncMock,
        return_value=(mock_cloud_resp, 350, 0),
    ):
        res = await analyzer.analyze(sample_ai_entry)

    assert res.attack_vector == "Frontier GRPO Reasoning"
    mock_receipt_service.record_success.assert_called_once()
    call_kwargs = mock_receipt_service.record_success.call_args[1]
    assert call_kwargs["execution_tier"] == "cloud_cached"
    assert call_kwargs["cache_read_input_tokens"] == 350


# ============================================================================
# 5. Token Savings & Cost Avoidance Telemetry
# ============================================================================


@pytest.mark.asyncio
async def test_receipt_service_cost_savings_telemetry():
    """Verify LLMReceiptService calculates token and estimated dollar savings."""
    mock_receipt_repo = MagicMock()
    mock_receipt_repo.get_tier_stats = AsyncMock(
        return_value={
            "tier_counts": {"local_slm": 25, "cloud_cached": 10, "cloud_uncached": 5},
            "local_slm_count": 25,
            "cloud_cached_count": 10,
            "cloud_uncached_count": 5,
            "total_cache_read_tokens": 15000,
            "total_cache_creation_tokens": 5000,
        }
    )

    mock_uow = MagicMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    mock_uow.receipts = mock_receipt_repo

    service = LLMReceiptService(uow_factory=lambda: mock_uow)
    telemetry = await service.get_cost_savings_telemetry()

    assert telemetry["local_slm_count"] == 25
    assert telemetry["cloud_cached_count"] == 10
    assert telemetry["cache_read_input_tokens"] == 15000
    assert telemetry["estimated_dollars_saved"] > 0.0


@pytest.mark.asyncio
async def test_stats_token_savings_endpoint():
    """Verify GET /api/stats/token-savings endpoint returns JSON telemetry."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/stats/token-savings")
        assert resp.status_code == 200
        data = resp.json()
        assert "local_slm_count" in data
        assert "cloud_cached_count" in data
        assert "cache_read_input_tokens" in data
        assert "estimated_dollars_saved" in data


# ============================================================================
# 6. Local SLM Translation with Circuit Breaker
# ============================================================================


def test_translation_service_local_slm_circuit_breaker_behavior():
    """Verify translation service skips local SLM when circuit breaker is tripped."""
    slm_circuit_breaker.record_failure("Offline")
    assert slm_circuit_breaker.is_tripped

    trans_service = TranslationService()
    # When breaker is tripped, _translate_via_slm returns None immediately
    res = trans_service._translate_via_slm(
        "DeepSeek 发布全新模型", source_lang="zh-cn", target="en"
    )
    assert res is None

    slm_circuit_breaker.reset()
