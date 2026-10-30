"""Unit tests for ScopedSubstringVerifier, claim normalization, and benchmark grounding."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.claim_verifier import (
    ScopedSubstringVerifier,
    normalize_text,
    substring_verifier,
)
from ai_security_monitor.domain.entities import Category, Entry


def make_entry_with_text(
    title: str, summary: str, metadata: dict | None = None
) -> Entry:
    return Entry(
        id=uuid4(),
        source_id=uuid4(),
        title=title,
        url=f"https://example.com/{title.replace(' ', '_')}",
        content_hash=f"hash_{title}",
        summary=summary,
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        metadata=metadata or {},
    )


def test_text_normalization():
    """Verify Unicode NFKD decomposition, em-dashes, full-width quotes, and lowercase normalization."""
    raw = "DeepSeek—V3: 671B Parameters & 88.9% on MATH–500!"
    norm = normalize_text(raw)
    assert "deepseek-v3" in norm
    assert "671b" in norm
    assert "88.9%" in norm
    assert "math-500" in norm


def test_token_variant_generation():
    """Verify variant generation for parameters, benchmarks, percentages, and speedups."""
    v = ScopedSubstringVerifier()

    # Parameter count synonyms
    var_72b = v.generate_token_variants("72B")
    assert "72 billion" in var_72b
    assert "72b" in var_72b

    var_billion = v.generate_token_variants("671 billion")
    assert "671b" in var_billion

    # Dash variations
    var_bench = v.generate_token_variants("SWE-bench")
    assert "swe bench" in var_bench
    assert "swebench" in var_bench

    # Percentages
    var_pct = v.generate_token_variants("90.5%")
    assert "90.5 percent" in var_pct
    assert "90.5%" in var_pct

    # Speedups
    var_speed = v.generate_token_variants("4x")
    assert "4 times" in var_speed
    assert "4-fold" in var_speed


def test_numeric_claim_grounding_success():
    """Claims present in source text with minor orthographic differences must verify successfully."""
    entry = make_entry_with_text(
        title="Qwen releases new 72 billion parameter reasoning model",
        summary="Achieves 4-fold speedup in inference with 88.9 percent on standard benchmarks.",
    )

    verifier = ScopedSubstringVerifier()

    # 72B should ground against '72 billion'
    c1 = verifier.verify_claim("72B", entry, claim_type="numeric")
    assert c1.is_verified is True

    # 4x should ground against '4-fold'
    c2 = verifier.verify_claim("4x", entry, claim_type="numeric")
    assert c2.is_verified is True

    # 88.9% should ground against '88.9 percent'
    c3 = verifier.verify_claim("88.9%", entry, claim_type="numeric")
    assert c3.is_verified is True


def test_multilingual_and_raw_original_content_grounding():
    """Claims must verify against original untranslated or unshielded content stored in metadata."""
    entry = make_entry_with_text(
        title="DeepSeek R1 English Announcement",
        summary="English overview of mathematical reasoning milestone.",
        metadata={
            "raw_original_content": "DeepSeek-R1 全面开源，总参数量 671B，激活 37B，在 AIME 2024 达到 79.8% 的高分。",
        },
    )

    verifier = ScopedSubstringVerifier()

    # 671B in Chinese source
    c1 = verifier.verify_claim("671B", entry, claim_type="numeric")
    assert c1.is_verified is True

    # AIME 2024 in Chinese source
    c2 = verifier.verify_claim("AIME 2024", entry, claim_type="benchmark")
    assert c2.is_verified is True

    # 79.8% in Chinese source
    c3 = verifier.verify_claim("79.8%", entry, claim_type="numeric")
    assert c3.is_verified is True


def test_benchmark_metric_filtering_drops_ungrounded_claims():
    """Ungrounded or hallucinated benchmarks not present in source text must be dropped."""
    entry = make_entry_with_text(
        title="DeepSeek-R1 Reasoning Performance",
        summary="The authors evaluate DeepSeek-R1 across MATH-500 and AIME, achieving state-of-the-art results.",
    )

    candidate_metrics = [
        # Grounded item (MATH-500 and AIME are in text)
        {
            "benchmark": "AIME 2024 / MATH-500",
            "score": "79.8%",
            "standing": "Frontier Level",
        },
        # Hallucinated item (Video benchmark not in text)
        {
            "benchmark": "VBench (Video Generation Quality)",
            "score": "95.2%",
            "standing": "World Record",
        },
        # Hallucinated item (Hardware interconnect not in text)
        {
            "benchmark": "Interconnect Fabric (NVLink / IF)",
            "score": "1.8 TB/s",
            "standing": "Cluster Fabric",
        },
    ]

    verified_items, result = substring_verifier.filter_benchmark_metrics(
        entry, candidate_metrics
    )

    # Only AIME / MATH-500 should survive
    assert len(verified_items) == 1
    assert verified_items[0]["benchmark"] == "AIME 2024 / MATH-500"

    # 2 items dropped
    assert len(result.dropped_claims) == 2
    dropped_names = {c.claim_text.split(":")[0] for c in result.dropped_claims}
    assert "VBench (Video Generation Quality)" in dropped_names
    assert "Interconnect Fabric (NVLink / IF)" in dropped_names

    # Grounding score: 1 verified out of 3 total = 1/3
    assert pytest.approx(result.grounding_score, 0.01) == 0.33
    assert pytest.approx(result.hallucination_rate, 0.01) == 0.67
