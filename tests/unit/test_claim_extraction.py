"""
Unit tests for deterministic ClaimExtractionService.
"""

from ai_security_monitor.application.services.claim_extraction_service import (
    ClaimExtractionService,
)


def test_english_claim_extraction() -> None:
    service = ClaimExtractionService()
    text = (
        "DeepSeek releases DeepSeek-V3 with 671B parameters and 128K context window. "
        "Evaluated on AIME 2024: 79.8% and SWE-bench: 49.2% under MIT license."
    )
    claims = service.extract_claims(text)

    # Check evidence span integrity
    for c in claims:
        assert text[c.evidence_span_start : c.evidence_span_end] == c.evidence_text

    fields = {c.field: c.normalized_value for c in claims}
    assert fields["params"] == "671B"
    assert fields["context_window"] == "128K"
    assert "AIME 2024: 79.8%" in [
        c.normalized_value for c in claims if c.field == "benchmark_score"
    ]
    assert "SWE-bench: 49.2%" in [
        c.normalized_value for c in claims if c.field == "benchmark_score"
    ]
    assert fields["license"] == "MIT"


def test_chinese_claim_extraction() -> None:
    service = ClaimExtractionService()
    text = (
        "深度求索发布DeepSeek-V3模型，拥有6710亿参数与128k长文本窗口，"
        "在SWE-bench达到49.2%，采用Apache-2.0开源协议。"
    )
    claims = service.extract_claims(text)

    # Check evidence span integrity
    for c in claims:
        assert text[c.evidence_span_start : c.evidence_span_end] == c.evidence_text

    fields = {c.field: c.normalized_value for c in claims}
    assert fields["params"] == "671B"
    assert fields["context_window"] == "128K"
    assert "SWE-bench: 49.2%" in [
        c.normalized_value for c in claims if c.field == "benchmark_score"
    ]
    assert fields["license"] == "Apache-2.0"


def test_chinese_numeric_scaling() -> None:
    service = ClaimExtractionService()
    text = "该系列包含700亿参数与320亿参数两款尺寸，支持100万上下文。"
    claims = service.extract_claims(text)

    params = [c.normalized_value for c in claims if c.field == "params"]
    assert "70B" in params
    assert "32B" in params

    context = [c.normalized_value for c in claims if c.field == "context_window"]
    assert "1000K" in context or "1M" in context


def test_no_overlapping_evidence_spans() -> None:
    service = ClaimExtractionService()
    text = "70B parameters with 32k context window and GSM8K: 88.5%."
    claims = service.extract_claims(text)

    for i in range(len(claims) - 1):
        assert claims[i].evidence_span_end <= claims[i + 1].evidence_span_start
