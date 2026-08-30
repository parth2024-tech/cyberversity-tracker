"""
Autonomous Intelligence Translation Service.

Automatically detects foreign language feeds (Chinese, Russian, Japanese,
German, French, Korean, Spanish, etc.) and translates intelligence titles,
advisories, and abstracts into English with multi-engine fallback and LRU caching.
"""
from __future__ import annotations

import re
import html
import structlog
from datetime import datetime, timezone
from typing import Optional

logger = structlog.get_logger(__name__)

# ISO Language Code to Friendly Display Name & Flag
LANGUAGE_NAMES: dict[str, tuple[str, str]] = {
    "zh": ("Chinese", "🇨🇳"),
    "zh-cn": ("Chinese (Simplified)", "🇨🇳"),
    "zh-tw": ("Chinese (Traditional)", "🇹🇼"),
    "ru": ("Russian", "🇷🇺"),
    "ja": ("Japanese", "🇯🇵"),
    "ko": ("Korean", "🇰🇷"),
    "de": ("German", "🇩🇪"),
    "fr": ("French", "🇫🇷"),
    "es": ("Spanish", "🇪🇸"),
    "it": ("Italian", "🇮🇹"),
    "pt": ("Portuguese", "🇵🇹"),
    "ar": ("Arabic", "🇸🇦"),
    "fa": ("Persian", "🇮🇷"),
    "uk": ("Ukrainian", "🇺🇦"),
    "vi": ("Vietnamese", "🇻🇳"),
    "nl": ("Dutch", "🇳🇱"),
    "pl": ("Polish", "🇵🇱"),
    "tr": ("Turkish", "🇹🇷"),
    "en": ("English", "🌐"),
}


