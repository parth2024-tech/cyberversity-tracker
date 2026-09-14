"""
Unit tests for TranslationService — language detection, caching, async wrappers.
All external HTTP calls (deep_translator, langdetect) are mocked out.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from ai_security_monitor.application.services.translation_service import (
    LANGUAGE_NAMES,
    TranslationService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(title: str = "Hello world", summary: str = "Some summary"):
    """Create a minimal mock domain entry."""
    entry = MagicMock()
    entry.title = title
    entry.summary = summary
    entry.metadata = {}
    return entry


# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_detects_japanese_hiragana(self):
        svc = TranslationService()
        assert svc.detect_language("こんにちは世界") == "ja"

    def test_detects_korean(self):
        svc = TranslationService()
        assert svc.detect_language("안녕하세요") == "ko"

    def test_detects_chinese_simplified(self):
        svc = TranslationService()
        assert svc.detect_language("人工智能正在改变世界") == "zh-cn"

    def test_detects_russian_cyrillic(self):
        svc = TranslationService()
        assert svc.detect_language("Привет мир") == "ru"

    def test_detects_arabic(self):
        svc = TranslationService()
        assert svc.detect_language("مرحبا بالعالم") == "ar"

    def test_empty_string_returns_english(self):
        svc = TranslationService()
        assert svc.detect_language("") == "en"

    def test_whitespace_only_returns_english(self):
        svc = TranslationService()
        assert svc.detect_language("   ") == "en"


# ---------------------------------------------------------------------------
# translate_text — cache & short-circuit
# ---------------------------------------------------------------------------


class TestTranslateText:
    def test_empty_text_returns_unchanged(self):
        svc = TranslationService()
        text, lang, is_trans = svc.translate_text("")
        assert text == ""
        assert is_trans is False

    def test_english_text_not_translated(self):
        svc = TranslationService()
        text, lang, is_trans = svc.translate_text("Breaking news from Silicon Valley")
        assert is_trans is False
        assert lang.startswith("en")

    def test_cache_hit_returned_without_re_translating(self):
        svc = TranslationService()
        cache_key = "en:こんにちは"
        svc._cache[cache_key] = ("Hello", "ja")

        text, lang, is_trans = svc.translate_text("こんにちは", target="en")
        assert text == "Hello"
        assert lang == "ja"
        assert is_trans is True

    def test_successful_translation_stored_in_cache(self):
        svc = TranslationService()
        with patch.object(
            svc, "_execute_translation", return_value="Artificial intelligence"
        ):
            text, lang, ok = svc.translate_text("人工智能", target="en")

        assert ok is True
        assert text == "Artificial intelligence"
        # Verify it's now cached
        assert "en:人工智能" in svc._cache

    def test_failed_translation_returns_original(self):
        svc = TranslationService()
        original = "Unbekannter Fehler"
        with (
            patch.object(svc, "detect_language", return_value="de"),
            patch.object(svc, "_execute_translation", return_value=None),
        ):
            text, lang, ok = svc.translate_text(original)

        assert text == original
        assert ok is False


# ---------------------------------------------------------------------------
# Cache size eviction
# ---------------------------------------------------------------------------


class TestCacheEviction:
    def test_cache_drops_oldest_entries_at_max_size(self):
        svc = TranslationService(max_cache_size=10)
        # Pre-fill cache to max
        for i in range(10):
            svc._cache[f"key_{i}"] = (f"val_{i}", "de")

        # Adding one more should trigger 20% eviction (2 keys removed)
        svc._set_cache("key_new", "val_new", "fr")
        assert len(svc._cache) < 11


# ---------------------------------------------------------------------------
# translate_entry
# ---------------------------------------------------------------------------


class TestTranslateEntry:
    def test_english_entry_not_translated(self):
        svc = TranslationService()
        entry = _make_entry(
            "Breakthrough in LLM reasoning", "OpenAI releases o3 model."
        )
        # Explicitly patch detect_language so the test is not dependent on
        # external langdetect library behaviour with short text snippets.
        with patch.object(svc, "detect_language", return_value="en"):
            result = svc.translate_entry(entry)
        assert result is False
        assert not entry.metadata.get("is_translated")

    def test_foreign_entry_is_translated_in_place(self):
        svc = TranslationService()
        entry = _make_entry("人工智能突破", "大型语言模型推理能力提升")
        with patch.object(svc, "_execute_translation", return_value="AI Breakthrough"):
            result = svc.translate_entry(entry)

        assert result is True
        assert entry.metadata.get("is_translated") is True
        assert "original_title" in entry.metadata

    def test_original_title_preserved(self):
        svc = TranslationService()
        original_title = "Прорыв в области ИИ"
        entry = _make_entry(original_title, "Новая языковая модель")
        with patch.object(svc, "_execute_translation", return_value="AI Breakthrough"):
            svc.translate_entry(entry)

        assert entry.metadata["original_title"] == original_title


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------


class TestAsyncWrappers:
    @pytest.mark.asyncio
    async def test_translate_text_async_returns_same_as_sync(self):
        svc = TranslationService()
        text = "Hello from async world"
        sync_result = svc.translate_text(text)
        async_result = await svc.translate_text_async(text)
        assert sync_result == async_result

    @pytest.mark.asyncio
    async def test_translate_entry_async_returns_bool(self):
        svc = TranslationService()
        entry = _make_entry("OpenAI GPT-5 announced", "New frontier model released.")
        result = await svc.translate_entry_async(entry)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# LANGUAGE_NAMES mapping
# ---------------------------------------------------------------------------


class TestLanguageNames:
    def test_known_languages_have_flags(self):
        for code in ("zh", "ru", "ja", "ko", "de", "fr", "ar"):
            assert code in LANGUAGE_NAMES
            name, flag = LANGUAGE_NAMES[code]
            assert name
            assert flag

    def test_english_present(self):
        name, flag = LANGUAGE_NAMES["en"]
        assert name == "English"
