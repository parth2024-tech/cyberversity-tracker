"""
Language Identification and Script Detection Service.

Provides language identification, script recognition (Simplified vs Traditional Chinese),
and code-switching detection for native document processing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Distinctive Simplified Chinese markers
SIMPLIFIED_MARKERS: frozenset[str] = frozenset({
    "们", "这", "为", "国", "会", "发", "时", "经", "关", "样", "现", "进", "开",
    "长", "点", "电", "门", "车", "产", "动", "业", "义", "头", "说", "话", "问",
    "体", "两", "实", "写", "学", "让", "对", "东", "应", "总", "机", "见", "给",
    "认", "选", "调", "风", "飞", "钱", "马", "龙", "区", "华", "带", "组", "级",
    "设", "统", "单", "条", "农", "专", "联", "节", "市", "办", "导", "达", "运",
    "历", "变", "无", "从", "当", "数", "书", "并", "内", "过", "报", "网",
    "视", "处", "别", "类", "确", "计", "资", "规", "权", "观", "查", "题", "较",
    "证", "构", "强", "标", "际", "备", "队", "测", "评", "参", "训", "练",
})

# Distinctive Traditional Chinese markers
TRADITIONAL_MARKERS: frozenset[str] = frozenset({
    "們", "這", "為", "國", "會", "發", "時", "經", "關", "樣", "現", "進", "開",
    "長", "點", "電", "門", "車", "產", "動", "業", "義", "頭", "說", "話", "問",
    "體", "兩", "實", "寫", "學", "讓", "對", "東", "應", "總", "機", "見", "給",
    "認", "選", "調", "風", "飛", "錢", "馬", "龍", "區", "華", "帶", "組", "級",
    "設", "統", "單", "條", "農", "專", "聯", "節", "市", "辦", "導", "達", "運",
    "歷", "變", "無", "從", "當", "數", "書", "並", "內", "過", "報", "網",
    "視", "處", "別", "類", "確", "計", "資", "規", "權", "觀", "查", "題", "較",
    "證", "構", "強", "標", "際", "備", "隊", "測", "評", "參", "訓", "練",
})

# French stop words
FR_WORDS: frozenset[str] = frozenset({
    "le", "la", "les", "des", "est", "dans", "pour", "une", "sur", "avec", "sont", "un",
})

# German stop words
DE_WORDS: frozenset[str] = frozenset({
    "der", "die", "das", "und", "ist", "in", "von", "mit", "für", "auf", "nicht", "ein", "eine",
})

# Spanish stop words
ES_WORDS: frozenset[str] = frozenset({
    "el", "la", "los", "las", "en", "de", "y", "es", "por", "con", "para", "un", "una",
})


@dataclass(frozen=True)
class LanguageDetectionResult:
    """Structured result of language and script identification."""

    lang: str  # ISO-639-1 code: 'zh', 'en', 'ja', 'ko', 'ru', 'fr', 'de', 'es', etc.
    confidence: float  # 0.0 to 1.0
    script: str | None  # 'Hans', 'Hant', 'Latn', 'Cyrl', 'Jpan', 'Kore', 'Arab', etc.
    is_code_switched: bool  # True if text exhibits significant bilingual mixing
    cjk_ratio: float  # Proportion of characters in CJK ideograph ranges
    latin_ratio: float  # Proportion of characters in Latin ranges


class LanguageDetectionService:
    """Fast, deterministic language and script identifier for native intelligence ingestion."""

    def __init__(self) -> None:
        self._cjk_regex = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
        self._hiragana_katakana_regex = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
        self._hangul_regex = re.compile(r"[\uac00-\ud7af\u1100-\u11ff]")
        self._cyrillic_regex = re.compile(r"[\u0400-\u04ff]")
        self._arabic_regex = re.compile(r"[\u0600-\u06ff]")
        self._latin_regex = re.compile(r"[A-Za-z]")
        self._latin_words_regex = re.compile(r"\b[A-Za-z0-9_-]{2,}\b")

    def detect(self, text: str) -> LanguageDetectionResult:
        """Analyze text and determine primary language, script, confidence, and code-switching."""
        if not text or not text.strip():
            return LanguageDetectionResult(
                lang="und",
                confidence=0.0,
                script=None,
                is_code_switched=False,
                cjk_ratio=0.0,
                latin_ratio=0.0,
            )

        clean = text.strip()
        non_space_chars = [c for c in clean if not c.isspace()]
        total_chars = max(len(non_space_chars), 1)

        cjk_count = len(self._cjk_regex.findall(clean))
        latin_count = len(self._latin_regex.findall(clean))
        cjk_ratio = cjk_count / total_chars
        latin_ratio = latin_count / total_chars

        # 1. Japanese check (Hiragana or Katakana presence)
        if self._hiragana_katakana_regex.search(clean):
            confidence = min(0.95, 0.5 + (len(self._hiragana_katakana_regex.findall(clean)) / total_chars) * 2)
            return LanguageDetectionResult(
                lang="ja",
                confidence=round(confidence, 4),
                script="Jpan",
                is_code_switched=latin_ratio > 0.15,
                cjk_ratio=round(cjk_ratio, 4),
                latin_ratio=round(latin_ratio, 4),
            )

        # 2. Korean check (Hangul presence)
        if self._hangul_regex.search(clean):
            confidence = min(0.95, 0.5 + (len(self._hangul_regex.findall(clean)) / total_chars) * 2)
            return LanguageDetectionResult(
                lang="ko",
                confidence=round(confidence, 4),
                script="Kore",
                is_code_switched=latin_ratio > 0.15,
                cjk_ratio=round(cjk_ratio, 4),
                latin_ratio=round(latin_ratio, 4),
            )

        # 3. Chinese check (CJK ideographs dominate or present significantly)
        if cjk_count > 0:
            # If CJK chars make up >= 15% of non-whitespace chars, or >= 3 CJK chars when text is short
            if cjk_ratio >= 0.15 or (cjk_count >= 3 and len(clean) < 60):
                # Distinguish Hans vs Hant
                simplified_hits = sum(1 for char in clean if char in SIMPLIFIED_MARKERS)
                traditional_hits = sum(1 for char in clean if char in TRADITIONAL_MARKERS)

                if traditional_hits > simplified_hits:
                    script = "Hant"
                else:
                    script = "Hans"

                # Check for code-switching (e.g. Chinese text mentioning English model names/benchmarks)
                latin_words = self._latin_words_regex.findall(clean)
                is_code_switched = len(latin_words) >= 1 and latin_ratio > 0.08

                # Calculate confidence
                confidence = min(0.99, max(0.65, 0.5 + cjk_ratio * 0.5))

                return LanguageDetectionResult(
                    lang="zh",
                    confidence=round(confidence, 4),
                    script=script,
                    is_code_switched=is_code_switched,
                    cjk_ratio=round(cjk_ratio, 4),
                    latin_ratio=round(latin_ratio, 4),
                )

        # 4. Cyrillic check
        cyrillic_count = len(self._cyrillic_regex.findall(clean))
        if cyrillic_count > 0 and (cyrillic_count / total_chars) > 0.2:
            confidence = min(0.95, 0.5 + (cyrillic_count / total_chars) * 0.5)
            return LanguageDetectionResult(
                lang="ru",
                confidence=round(confidence, 4),
                script="Cyrl",
                is_code_switched=latin_ratio > 0.15,
                cjk_ratio=round(cjk_ratio, 4),
                latin_ratio=round(latin_ratio, 4),
            )

        # 5. Arabic check
        arabic_count = len(self._arabic_regex.findall(clean))
        if arabic_count > 0 and (arabic_count / total_chars) > 0.2:
            confidence = min(0.95, 0.5 + (arabic_count / total_chars) * 0.5)
            return LanguageDetectionResult(
                lang="ar",
                confidence=round(confidence, 4),
                script="Arab",
                is_code_switched=latin_ratio > 0.15,
                cjk_ratio=round(cjk_ratio, 4),
                latin_ratio=round(latin_ratio, 4),
            )

        # 6. Latin-based language identification
        words = set(re.findall(r"\b[a-z]{2,}\b", clean.lower()))
        script = "Latn"

        fr_hits = len(words.intersection(FR_WORDS))
        de_hits = len(words.intersection(DE_WORDS))
        es_hits = len(words.intersection(ES_WORDS))

        if fr_hits >= 2 and fr_hits > de_hits and fr_hits > es_hits:
            return LanguageDetectionResult(
                lang="fr",
                confidence=0.85,
                script=script,
                is_code_switched=False,
                cjk_ratio=0.0,
                latin_ratio=round(latin_ratio, 4),
            )

        if de_hits >= 2 and de_hits > fr_hits and de_hits > es_hits:
            return LanguageDetectionResult(
                lang="de",
                confidence=0.85,
                script=script,
                is_code_switched=False,
                cjk_ratio=0.0,
                latin_ratio=round(latin_ratio, 4),
            )

        if es_hits >= 2 and es_hits > fr_hits and es_hits > de_hits:
            return LanguageDetectionResult(
                lang="es",
                confidence=0.85,
                script=script,
                is_code_switched=False,
                cjk_ratio=0.0,
                latin_ratio=round(latin_ratio, 4),
            )

        # Default to English for Latin-dominant intelligence
        confidence = min(0.98, max(0.70, 0.5 + latin_ratio * 0.4))
        return LanguageDetectionResult(
            lang="en",
            confidence=round(confidence, 4),
            script=script,
            is_code_switched=False,
            cjk_ratio=round(cjk_ratio, 4),
            latin_ratio=round(latin_ratio, 4),
        )


language_detector = LanguageDetectionService()