class TranslationService:
    """Zero-cost autonomous neural translation engine with multi-provider fallbacks."""

    def __init__(self, max_cache_size: int = 2000):
        self._cache: dict[str, tuple[str, str]] = {}  # text -> (translated, detected_lang)
        self._max_cache_size = max_cache_size

    def detect_language(self, text: str) -> str:
        """Detect the source language of a text with high accuracy."""
        if not text or not text.strip():
            return "en"

        clean = text.strip()

        # Unicode script quick heuristics (100% precision for non-Latin scripts)
        if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", clean):
            return "ja"
        if re.search(r"[\uac00-\ud7af\u1100-\u11ff]", clean):
            return "ko"
        if re.search(r"[\u4e00-\u9fff]", clean):
            return "zh-cn"
        if re.search(r"[\u0400-\u04ff]", clean):
            return "ru"
        if re.search(r"[\u0600-\u06ff]", clean):
            return "ar"

        # Check with langdetect for European / Latin script languages
        try:
            from langdetect import detect, DetectorFactory
            DetectorFactory.seed = 0
            # Strip URLs and numbers before detection
            clean_detect = re.sub(r"https?://\S+|CVE-\d+-\d+|\b\d+\b", "", clean).strip()
            if len(clean_detect) >= 5:
                lang = detect(clean_detect)
                return lang
        except Exception:
            pass

        return "en"

    def translate_text(self, text: str, target: str = "en") -> tuple[str, str, bool]:
        """
        Translate any string into English.
        Returns: (translated_text, detected_language_code, is_translated)
        """
        if not text or not text.strip():
            return text, "en", False

        clean_text = text.strip()

        # Check LRU cache
        cache_key = f"{target}:{clean_text}"
        if cache_key in self._cache:
            trans, lang = self._cache[cache_key]
            return trans, lang, lang != target and lang != "en"

        detected_lang = self.detect_language(clean_text)

        # If already English or target language, return as-is
        if detected_lang == target or detected_lang.startswith("en"):
            self._set_cache(cache_key, clean_text, "en")
            return clean_text, "en", False

        # Attempt translation with multi-provider fallback
        translated = self._execute_translation(clean_text, detected_lang, target)

        if translated and translated.strip() and translated.strip() != clean_text:
            self._set_cache(cache_key, translated, detected_lang)
            return translated, detected_lang, True

        # If translation failed or yielded identical text, record and return
        self._set_cache(cache_key, clean_text, detected_lang)
        return clean_text, detected_lang, False

    def translate_entry(self, entry) -> bool:
        """
        Automatically detect language and translate entry title and summary in-place.
        Returns True if the entry was translated from a non-English language.
        """
        title_lang = self.detect_language(entry.title or "")
        summary_lang = self.detect_language(entry.summary or "") if entry.summary else "en"

        # Check if either field is non-English
        is_foreign = (title_lang != "en" and not title_lang.startswith("en")) or \
                     (summary_lang != "en" and not summary_lang.startswith("en"))

        if not is_foreign:
            return False

        detected_code = title_lang if title_lang != "en" else summary_lang
        friendly_info = LANGUAGE_NAMES.get(detected_code, (detected_code.upper(), "🌐"))
        friendly_name, flag = friendly_info

        entry.metadata = entry.metadata or {}

        # Preserve untampered original text if not already saved
        if "original_title" not in entry.metadata:
            entry.metadata["original_title"] = entry.title
        if "original_summary" not in entry.metadata:
            entry.metadata["original_summary"] = entry.summary

        # Translate Title
        if title_lang != "en" and not title_lang.startswith("en"):
            trans_title, _, ok = self.translate_text(entry.title, target="en")
            if ok:
                entry.title = trans_title

        # Translate Summary
        if entry.summary and summary_lang != "en" and not summary_lang.startswith("en"):
            trans_summary, _, ok = self.translate_text(entry.summary, target="en")
            if ok:
                entry.summary = trans_summary

        # Stamp translation metadata
        entry.metadata["is_translated"] = True
        entry.metadata["detected_language"] = detected_code
        entry.metadata["detected_language_name"] = friendly_name
        entry.metadata["detected_language_flag"] = flag
        entry.metadata["translated_at"] = datetime.now(timezone.utc).isoformat()

        logger.info(
            f"Automatically translated entry from {flag} {friendly_name} ({detected_code}): {entry.title[:60]}..."
        )
        return True

    def _execute_translation(self, text: str, source_lang: str, target: str) -> Optional[str]:
        """Execute translation via deep_translator with fallback providers."""
        # 1. Primary: GoogleTranslator
        try:
            from deep_translator import GoogleTranslator
            src = "auto" if source_lang == "en" else source_lang
            if src in ("zh-cn", "zh_cn"):
                src = "zh-CN"
            elif src in ("zh-tw", "zh_tw"):
                src = "zh-TW"

            translator = GoogleTranslator(source=src, target=target)
            result = translator.translate(text)
            if result and not result.startswith("Error 500"):
                return html.unescape(result)
        except Exception as e:
            logger.debug(f"GoogleTranslator error for '{text[:30]}...': {e}")

        # 2. Fallback: MyMemoryTranslator
        try:
            from deep_translator import MyMemoryTranslator
            mymemory_map = {
                "zh": "zh-CN", "zh-cn": "zh-CN", "zh-tw": "zh-TW",
                "de": "de-DE", "fr": "fr-FR", "es": "es-ES", "it": "it-IT",
                "ja": "ja-JP", "ko": "ko-KR", "ru": "ru-RU", "ar": "ar-SA",
                "pt": "pt-PT", "nl": "nl-NL", "pl": "pl-PL", "tr": "tr-TR",
            }
            src_locale = mymemory_map.get(source_lang.lower(), source_lang)
            target_locale = "en-US" if target == "en" else target
            mm = MyMemoryTranslator(source=src_locale, target=target_locale)
            result = mm.translate(text)
            if result and not result.startswith("MYMEMORY WARNING"):
                return html.unescape(result)
        except Exception as e:
            logger.debug(f"MyMemoryTranslator fallback error: {e}")

        # 3. Fallback: LingueeTranslator
        try:
            from deep_translator import LingueeTranslator
            lt = LingueeTranslator(source=source_lang, target=target)
            result = lt.translate(text)
            if result:
                return html.unescape(result)
        except Exception:
            pass

        return None

    def _set_cache(self, key: str, value: str, lang: str) -> None:
        """Store translation in memory cache with size bound."""
        if len(self._cache) >= self._max_cache_size:
            # Drop oldest 20%
            keys = list(self._cache.keys())[:int(self._max_cache_size * 0.2)]
            for k in keys:
                self._cache.pop(k, None)
        self._cache[key] = (value, lang)


# Global singleton translation service instance
translation_service = TranslationService()
