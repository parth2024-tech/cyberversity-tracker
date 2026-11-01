"""
Unit tests for Language Identification and Script Detection Service.
"""

from ai_security_monitor.application.services.language_detection_service import (
    LanguageDetectionService,
    language_detector,
)


def test_empty_and_whitespace():
    detector = LanguageDetectionService()
    res1 = detector.detect("")
    assert res1.lang == "und"
    assert res1.confidence == 0.0
    assert res1.script is None
    assert not res1.is_code_switched

    res2 = detector.detect("   \n\t  ")
    assert res2.lang == "und"


def test_simplified_chinese_detection():
    detector = LanguageDetectionService()
    text = "深度求索发布全新开源大语言模型，采用自适应路由架构与多头潜在注意力机制。"
    res = detector.detect(text)
    assert res.lang == "zh"
    assert res.script == "Hans"
    assert res.cjk_ratio > 0.7
    assert res.confidence > 0.8


def test_traditional_chinese_detection():
    detector = LanguageDetectionService()
    text = "這是一個關於人工智慧模型測試的範例，評測結果顯示性能顯著提升。"
    res = detector.detect(text)
    assert res.lang == "zh"
    assert res.script == "Hant"
    assert res.cjk_ratio > 0.7


def test_chinese_code_switching():
    detector = LanguageDetectionService()
    text = "阿里通义团队开源 Qwen2.5-Coder-32B 模型，在 EvalPlus 和 GSM8K 评测基准上达到 SOTA 水平。"
    res = detector.detect(text)
    assert res.lang == "zh"
    assert res.script == "Hans"
    assert res.is_code_switched is True
    assert res.latin_ratio > 0.1


def test_english_detection():
    detector = LanguageDetectionService()
    text = "vLLM introduces a high-throughput and memory-efficient inference engine for LLMs using PagedAttention."
    res = detector.detect(text)
    assert res.lang == "en"
    assert res.script == "Latn"
    assert res.confidence >= 0.7
    assert not res.is_code_switched


def test_japanese_detection():
    detector = LanguageDetectionService()
    text = "最新の人工知能モデルに関する研究論文が発表されました。"
    res = detector.detect(text)
    assert res.lang == "ja"
    assert res.script == "Jpan"


def test_korean_detection():
    detector = LanguageDetectionService()
    text = "새로운 인공지능 파운데이션 모델이 공개되었습니다."
    res = detector.detect(text)
    assert res.lang == "ko"
    assert res.script == "Kore"


def test_russian_detection():
    detector = LanguageDetectionService()
    text = "Новая архитектура трансформеров для обработки естественного языка."
    res = detector.detect(text)
    assert res.lang == "ru"
    assert res.script == "Cyrl"


def test_french_detection():
    detector = LanguageDetectionService()
    text = "Une nouvelle architecture de réseau neuronal est présentée avec des performances exceptionnelles sur les données."
    res = detector.detect(text)
    assert res.lang == "fr"
    assert res.script == "Latn"


def test_german_detection():
    detector = LanguageDetectionService()
    text = "Die Entwicklung von künstlicher Intelligenz ist ein wichtiger Schritt für die europäische Forschung."
    res = detector.detect(text)
    assert res.lang == "de"
    assert res.script == "Latn"


def test_singleton_instance():
    assert language_detector is not None
    res = language_detector.detect("OpenAI releases new reasoning model.")
    assert res.lang == "en"
