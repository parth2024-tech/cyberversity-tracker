"""
Unit tests for the upgraded China Intelligence Corridor v3 components:
- ChinaTokenShield (invariant placeholder protection & verifier)
- ChinaDeduplicationService (pure-Python Chinese bi-gram SimHash & Jaccard)
- CisaEpssService (CISA KEV caching, EPSS scoring, NVD links)
- ModelScopeFetcher & HuggingFaceChinaFetcher
"""

from unittest.mock import AsyncMock, patch

import pytest

from ai_security_monitor.application.services.china_dedup_service import (
    ChinaDeduplicationService,
)
from ai_security_monitor.application.services.china_token_shield import (
    ChinaTokenShield,
)
from ai_security_monitor.application.services.cisa_epss_service import (
    CisaEpssService,
)
from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.huggingface_china_fetcher import (
    HuggingFaceChinaFetcher,
)
from ai_security_monitor.infrastructure.fetchers.modelscope_fetcher import (
    ModelScopeFetcher,
)


class TestChinaTokenShield:
    """Tests for the ChinaTokenShield invariant protection protocol."""

    def test_shield_and_unshield_roundtrip(self):
        shield = ChinaTokenShield()
        text = "DeepSeek-V3与Qwen2.5-72B在代码评估中修复了CVE-2026-18492，托管于deepseek-ai/DeepSeek-V3。"

        shielded, mapping = shield.shield(text)

        # Check placeholders were created
        assert "⟦" in shielded and "⟧" in shielded
        assert len(mapping) >= 3

        # Verify all placeholders exist in shielded text
        is_valid, missing = shield.verify(shielded, mapping)
        assert is_valid is True
        assert missing == []

        # Restore original text
        restored = shield.unshield(shielded, mapping)
        assert "DeepSeek-V3" in restored
        assert "Qwen2.5-72B" in restored
        assert "CVE-2026-18492" in restored
        assert "deepseek-ai/DeepSeek-V3" in restored

    def test_verify_detects_dropped_placeholder(self):
        shield = ChinaTokenShield()
        text = "Qwen2.5-Coder-32B 发布了，包含 CVE-2026-9999。"
        shielded, mapping = shield.shield(text)

        # Simulate broken translation dropping one placeholder
        corrupted = "Qwen released a new model without the security issue."
        is_valid, missing = shield.verify(corrupted, mapping)
        assert is_valid is False
        assert len(missing) == len(mapping)

    def test_empty_text_handling(self):
        shield = ChinaTokenShield()
        shielded, mapping = shield.shield("")
        assert shielded == ""
        assert mapping == {}
        assert shield.unshield("", {}) == ""
        assert shield.verify("", {}) == (True, [])


class TestChinaDeduplicationService:
    """Tests for pure-Python Chinese bi-gram deduplication and SimHash."""

    def test_canonicalize_url(self):
        dedup = ChinaDeduplicationService()
        raw_url = "https://www.qbitai.com/article/1234.html?utm_source=wechat&spm=100.200&ref=feed"
        canonical = dedup.canonicalize_url(raw_url)
        assert canonical == "https://qbitai.com/article/1234.html"

    def test_chinese_fingerprint_filtering(self):
        dedup = ChinaDeduplicationService()
        text = "通义千问发布了新的开源大模型与推理框架"
        fp = dedup.extract_fingerprint(text)

        # Semantic keywords should be captured as bi-grams
        assert "通义" in fp or "千问" in fp
        assert "开源" in fp
        assert "模型" in fp
        # Grammatical particle '了' should not appear standalone
        assert "了" not in fp

    def test_jaccard_similarity(self):
        dedup = ChinaDeduplicationService()
        text1 = "DeepSeek发布DeepSeek-V3大模型，性能超越Llama-3.1"
        text2 = "DeepSeek宣布推出DeepSeek-V3大模型，多项性能优于Llama-3.1"
        text3 = "苹果公司今天发布了最新款iPhone手机与手表产品"

        fp1 = dedup.extract_fingerprint(text1)
        fp2 = dedup.extract_fingerprint(text2)
        fp3 = dedup.extract_fingerprint(text3)

        sim_high = dedup.jaccard_similarity(fp1, fp2)
        sim_low = dedup.jaccard_similarity(fp1, fp3)

        assert sim_high > 0.25
        assert sim_low < 0.10

    def test_simhash_near_duplicate_detection(self):
        dedup = ChinaDeduplicationService()
        article_a = "阿里巴巴通义千问团队今天开源Qwen2.5-Coder代码模型，包含多种尺寸。"
        article_b = "阿里通义千问团队开源Qwen2.5-Coder代码模型，支持多种不同参数尺寸。"
        unrelated = "微软针对Windows内核远程代码执行高危漏洞发布带外补丁修复。"

        assert (
            dedup.is_near_duplicate(article_a, article_b, jaccard_threshold=0.30)
            is True
        )
        assert dedup.is_near_duplicate(article_a, unrelated) is False


