"""
Unit and Integration Tests for Autonomous Intelligence Translation Service.
"""
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from ai_security_monitor.application.services.translation_service import (
    TranslationService,
    LANGUAGE_NAMES,
)
from ai_security_monitor.domain.entities import Entry, Category


def test_language_detection_heuristics():
    """Verify high-precision language detection across Asian and European scripts."""
    service = TranslationService()

    # Chinese
    assert service.detect_language("DeepSeek-R1 曝出严重零日漏洞") in ("zh-cn", "zh")
    # Russian
    assert service.detect_language("Атака нулевого дня на критическую инфраструктуру") == "ru"
    # Japanese
    assert service.detect_language("ゼロデイ脆弱性が発見されました。") == "ja"
    # Korean
    assert service.detect_language("새로운 제로데이 취약점이 발견되었습니다.") == "ko"
    # Arabic
    assert service.detect_language("تم اكتشاف ثغرة أمنية جديدة في الخادم") == "ar"
    # English
    assert service.detect_language("Critical remote code execution vulnerability in Apache HTTP") == "en"
    # Empty / whitespace
    assert service.detect_language("") == "en"
    assert service.detect_language("   ") == "en"


def test_translate_text_caching():
    """Verify translated strings are cached for zero-latency repeats."""
    service = TranslationService()

    sample_zh = "DeepSeek-V3 模型的提示注入风险分析"
    
    with patch.object(service, "_execute_translation", return_value="Prompt injection risk analysis of DeepSeek-V3 model") as mock_exec:
        trans1, lang1, ok1 = service.translate_text(sample_zh)
        assert ok1 is True
        assert "DeepSeek" in trans1
        assert lang1 in ("zh-cn", "zh")
        assert mock_exec.call_count == 1

        # Second call should hit LRU cache without executing translation again
        trans2, lang2, ok2 = service.translate_text(sample_zh)
        assert trans2 == trans1
        assert ok2 is True
        assert mock_exec.call_count == 1


def test_translate_entry_in_place():
    """Verify translation of an Entry object preserves originals in metadata."""
    service = TranslationService()

    entry = Entry(
        id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        title="CNNVD 关于开源大模型安全漏洞的预警通报",
        url="https://cnnvd.org.cn/alert/123",
        content_hash="hash-zh-12345",
        summary="国家信息安全漏洞库监测到针对开源框架的远程攻击风险。",
        published_at=datetime.now(timezone.utc),
        category=Category.CYBERSECURITY,
        metadata={"region": "china", "country": "CN"}
    )

    with patch.object(
        service,
        "_execute_translation",
        side_effect=lambda text, src, tgt: f"[EN] {text}"
    ):
        was_trans = service.translate_entry(entry)
        assert was_trans is True
        assert entry.title.startswith("[EN]")
        assert entry.summary.startswith("[EN]")
        assert entry.metadata["is_translated"] is True
        assert entry.metadata["original_title"] == "CNNVD 关于开源大模型安全漏洞的预警通报"
        assert entry.metadata["original_summary"] == "国家信息安全漏洞库监测到针对开源框架的远程攻击风险。"
        assert entry.metadata["detected_language"] in ("zh-cn", "zh")
        assert entry.metadata["detected_language_flag"] in ("🇨🇳", "🌐")


@pytest.mark.asyncio
async def test_translation_api_endpoints():
    """Verify /api/translate text and backfill endpoints."""
    from httpx import ASGITransport, AsyncClient
    from ai_security_monitor.presentation.api.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Translate Arbitrary Text
        res = await client.post(
            "/api/translate",
            json={"text": "DeepSeek-R1 安全通报", "target": "en"}
        )
        assert res.status_code == 200
        data = res.json()
        assert "translated" in data
        assert data["detected_language"] in ("zh-cn", "zh")

        # 2. Backfill Endpoint
        res_backfill = await client.post(
            "/api/translate/backfill",
            json={"limit": 5}
        )
        assert res_backfill.status_code == 200
        assert "status" in res_backfill.json()
        assert res_backfill.json()["status"] == "success"
