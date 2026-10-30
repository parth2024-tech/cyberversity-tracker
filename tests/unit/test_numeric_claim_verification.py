"""Unit tests for Feature 10: Numeric Claim Verification.

Verifies:
1. Normalization table: 72B = 72 billion = 720亿; 128K = 131072; 1M = 100万; $0.14 = 0.14美元.
2. Near-miss numbers rejection (strict numerical boundary: 72B vs 7.2B, 7B vs 72B, 14B vs 140B).
3. Translated-source case: English claims verified against original Chinese grounding corpus.
4. Failure behavior: Drops ungrounded claims, preserves grammatical prose summary, and logs drops.
5. Epistemic invariant: Never claims '0% hallucination' (presence in text != attribution).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from ai_security_monitor.application.services.claim_verifier import (
    ClaimType,
    ScopedSubstringVerifier,
    substring_verifier,
)
from ai_security_monitor.domain.entities import Category, Entry


def make_entry(title: str, summary: str, metadata: dict | None = None) -> Entry:
    """Helper to construct Entry with metadata."""
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


class TestNormalizationTable:
    """Test standard normalizer equivalencies across English, Chinese, metric, and binary units."""

    def test_parameter_count_equivalencies(self):
        verifier = ScopedSubstringVerifier()

        # 72B <-> 72 billion <-> 720亿
        entry_cn = make_entry(
            "Qwen Release", "Summary", {"raw_original_content": "开源 720亿 参数模型"}
        )
        assert (
            verifier.verify_claim(
                "72B", entry_cn, ClaimType.PARAMETER_COUNT
            ).is_verified
            is True
        )
        assert (
            verifier.verify_claim(
                "72 billion", entry_cn, ClaimType.PARAMETER_COUNT
            ).is_verified
            is True
        )

        entry_en = make_entry(
            "Qwen Release",
            "Summary",
            {"raw_original_content": "Releases 72B parameter model"},
        )
        assert (
            verifier.verify_claim(
                "720亿", entry_en, ClaimType.PARAMETER_COUNT
            ).is_verified
            is True
        )

        # 7B <-> 70亿
        entry_7b = make_entry(
            "DeepSeek 7B", "Summary", {"raw_original_content": "70亿参数小模型"}
        )
        assert (
            verifier.verify_claim("7B", entry_7b, ClaimType.PARAMETER_COUNT).is_verified
            is True
        )

        # 671B <-> 6710亿
        entry_671b = make_entry(
            "DeepSeek V3", "Summary", {"raw_original_content": "总参数 6710亿"}
        )
        assert (
            verifier.verify_claim(
                "671B", entry_671b, ClaimType.PARAMETER_COUNT
            ).is_verified
            is True
        )

        # 1.5T <-> 1.5万亿
        entry_1_5t = make_entry(
            "Frontier MoE", "Summary", {"raw_original_content": "总计 1.5万亿 参数"}
        )
        assert (
            verifier.verify_claim(
                "1.5T", entry_1_5t, ClaimType.PARAMETER_COUNT
            ).is_verified
            is True
        )
        assert (
            verifier.verify_claim(
                "1.5 trillion", entry_1_5t, ClaimType.PARAMETER_COUNT
            ).is_verified
            is True
        )

    def test_context_length_equivalencies(self):
        verifier = ScopedSubstringVerifier()

        # 128K <-> 131072 (binary power) <-> 128000 <-> 128k 上下文
        entry_131k = make_entry(
            "Long Context",
            "Summary",
            {"raw_original_content": "supports 131072 tokens"},
        )
        assert (
            verifier.verify_claim(
                "128K", entry_131k, ClaimType.CONTEXT_LENGTH
            ).is_verified
            is True
        )

        entry_128k_cn = make_entry(
            "Long Context", "Summary", {"raw_original_content": "支持 128k 上下文"}
        )
        assert (
            verifier.verify_claim(
                "131072", entry_128k_cn, ClaimType.CONTEXT_LENGTH
            ).is_verified
            is True
        )
        assert (
            verifier.verify_claim(
                "128K", entry_128k_cn, ClaimType.CONTEXT_LENGTH
            ).is_verified
            is True
        )

        # 1M <-> 100万 <-> 1,000,000
        entry_1m_cn = make_entry(
            "Kimi Release", "Summary", {"raw_original_content": "支持 100万 上下文窗口"}
        )
        assert (
            verifier.verify_claim(
                "1M", entry_1m_cn, ClaimType.CONTEXT_LENGTH
            ).is_verified
            is True
        )
        assert (
            verifier.verify_claim(
                "1,000,000", entry_1m_cn, ClaimType.CONTEXT_LENGTH
            ).is_verified
            is True
        )

    def test_benchmark_and_speedup_equivalencies(self):
        verifier = ScopedSubstringVerifier()

        # 88.9% <-> 88.9 percent
        entry_pct = make_entry(
            "Math Benchmark",
            "Summary",
            {"raw_original_content": "scored 88.9 percent on MATH-500"},
        )
        assert (
            verifier.verify_claim(
                "88.9%", entry_pct, ClaimType.BENCHMARK_SCORE
            ).is_verified
            is True
        )

        # 4x <-> 4-fold <-> 4倍
        entry_speed_cn = make_entry(
            "Inference Optimization",
            "Summary",
            {"raw_original_content": "吞吐量提升 4倍"},
        )
        assert (
            verifier.verify_claim(
                "4x", entry_speed_cn, ClaimType.BENCHMARK_SCORE
            ).is_verified
            is True
        )
        assert (
            verifier.verify_claim(
                "4-fold", entry_speed_cn, ClaimType.BENCHMARK_SCORE
            ).is_verified
            is True
        )

    def test_price_equivalencies(self):
        verifier = ScopedSubstringVerifier()

        # $0.14 <-> 0.14美元 <-> 0.14 usd
        entry_price_cn = make_entry(
            "API Pricing",
            "Summary",
            {"raw_original_content": "每百万 token 仅需 0.14美元"},
        )
        assert (
            verifier.verify_claim("$0.14", entry_price_cn, ClaimType.PRICE).is_verified
            is True
        )
        assert (
            verifier.verify_claim(
                "0.14 usd", entry_price_cn, ClaimType.PRICE
            ).is_verified
            is True
        )

        # ¥2 <-> 2元 <-> 2 rmb
        entry_rmb = make_entry(
            "API Pricing",
            "Summary",
            {"raw_original_content": "推理成本 2元 / 百万 tokens"},
        )
        assert (
            verifier.verify_claim("¥2", entry_rmb, ClaimType.PRICE).is_verified is True
        )
        assert (
            verifier.verify_claim("2元", entry_rmb, ClaimType.PRICE).is_verified is True
        )


class TestNearMissNumbersRejection:
    """Verify that strict numerical boundary checking prevents near-miss false positive grounding."""

    def test_parameter_count_near_misses(self):
        verifier = ScopedSubstringVerifier()

        # 72B must NOT ground against 7.2B
        entry_7_2b = make_entry(
            "Small Model",
            "Summary",
            {"raw_original_content": "Released 7.2B parameter model"},
        )
        res = verifier.verify_claim("72B", entry_7_2b, ClaimType.PARAMETER_COUNT)
        assert res.is_verified is False

        # 7.2B must NOT ground against 72B
        entry_72b = make_entry(
            "Large Model",
            "Summary",
            {"raw_original_content": "Released 72B parameter model"},
        )
        res = verifier.verify_claim("7.2B", entry_72b, ClaimType.PARAMETER_COUNT)
        assert res.is_verified is False

        # 7B must NOT ground against 72B or 70B
        res_7b = verifier.verify_claim("7B", entry_72b, ClaimType.PARAMETER_COUNT)
        assert res_7b.is_verified is False

        # 14B must NOT ground against 140B
        entry_140b = make_entry(
            "MoE Model", "Summary", {"raw_original_content": "Total 140B parameters"}
        )
        res_14b = verifier.verify_claim("14B", entry_140b, ClaimType.PARAMETER_COUNT)
        assert res_14b.is_verified is False

        # Chinese near-miss: 720亿 must NOT ground against 7200亿 or 72亿
        entry_7200yi = make_entry(
            "Giant Model", "Summary", {"raw_original_content": "模型包含 7200亿 参数"}
        )
        assert (
            verifier.verify_claim(
                "720亿", entry_7200yi, ClaimType.PARAMETER_COUNT
            ).is_verified
            is False
        )

        entry_72yi = make_entry(
            "Medium Model", "Summary", {"raw_original_content": "模型包含 72亿 参数"}
        )
        assert (
            verifier.verify_claim(
                "720亿", entry_72yi, ClaimType.PARAMETER_COUNT
            ).is_verified
            is False
        )

    def test_context_and_benchmark_near_misses(self):
        verifier = ScopedSubstringVerifier()

        # 128K must NOT ground against 12.8K
        entry_12_8k = make_entry(
            "Short Context", "Summary", {"raw_original_content": "12.8K context window"}
        )
        assert (
            verifier.verify_claim(
                "128K", entry_12_8k, ClaimType.CONTEXT_LENGTH
            ).is_verified
            is False
        )

        # 88.9% must NOT ground against 88.0% or 8.89%
        entry_pct_diff = make_entry(
            "Eval", "Summary", {"raw_original_content": "achieved 88.0% on benchmark"}
        )
        assert (
            verifier.verify_claim(
                "88.9%", entry_pct_diff, ClaimType.BENCHMARK_SCORE
            ).is_verified
            is False
        )

        entry_pct_scale = make_entry(
            "Eval", "Summary", {"raw_original_content": "achieved 8.89% on benchmark"}
        )
        assert (
            verifier.verify_claim(
                "88.9%", entry_pct_scale, ClaimType.BENCHMARK_SCORE
            ).is_verified
            is False
        )

        # $0.14 must NOT ground against $1.14
        entry_price_diff = make_entry(
            "Cost", "Summary", {"raw_original_content": "priced at $1.14 per 1M"}
        )
        assert (
            verifier.verify_claim(
                "$0.14", entry_price_diff, ClaimType.PRICE
            ).is_verified
            is False
        )


class TestTranslatedSourceGrounding:
    """Verify that English claims in summaries ground correctly against original untranslated foreign source text."""

    def test_english_summary_verified_against_chinese_source(self):
        # Original Chinese source announcement
        entry = make_entry(
            title="Qwen 2.5 Announcement",
            summary="English overview of Alibaba foundation model update.",
            metadata={
                "raw_original_content": "阿里云正式开源通义千问 720亿 参数旗舰模型，支持 128k 上下文窗口，在 AIME 2024 达到 79.8% 高分，API 定价仅 0.14美元 / 百万 tokens。",
            },
        )

        verifier = substring_verifier

        # Claim 1: 72B (grounds to 720亿)
        c1 = verifier.verify_claim("72B", entry, ClaimType.PARAMETER_COUNT)
        assert c1.is_verified is True
        assert c1.matched_term in ("720亿", "720 亿")

        # Claim 2: 128K (grounds to 128k 上下文)
        c2 = verifier.verify_claim("128K", entry, ClaimType.CONTEXT_LENGTH)
        assert c2.is_verified is True

        # Claim 3: 79.8% (grounds to 79.8%)
        c3 = verifier.verify_claim("79.8%", entry, ClaimType.BENCHMARK_SCORE)
        assert c3.is_verified is True

        # Claim 4: $0.14 (grounds to 0.14美元)
        c4 = verifier.verify_claim("$0.14", entry, ClaimType.PRICE)
        assert c4.is_verified is True


class TestFailureBehaviorAndProsePreservation:
    """Verify failure behavior: ungrounded claims are dropped while preserving grammatical prose."""

    def test_drop_ungrounded_benchmark_preserves_prose(self):
        verifier = ScopedSubstringVerifier()

        # Source only contains 72B and 128k, GPQA 99.8% is a hallucination
        entry = make_entry(
            title="Qwen 2.5 Release",
            summary="Initial summary",
            metadata={
                "raw_original_content": "阿里云开源 720亿 参数模型，提供 128k 上下文。"
            },
        )

        summary_with_hallucination = "Alibaba released Qwen 2.5 with 72B parameters, 128K context window, achieving 99.8% on GPQA."

        cleaned_text, result = verifier.clean_summary_claims(
            entry, summary_with_hallucination
        )

        # 72B and 128K verified
        assert len(result.verified_claims) >= 2
        verified_texts = {c.claim_text for c in result.verified_claims}
        assert any("72b" in t.lower() for t in verified_texts)
        assert any("128k" in t.lower() for t in verified_texts)

        # 99.8% dropped
        assert len(result.dropped_claims) >= 1
        dropped_texts = {c.claim_text for c in result.dropped_claims}
        assert any("99.8%" in t for t in dropped_texts)

        # Resulting prose preserves 72B and 128K but cleanly drops GPQA 99.8%
        assert "72B parameters" in cleaned_text
        assert "128K context window" in cleaned_text
        assert "99.8%" not in cleaned_text
        assert cleaned_text.endswith(".")
        assert ", ," not in cleaned_text

    def test_epistemic_disclaimer_invariant(self):
        """Verifier must never claim 0% hallucination."""
        verifier = ScopedSubstringVerifier()
        entry = make_entry("Title", "Summary", {"raw_original_content": "72B model"})
        res = verifier.verify_claim("72B", entry, ClaimType.PARAMETER_COUNT)

        # Disclaimer confirms presence, notes absence of attribution guarantee
        assert "never claim 0% hallucination" in res.confidence_note
        _, clean_res = verifier.clean_summary_claims(entry, "Releases 72B model.")
        assert "never claim 0% hallucination" in clean_res.epistemic_disclaimer
