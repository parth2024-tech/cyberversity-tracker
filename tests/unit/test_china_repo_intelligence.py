"""Unit tests for China Repository Intelligence Extractor & Epistemic Profiler."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.china_repo_intelligence import (
    ChinaRepoArchetype,
    ChinaRepoIntelligenceExtractor,
    china_repo_intelligence,
)
from ai_security_monitor.presentation.api.main import create_app


def test_archetype_classification_foundation_model():
    """Verify classification of Chinese foundation models."""
    profile = china_repo_intelligence.extract_profile(
        title="deepseek-ai/DeepSeek-V3",
        description="DeepSeek-V3 is an open-source 671B parameter Mixture-of-Experts (MoE) foundation model.",
        url="https://github.com/deepseek-ai/DeepSeek-V3",
    )
    assert profile.archetype == ChinaRepoArchetype.FOUNDATION_MODEL.value
    assert "Foundation Model" in profile.archetype_label
    assert profile.lab_name is not None
    assert "DeepSeek" in profile.lab_name
    assert profile.is_official_lab is True
    assert profile.parameter_scale == "671B"


def test_archetype_classification_inference_runtime():
    """Verify classification of inference runtimes and deployment engines."""
    profile = china_repo_intelligence.extract_profile(
        title="InternLM/lmdeploy",
        description="LMDeploy is a high-throughput LLM serving runtime and quantization toolkit supporting AWQ, GGUF, and FP8 on vLLM.",
        url="https://github.com/InternLM/lmdeploy",
    )
    assert profile.archetype == ChinaRepoArchetype.INFERENCE_RUNTIME.value
    assert "Inference Runtime" in profile.archetype_label
    assert profile.lab_name is not None
    assert "Shanghai AI Lab" in profile.lab_name
    assert "AWQ" in profile.quantization_formats
    assert "GGUF" in profile.quantization_formats
    assert "FP8" in profile.quantization_formats
    assert "vLLM" in profile.serving_frameworks


def test_archetype_classification_rag_knowledge_base():
    """Verify classification of deep document layout RAG systems."""
    profile = china_repo_intelligence.extract_profile(
        title="infiniflow/ragflow",
        description="RAGFlow is an open-source RAG engine based on deep document understanding and hybrid search 知识库检索增强.",
        url="https://github.com/infiniflow/ragflow",
    )
    assert profile.archetype == ChinaRepoArchetype.RAG_KNOWLEDGE_BASE.value
    assert profile.lab_name is not None
    assert "InfiniFlow" in profile.lab_name
    assert profile.is_official_lab is True


def test_archetype_classification_agentic_system():
    """Verify classification of autonomous coding agents and workflow orchestrators."""
    profile = china_repo_intelligence.extract_profile(
        title="InternLM/MindSearch",
        description="MindSearch: An open-source autonomous multi-agent search engine framework 智能体工作流编排.",
        url="https://github.com/InternLM/MindSearch",
    )
    assert profile.archetype == ChinaRepoArchetype.AGENTIC_SYSTEM.value
    assert "Agentic System" in profile.archetype_label


def test_archetype_classification_multimodal_voice():
    """Verify classification of multimodal audio and vision models."""
    profile = china_repo_intelligence.extract_profile(
        title="FunAudioLLM/CosyVoice",
        description="Multi-lingual large voice generation model supporting zero-shot cross-lingual voice cloning 多模态语音大模型.",
        url="https://github.com/FunAudioLLM/CosyVoice",
    )
    assert profile.archetype == ChinaRepoArchetype.MULTIMODAL_VOICE.value
    assert "Multimodal" in profile.archetype_label


def test_archetype_classification_evaluation():
    """Verify classification of benchmark and evaluation suites."""
    profile = china_repo_intelligence.extract_profile(
        title="datawhalechina/self-llm",
        description="Open source LLM tutorials, benchmark evals, and fine-tuning datasets 评测基准与微调数据集.",
        url="https://github.com/datawhalechina/self-llm",
    )
    assert profile.archetype == ChinaRepoArchetype.EVAL_AND_BENCHMARK.value


def test_fact_extraction_hardware_vram_and_context():
    """Verify accurate extraction of VRAM requirements and context window sizes."""
    extractor = ChinaRepoIntelligenceExtractor()
    profile = extractor.extract_profile(
        title="QwenLM/Qwen2.5-72B-Instruct",
        description="Qwen2.5 72B model featuring 128K context tokens, runnable on 24GB VRAM with INT4 quantization or 8x H800 for full FP8 serving.",
        url="https://github.com/QwenLM/Qwen2.5",
    )
    assert profile.parameter_scale == "72B"
    assert profile.context_window == "128K"
    assert profile.vram_hardware is not None
    assert "24GB VRAM" in profile.vram_hardware or "24" in profile.vram_hardware
    assert "INT4" in profile.quantization_formats
    assert "FP8" in profile.quantization_formats
    assert profile.researcher_quality_score >= 0.70


def test_license_detection_and_quality_score():
    """Verify license identification and score adjustments."""
    profile_deepseek = china_repo_intelligence.extract_profile(
        title="deepseek-ai/DeepSeek-Coder",
        description="Licensed under DeepSeek-License. Official release with 33B parameters.",
        url="https://github.com/deepseek-ai/DeepSeek-Coder",
    )
    assert profile_deepseek.license_type == "DeepSeek License"
    assert profile_deepseek.is_official_lab is True
    assert profile_deepseek.researcher_quality_score >= 0.75

    profile_awesome = china_repo_intelligence.extract_profile(
        title="awesome-chinese-ai-models",
        description="Awesome curated list of Chinese models 收藏大全",
        url="https://github.com/someone/awesome-chinese-ai-models",
    )
    # Link farm should have lower score
    assert profile_awesome.researcher_quality_score <= 0.60


@pytest.mark.asyncio
async def test_china_trending_api_filtering():
    """Verify /api/china/trending supports archetype and lab query filters."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Base trending request
        resp = await client.get("/api/china/trending?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "trending_repositories" in data
        assert "filter" in data

        # 2. Archetype filter query
        resp_arch = await client.get("/api/china/trending?archetype=rag_knowledge_base")
        assert resp_arch.status_code == 200
        data_arch = resp_arch.json()
        assert data_arch["filter"]["archetype"] == "rag_knowledge_base"

        # 3. Lab filter query
        resp_lab = await client.get("/api/china/trending?lab=deepseek")
        assert resp_lab.status_code == 200
        data_lab = resp_lab.json()
        assert data_lab["filter"]["lab"] == "deepseek"


@pytest.mark.asyncio
async def test_china_overview_archetype_breakdown():
    """Verify /api/china/overview contains archetype breakdown and trending repos."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/china/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "archetype_breakdown" in data
        assert isinstance(data["archetype_breakdown"], dict)
        assert "trending_repositories" in data
