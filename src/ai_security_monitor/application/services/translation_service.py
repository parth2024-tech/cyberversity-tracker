"""
Autonomous Intelligence Translation Service.

Automatically detects foreign language feeds (Chinese, Russian, Japanese,
German, French, Korean, Spanish, etc.) and translates intelligence titles,
advisories, and abstracts into English with multi-engine fallback and LRU caching.
"""

from __future__ import annotations

import asyncio
import html
import re
import urllib.parse
from datetime import UTC, datetime

import structlog

from ai_security_monitor.application.services.china_token_shield import (
    ChinaTokenShield,
    token_shield,
)
from ai_security_monitor.config.settings import settings

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

GLOSSARY_FALLBACK_TERMS: list[tuple[str, str]] = [
    ("大语言模型", "Foundation Large Language Model"),
    ("大模型", "Large Language Model"),
    ("基座模型", "Foundation Model"),
    ("思维链", "Chain-of-Thought (CoT)"),
    ("测试时计算扩展", "Test-Time Compute Scaling"),
    ("强化学习对齐", "RL / RLHF Alignment"),
    ("开源权重", "Open-Weights Release"),
    ("端侧模型", "On-Device SLM"),
    ("算力集群", "Compute Cluster"),
    ("显存占用", "VRAM Footprint"),
    ("显存", "VRAM"),
    ("推理框架", "Inference Runtime"),
    ("推理加速", "Inference Acceleration"),
    ("推理引擎", "Inference Engine"),
    ("智能体", "Autonomous Agent"),
    ("知识库", "RAG Knowledge Base"),
    ("检索增强", "Retrieval-Augmented Generation (RAG)"),
    ("多模态", "Multimodal"),
    ("视觉大模型", "Vision-Language Foundation Model"),
    ("语音大模型", "Voice Foundation Model"),
    ("语音合成", "Speech Synthesis / TTS"),
    ("微调", "Fine-Tuning"),
    ("量化", "Quantization"),
    ("深度求索", "DeepSeek"),
    ("通义千问", "Alibaba Qwen"),
    ("上海人工智能实验室", "Shanghai AI Lab"),
    ("智谱", "Zhipu AI"),
    ("月之暗面", "Moonshot AI"),
    ("评测基准", "Evaluation Benchmark"),
    ("零日漏洞", "Zero-Day Vulnerability"),
    ("利用代码", "Exploit PoC"),
    ("权限提升", "Privilege Escalation"),
    ("威胁情报", "Threat Intelligence"),
    ("安全公告", "Security Advisory"),
    ("逆向工程", "Reverse Engineering"),
]