class TestCisaEpssService:
    """Tests for CISA KEV and EPSS zero-cost enrichment."""

    @pytest.mark.asyncio
    async def test_cisa_kev_caching(self):
        svc = CisaEpssService()
        svc._kev_set = {"CVE-2024-3094", "CVE-2023-38606"}

        assert svc.is_known_exploited("CVE-2024-3094") is True
        assert svc.is_known_exploited("cve-2024-3094") is True  # case-insensitive
        assert svc.is_known_exploited("CVE-2099-0001") is False

    def test_nvd_url_generation(self):
        svc = CisaEpssService()
        url = svc.get_nvd_url("CVE-2026-12345")
        assert url == "https://nvd.nist.gov/vuln/detail/CVE-2026-12345"

    @pytest.mark.asyncio
    async def test_enrich_cve(self):
        svc = CisaEpssService()
        svc._kev_set = {"CVE-2024-3094"}

        with patch.object(svc, "get_epss_score", AsyncMock(return_value=(0.92, 0.99))):
            enrichment = await svc.enrich_cve("CVE-2024-3094")
            assert enrichment["cve"] == "CVE-2024-3094"
            assert enrichment["is_kev"] is True
            assert enrichment["epss"] == 0.92
            assert enrichment["threat_tier"] == "CRITICAL_EXPLOITED"
            assert "nvd.nist.gov" in enrichment["nvd_url"]


class TestModelScopeFetcher:
    """Tests for Alibaba ModelScope Hub OpenAPI fetcher."""

    def test_format_param_count(self):
        assert ModelScopeFetcher._format_param_count(16219988836) == "16.2B"
        assert ModelScopeFetcher._format_param_count(7000000000) == "7B"
        assert ModelScopeFetcher._format_param_count(500000) == "500K"
        assert ModelScopeFetcher._format_param_count(None) == "N/A"

    def test_parse_entry(self):
        source = Source(
            name="ModelScope Hub",
            category=Category.AI_TECH,
            type=SourceType.MODELSCOPE,
            url="https://modelscope.cn/openapi/v1/models",
        )
        fetcher = ModelScopeFetcher(source)

        raw = {
            "id": "Qwen/Qwen2.5-72B",
            "display_name": "Qwen2.5-72B",
            "description": "Alibaba high performance foundation model",
            "downloads": 150000,
            "likes": 2300,
            "license": "apache-2.0",
            "tasks": ["text-generation"],
            "params": 72000000000,
            "created_at": "2026-10-15T10:00:00Z",
        }

        entry = fetcher._parse_entry(raw)
        assert "[ModelScope]" in entry.title
        assert "Qwen2.5-72B" in entry.title
        assert "72B" in entry.title
        assert entry.metadata["region"] == "china"
        assert entry.metadata["parameters"] == "72B"
        assert entry.metadata["downloads"] == 150000


class TestHuggingFaceChinaFetcher:
    """Tests for Hugging Face Chinese Frontier Labs fetcher."""

    def test_parse_entry(self):
        source = Source(
            name="HF China Labs",
            category=Category.AI_MODELS,
            type=SourceType.HUGGINGFACE_CHINA,
            url="https://huggingface.co/api/models",
        )
        fetcher = HuggingFaceChinaFetcher(source)

        raw = {
            "id": "deepseek-ai/DeepSeek-V3",
            "likes": 5200,
            "downloads": 320000,
            "pipeline_tag": "text-generation",
            "tags": ["license:mit", "transformers", "moe"],
            "createdAt": "2026-10-10T12:00:00Z",
            "_tracked_author": "deepseek-ai",
        }

        entry = fetcher._parse_entry(raw)
        assert "[deepseek-ai]" in entry.title
        assert "deepseek-ai/DeepSeek-V3" in entry.title
        assert entry.metadata["region"] == "china"
        assert entry.metadata["author"] == "deepseek-ai"
        assert entry.metadata["license"] == "mit"
        assert entry.metadata["likes"] == 5200
