"""
Unit tests for LLMAnalyzer.
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import (
    AnalysisModel,
    Category,
    Entry,
)
from ai_security_monitor.infrastructure.analyzers.llm_analyzer import LLMAnalyzer


@pytest.fixture
def sample_entry():
    return Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="DeepSeek R1 Model Card & Technical Report",
        url="https://github.com/deepseek-ai/DeepSeek-R1",
        content_hash="h_llm",
        summary="Large-scale reasoning model trained using reinforcement learning.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        tags=["deepseek", "reasoning", "rl"],
    )


def test_llm_analyzer_init():
    analyzer = LLMAnalyzer(config={"provider": "ollama", "ollama_model": "qwen2:0.5b"})
    assert analyzer.provider == "ollama"
    assert analyzer.analyzer_type == "llm_ollama"
    assert analyzer.model == AnalysisModel.OLLAMA


def test_llm_analyzer_init_gateway():
    analyzer = LLMAnalyzer(config={"provider": "gateway"})
    analyzer._init_gateway()
    assert analyzer.gateway_host == "http://localhost:20128/v1"
    assert analyzer._use_gateway is True


def test_llm_analyzer_build_prompt(sample_entry):
    analyzer = LLMAnalyzer(config={"provider": "ollama"})
    prompt = analyzer._build_prompt(sample_entry)
    assert "DeepSeek R1 Model Card" in prompt
    assert "Strict JSON format required" in prompt
    assert "attack_vector" in prompt


@pytest.mark.asyncio
async def test_llm_analyzer_call_ollama_success():
    analyzer = LLMAnalyzer(config={"provider": "ollama"})
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(
        return_value={
            "response": '{"attack_vector": "Test-Time Compute", "risk_assessment": "Frontier milestone", "mitigation": "Deploy via vLLM", "threat_velocity": 90, "severity_index": 95, "blast_radius_score": 85, "affected_ecosystem": ["vLLM"], "is_pre_cve_warning": false, "attack_archetype": "Frontier Foundation Model", "weaponization_potential": "Production Ready"}'
        }
    )

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        res = await analyzer._call_ollama("test prompt")
        assert res["attack_vector"] == "Test-Time Compute"
        assert res["severity_index"] == 95


@pytest.mark.asyncio
async def test_llm_analyzer_call_ollama_regex_fallback():
    """Verify JSON extraction when model returns markdown or text surrounding JSON."""
    analyzer = LLMAnalyzer(config={"provider": "ollama"})
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    raw = 'Here is the analysis:\n```json\n{"attack_vector": "Reasoning Model", "severity_index": 80}\n```\nHope this helps!'
    mock_resp.json = MagicMock(return_value={"response": raw})

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        res = await analyzer._call_ollama("test prompt")
        assert res["attack_vector"] == "Reasoning Model"
        assert res["severity_index"] == 80


@pytest.mark.asyncio
async def test_llm_analyzer_call_ollama_fallback_to_qwen():
    """When primary model fails, should fallback to qwen2:0.5b."""
    analyzer = LLMAnalyzer(
        config={"provider": "ollama", "ollama_model": "mistral:latest"}
    )
    mock_fail = MagicMock()
    mock_fail.raise_for_status.side_effect = RuntimeError("Primary model unavailable")

    mock_ok = MagicMock()
    mock_ok.raise_for_status = MagicMock()
    mock_ok.json.return_value = {
        "response": '{"attack_vector": "Fallback model", "severity_index": 60}'
    }

    with patch("httpx.AsyncClient.post", side_effect=[mock_fail, mock_ok]):
        res = await analyzer._call_ollama("test prompt")
        assert res["attack_vector"] == "Fallback model"


@pytest.mark.asyncio
async def test_llm_analyzer_call_gateway_success():
    analyzer = LLMAnalyzer(config={"provider": "gateway"})
    analyzer._init_gateway()

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"attack_vector": "Gateway Test", "severity_index": 88}'
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        res = await analyzer._call_gateway("test prompt")
        assert res["attack_vector"] == "Gateway Test"
        assert res["severity_index"] == 88


@pytest.mark.asyncio
async def test_llm_analyzer_call_groq_success():
    analyzer = LLMAnalyzer(config={"provider": "ollama"})
    analyzer.groq_model = "llama-3.3-70b-versatile"
    analyzer.client = MagicMock()

    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(
        {"attack_vector": "Groq Fast Path", "severity_index": 92}
    )
    mock_res = MagicMock()
    mock_res.choices = [mock_choice]
    analyzer.client.chat.completions.create.return_value = mock_res

    res = await analyzer._call_groq("test prompt")
    assert res["attack_vector"] == "Groq Fast Path"
    assert res["severity_index"] == 92


@pytest.mark.asyncio
async def test_llm_analyzer_analyze_success(sample_entry):
    analyzer = LLMAnalyzer(config={"provider": "ollama"})
    fake_json = {
        "attack_vector": "Test-Time Compute Scaling via GRPO",
        "risk_assessment": "Breakthrough in open-weights reasoning capability",
        "mitigation": "Quantize to FP8 and serve using vLLM",
        "threat_velocity": 92,
        "severity_index": 95,
        "blast_radius_score": 88,
        "affected_ecosystem": ["vLLM", "SGLang", "PyTorch"],
        "is_pre_cve_warning": False,
        "attack_archetype": "Frontier Foundation Model",
        "weaponization_potential": "Production Ready",
    }

    with patch.object(analyzer, "_call_ollama", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = fake_json
        analysis = await analyzer.analyze(sample_entry)

        assert analysis.attack_vector == "Test-Time Compute Scaling via GRPO"
        assert analysis.severity_index == 95
        assert analysis.threat_velocity == 92
        assert "vLLM" in analysis.affected_ecosystem
        assert analysis.model == AnalysisModel.OLLAMA


@pytest.mark.asyncio
async def test_llm_analyzer_analyze_fallback_to_heuristic(sample_entry):
    analyzer = LLMAnalyzer(config={"provider": "ollama"})

    with patch.object(
        analyzer, "_call_ollama", side_effect=Exception("Ollama offline")
    ):
        analysis = await analyzer.analyze(sample_entry)
        # Should fallback gracefully to HeuristicAnalyzer without crashing
        assert analysis is not None
        assert analysis.model == AnalysisModel.HEURISTIC
        assert analysis.severity_index > 0