class TranslationService:
    """Zero-cost autonomous neural translation engine with multi-provider fallbacks."""

    def __init__(
        self,
        max_cache_size: int = 2000,
        token_shield_instance: ChinaTokenShield | None = None,
    ):
        self._cache: dict[
            str, tuple[str, str]
        ] = {}  # text -> (translated, detected_lang)
        self._max_cache_size = max_cache_size
        self._token_shield = token_shield_instance or token_shield

    def has_foreign_text(self, text: str | None) -> bool:
        """Check if text contains foreign non-English characters or non-Latin scripts."""
        if not text or not text.strip():
            return False
        # Non-Latin scripts (Chinese, Japanese, Korean, Cyrillic, Arabic, Hebrew, Thai, etc.)
        if re.search(
            r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff\u0600-\u06ff\u0590-\u05ff\u0e00-\u0e7f]",
            text,
        ):
            return True
        # Check Latin text with accented characters against detect_language
        if re.search(r"[áéíóúüñäößàèìòùâêîôûç]", text, re.I):
            lang = self.detect_language(text)
            return lang != "en" and not lang.startswith("en")
        return False

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

        # Common English vocabulary & tech jargon heuristics
        common_en = {
            "the",
            "of",
            "and",
            "in",
            "to",
            "for",
            "with",
            "is",
            "on",
            "at",
            "from",
            "by",
            "as",
            "this",
            "that",
            "an",
            "be",
            "are",
            "ai",
            "model",
            "models",
            "learning",
            "system",
            "server",
            "release",
            "data",
            "code",
            "paper",
            "using",
            "new",
            "vram",
            "ram",
            "gpu",
            "llm",
            "meets",
            "goes",
            "show",
            "hn",
            "agent",
            "open",
            "weights",
            "source",
            "inference",
            "training",
            "benchmarks",
            "reasoning",
        }
        words = set(re.findall(r"\b[a-zA-Z]{2,}\b", clean.lower()))
        has_accented = bool(re.search(r"[áéíóúüñäößàèìòùâêîôûç]", clean, re.I))

        if words & common_en:
            if not has_accented or len(words & common_en) >= 2:
                return "en"

        # Pure ASCII text without non-Latin scripts or foreign accents is English in tech feeds
        if all(ord(c) < 128 for c in clean):
            words_list = clean.split()
            if len(clean) < 60 or len(words_list) <= 7 or not has_accented:
                return "en"

        # Check with langdetect for European / Latin script languages
        try:
            from langdetect import DetectorFactory, detect_langs

            DetectorFactory.seed = 0
            clean_detect = re.sub(
                r"https?://\S+|CVE-\d+-\d+|\b\d+\b", "", clean
            ).strip()
            if len(clean_detect) >= 30:
                langs = detect_langs(clean_detect)
                if langs:
                    top = langs[0]
                    if top.lang == "en":
                        return "en"
                    # If pure ASCII without accented letters, avoid false positives from short fragments
                    if all(ord(c) < 128 for c in clean) and top.lang in (
                        "de",
                        "nl",
                        "ca",
                        "af",
                        "so",
                        "da",
                        "no",
                        "sv",
                    ):
                        return "en"
                    threshold = getattr(
                        settings.fetch, "langdetect_confidence_threshold", 0.7
                    )
                    if top.prob < threshold:
                        return "uncertain"
                    return top.lang
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

        # If uncertain, skip translation to prevent corrupting text
        if detected_lang == "uncertain":
            return clean_text, "uncertain", False

        # If already English or target language, return as-is
        if detected_lang == target or detected_lang.startswith("en"):
            self._set_cache(cache_key, clean_text, "en")
            return clean_text, "en", False

        # Protect technical tokens (model identifiers, param counts, CVEs, repo paths)
        shielded_text, mapping = self._token_shield.shield(clean_text)

        # Attempt translation with multi-provider fallback
        translated = self._execute_translation(shielded_text, detected_lang, target)

        if translated and translated.strip() and translated.strip() != shielded_text:
            if mapping:
                translated = self._token_shield.unshield(translated, mapping)
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
        summary_lang = (
            self.detect_language(entry.summary or "") if entry.summary else "en"
        )

        # If confidence was below threshold, flag as uncertain and preserve original text
        if title_lang == "uncertain" or summary_lang == "uncertain":
            from ai_security_monitor.core.diagnostics import diagnostics

            diagnostics.record_language_uncertain(entry.title or "")
            entry.metadata = entry.metadata or {}
            entry.metadata["language_uncertain"] = True
            if "original_title" not in entry.metadata:
                entry.metadata["original_title"] = entry.title
            if "original_summary" not in entry.metadata:
                entry.metadata["original_summary"] = entry.summary
            logger.info(
                f"Preserving original text due to uncertain language confidence: {entry.title[:50]}..."
            )
            return False

        # Check if either field is non-English
        is_foreign = (title_lang != "en" and not title_lang.startswith("en")) or (
            summary_lang != "en" and not summary_lang.startswith("en")
        )

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
        entry.metadata["translated_at"] = datetime.now(UTC).isoformat()

        logger.info(
            f"Automatically translated entry from {flag} {friendly_name} ({detected_code}): {entry.title[:60]}..."
        )
        return True

    def _translate_via_slm(
        self, text: str, source_lang: str, target: str
    ) -> str | None:
        """Route translation to Tier 1 Local SLM (e.g. Qwen2.5) if circuit breaker allows."""
        from ai_security_monitor.infrastructure.analyzers.slm_circuit_breaker import (
            slm_circuit_breaker,
        )

        if slm_circuit_breaker.is_tripped or not getattr(
            settings.analyzer, "slm_enabled", True
        ):
            return None

        import httpx

        endpoint = getattr(
            settings.analyzer, "slm_endpoint", "http://localhost:11434"
        ).rstrip("/")
        model = getattr(settings.analyzer, "slm_model", "qwen2.5:7b")

        timeout = httpx.Timeout(
            connect=settings.analyzer.slm_timeout_seconds,
            read=8.0,
            write=5.0,
            pool=3.0,
        )

        payload = {
            "model": model,
            "system": "You are a professional technical translator. Translate the text into fluent English. Output ONLY the translated text without commentary or quotation marks.",
            "prompt": f"Translate this from {source_lang} to {target}:\n\n{text}",
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 300},
        }

        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{endpoint}/api/generate", json=payload)
                if resp.status_code == 200:
                    raw = resp.json().get("response", "").strip()
                    if raw and raw != text:
                        slm_circuit_breaker.record_success()
                        unescaped = html.unescape(raw)
                        return self._refine_ai_translation(unescaped, source_lang)
        except (httpx.ConnectError, httpx.ConnectTimeout) as net_err:
            slm_circuit_breaker.record_failure(net_err)
        except Exception as err:
            logger.debug(f"Local SLM translation error: {err}")

        return None

    def _translate_via_gtx(
        self, text: str, source_lang: str, target: str
    ) -> str | None:
        """Translate via Google Translate GTX RPC — fast, free, and robust against web scraping limits."""
        import httpx

        src = "auto" if source_lang in ("en", "auto") else source_lang
        if src in ("zh-cn", "zh_cn"):
            src = "zh-CN"
        elif src in ("zh-tw", "zh_tw"):
            src = "zh-TW"

        # Chunk if text exceeds 1200 characters to stay within safe query bounds
        if len(text) > 1200:
            chunks = [text[i : i + 1000] for i in range(0, len(text), 1000)]
            translated_chunks = []
            for chunk in chunks:
                part = self._translate_via_gtx(chunk, source_lang, target)
                if part:
                    translated_chunks.append(part)
                else:
                    return None
            return " ".join(translated_chunks)

        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={src}&tl={target}&dt=t&q={urllib.parse.quote(text)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }

        try:
            with httpx.Client(timeout=6.0, headers=headers) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if (
                        data
                        and isinstance(data, list)
                        and len(data) > 0
                        and isinstance(data[0], list)
                    ):
                        pieces = [p[0] for p in data[0] if p and p[0]]
                        combined = "".join(pieces)
                        if (
                            combined
                            and combined.strip()
                            and combined.strip() != text.strip()
                        ):
                            unescaped = html.unescape(combined)
                            return self._refine_ai_translation(unescaped, source_lang)
        except Exception as e:
            logger.debug(f"GTX translation notice: {e}")

        return None

    def _translate_via_groq(
        self, text: str, source_lang: str, target: str
    ) -> str | None:
        """Route translation to Groq cloud API if key is present."""
        groq_key = getattr(settings.analyzer, "groq_api_key", None)
        if not groq_key:
            return None
        import httpx

        headers = {
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a professional technical translator. Translate the text into fluent English. Preserve all placeholders like ⟦T_01⟧ and model names exactly as given. Output ONLY the English translation without preamble or quotes.",
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
            "temperature": 0.1,
            "max_tokens": 500,
        }
        try:
            with httpx.Client(timeout=7.0) as client:
                resp = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        raw = choices[0].get("message", {}).get("content", "").strip()
                        if raw and raw != text:
                            unescaped = html.unescape(raw)
                            return self._refine_ai_translation(unescaped, source_lang)
        except Exception as e:
            logger.debug(f"Groq translation notice: {e}")
        return None

    def _translate_via_glossary_fallback(
        self, text: str, source_lang: str
    ) -> str | None:
        """Deterministic offline glossary substitution when all network translation channels fail."""
        if not text:
            return None
        res = text
        for zh_term, en_term in GLOSSARY_FALLBACK_TERMS:
            res = res.replace(zh_term, en_term)
        if res != text:
            return self._refine_ai_translation(res, source_lang)
        return None

    def _execute_translation(
        self, text: str, source_lang: str, target: str
    ) -> str | None:
        """Execute translation via Multi-Tier resilient cascade with fail-safe fallbacks."""
        # Tier 1: Local SLM (Ollama / Qwen2.5) if circuit breaker permits
        try:
            slm_result = self._translate_via_slm(text, source_lang, target)
            if slm_result:
                return slm_result
        except Exception as e:
            logger.debug(f"Tier 1 SLM translation notice: {e}")

        # Tier 2: Free Cloud LLM (Groq) if configured
        try:
            groq_result = self._translate_via_groq(text, source_lang, target)
            if groq_result:
                return groq_result
        except Exception as e:
            logger.debug(f"Tier 2 Groq translation notice: {e}")

        # Tier 3: Direct Google GTX RPC (Fast, robust, zero-cost, no scraper rate limits)
        try:
            gtx_result = self._translate_via_gtx(text, source_lang, target)
            if gtx_result:
                return gtx_result
        except Exception as e:
            logger.debug(f"Tier 3 GTX translation notice: {e}")

        # Tier 4: deep_translator GoogleTranslator
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
                unescaped = html.unescape(result)
                return self._refine_ai_translation(unescaped, source_lang)
        except Exception as e:
            logger.debug(f"GoogleTranslator error for '{text[:30]}...': {e}")

        # Tier 5: deep_translator MyMemoryTranslator (chunked)
        try:
            from deep_translator import MyMemoryTranslator

            mymemory_map = {
                "zh": "zh-CN",
                "zh-cn": "zh-CN",
                "zh-tw": "zh-TW",
                "de": "de-DE",
                "fr": "fr-FR",
                "es": "es-ES",
                "it": "it-IT",
                "ja": "ja-JP",
                "ko": "ko-KR",
                "ru": "ru-RU",
                "ar": "ar-SA",
                "pt": "pt-PT",
                "nl": "nl-NL",
                "pl": "pl-PL",
                "tr": "tr-TR",
            }
            src_locale = mymemory_map.get(source_lang.lower(), source_lang)
            target_locale = "en-US" if target == "en" else target
            mm = MyMemoryTranslator(source=src_locale, target=target_locale)

            if len(text) > 480:
                chunks = [
                    text[i : i + 450] for i in range(0, min(len(text), 1500), 450)
                ]
                translated_parts = []
                for c in chunks:
                    res = mm.translate(c)
                    if res and not res.startswith("MYMEMORY WARNING"):
                        translated_parts.append(res)
                if translated_parts:
                    unescaped = html.unescape(" ".join(translated_parts))
                    return self._refine_ai_translation(unescaped, source_lang)
            else:
                result = mm.translate(text)
                if result and not result.startswith("MYMEMORY WARNING"):
                    unescaped = html.unescape(result)
                    return self._refine_ai_translation(unescaped, source_lang)
        except Exception as e:
            logger.debug(f"MyMemoryTranslator fallback error: {e}")

        # Tier 6: deep_translator LingueeTranslator
        try:
            from deep_translator import LingueeTranslator

            lt = LingueeTranslator(source=source_lang, target=target)
            result = lt.translate(text)
            if result:
                unescaped = html.unescape(result)
                return self._refine_ai_translation(unescaped, source_lang)
        except Exception:
            pass

        # Tier 7: Deterministic Glossary Fallback (Offline emergency fail-safe)
        try:
            glossary_res = self._translate_via_glossary_fallback(text, source_lang)
            if glossary_res:
                return glossary_res
        except Exception:
            pass

        return None

    def _refine_ai_translation(self, text: str, source_lang: str) -> str:
        """Post-process translated text with researcher-grade AI and cybersecurity terminology."""
        if not text:
            return text
        t = text
        replacements = [
            (r"\bbig model(s)?\b", r"Foundation LLM\1"),
            (r"\blarge model(s)?\b", r"Large Language Model\1"),
            (r"\bthought chain(s)?\b", r"Chain-of-Thought (CoT)"),
            (r"\bvideo memory\b", "VRAM"),
            (r"\bcompute power\b", "compute budget"),
            (r"\bend-side model(s)?\b", r"on-device SLM\1"),
            (r"\bopen source weight(s)?\b", r"open-weights release\1"),
            (r"\bquantification\b", "quantization"),
            (r"\bstrengthen tuning\b", "RL / RLHF alignment"),
            (r"\bmicro-tuning\b", "fine-tuning"),
            (r"\bprompt words\b", "prompts"),
            (r"\b0day\b", "Zero-Day"),
            (r"\butilization code\b", "exploit PoC"),
            (r"\bright escalation\b", "privilege escalation"),
            (r"\bsecurity announcement(s)?\b", r"security advisory\1"),
            (r"\bknowledge distilling\b", "knowledge distillation"),
            (r"\bretrieval enhancement\b", "Retrieval-Augmented Generation (RAG)"),
            (r"\bknowledge base\b", "RAG knowledge base"),
            (r"\bsmart body\b|\bintelligent body\b", "AI Agent"),
            (r"\breasoning frame\b", "inference runtime"),
            (r"\bmulti-modal\b", "multimodal"),
        ]
        for pat, rep in replacements:
            t = re.sub(pat, rep, t, flags=re.I)
        return t

    def _set_cache(self, key: str, value: str, lang: str) -> None:
        """Store translation in memory cache with size bound."""
        if len(self._cache) >= self._max_cache_size:
            # Drop oldest 20%
            keys = list(self._cache.keys())[: int(self._max_cache_size * 0.2)]
            for k in keys:
                self._cache.pop(k, None)
        self._cache[key] = (value, lang)

    # ------------------------------------------------------------------
    # Async-safe wrappers — use these from async contexts (FastAPI routes,
    # monitor sweeps, newspaper generation) to avoid blocking the event loop.
    # ------------------------------------------------------------------

    async def translate_text_async(
        self, text: str, target: str = "en"
    ) -> tuple[str, str, bool]:
        """Non-blocking version of translate_text() — runs sync providers in a thread."""
        return await asyncio.to_thread(self.translate_text, text, target)

    async def translate_entry_async(self, entry) -> bool:
        """Non-blocking version of translate_entry() — runs sync providers in a thread."""
        return await asyncio.to_thread(self.translate_entry, entry)


# Global singleton translation service instance
translation_service = TranslationService()
