"""
Deterministic Claim Extraction Service.

Extracts structured, ground-truth claims with exact character-offset evidence spans
from native-language documents (Chinese & English) without translation distortion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ExtractedClaim:
    """Structured claim extracted directly from native document text."""

    field: str  # 'params', 'context_window', 'benchmark_score', 'license'
    normalized_value: str
    unit: str | None
    evidence_span_start: int
    evidence_span_end: int
    evidence_text: str
    confidence: float = 1.0


class ClaimExtractionService:
    """Extracts factual claims from native Chinese and English texts."""

    def __init__(self) -> None:
        self._init_patterns()

    def _init_patterns(self) -> None:
        # 1. Parameter count patterns (e.g. 671B, 6710亿参数, 70B, 32B, 14B)
        self.params_en_pattern = re.compile(
            r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)\s*(B|billion)\s*(?:parameters?|params)?(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )
        self.params_zh_pattern = re.compile(
            r"(\d+(?:\.\d+)?)\s*(?:万亿|千亿|百亿|十亿|0亿|亿)\s*参数",
        )

        # 2. Context window patterns (e.g. 128k context, 1M context, 128K上下文)
        self.context_en_pattern = re.compile(
            r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)\s*([kKmM])\s*(?:tokens?|context(?: window)?|window)?(?![A-Za-z0-9_])",
        )
        self.context_zh_pattern = re.compile(
            r"(\d+(?:\.\d+)?)\s*([kKmM万])\s*(?:token|上下文|长文本|窗口)",
        )

        # 3. Benchmark score patterns
        bench_names = r"(?:AIME(?:\s*2024)?|SWE-bench(?:\s*Verified)?|MATH-500|MATH\s*500|GSM8K|MMLU-Pro|MMLU|LiveCodeBench|HumanEval|GPQA)"
        self.benchmark_pattern = re.compile(
            rf"(?<![A-Za-z0-9_])({bench_names})\s*(?::|：|达到|scored?|is|of|\()\s*(\d+(?:\.\d+)?%?)",
            re.IGNORECASE,
        )

        # 4. License patterns
        self.license_pattern = re.compile(
            r"(?<![A-Za-z0-9_])(Apache[-\s]2\.0|MIT|DeepSeek License|Llama Community License|Qwen License)(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )

    def extract_claims(self, text: str) -> list[ExtractedClaim]:
        """
        Extract claims from text with non-overlapping character offsets.
        Preserves original offsets in the input text.
        """
        if not text:
            return []

        claims: list[ExtractedClaim] = []

        # 1. Parameter counts
        for m in self.params_en_pattern.finditer(text):
            num_str, unit_str = m.group(1), m.group(2).upper()
            val = f"{num_str}B" if unit_str.startswith("B") else f"{num_str}B"
            claims.append(
                ExtractedClaim(
                    field="params",
                    normalized_value=val,
                    unit="parameters",
                    evidence_span_start=m.start(),
                    evidence_span_end=m.end(),
                    evidence_text=m.group(0),
                    confidence=0.95,
                )
            )

        for m in self.params_zh_pattern.finditer(text):
            raw_match = m.group(0)
            # Normalize e.g. 6710亿 -> 671B, 700亿 -> 70B, 320亿 -> 32B, 140亿 -> 14B, 70亿 -> 7B
            match_num = re.search(r"(\d+(?:\.\d+)?)", raw_match)
            if match_num:
                num = float(match_num.group(1))
                if "0亿" in raw_match or num >= 10:
                    b_val = num / 10 if ("0亿" in raw_match or num >= 100) else num
                    norm = f"{b_val:g}B"
                else:
                    norm = f"{num:g}B"
                claims.append(
                    ExtractedClaim(
                        field="params",
                        normalized_value=norm,
                        unit="parameters",
                        evidence_span_start=m.start(),
                        evidence_span_end=m.end(),
                        evidence_text=raw_match,
                        confidence=0.95,
                    )
                )

        # 2. Context window
        # For English: only match if context/token/window is explicitly mentioned
        for m in self.context_en_pattern.finditer(text):
            full = m.group(0)
            if not any(kw in full.lower() for kw in ("token", "context", "window")):
                continue
            num_str, scale = m.group(1), m.group(2).upper()
            norm = f"{num_str}{scale}"
            claims.append(
                ExtractedClaim(
                    field="context_window",
                    normalized_value=norm,
                    unit="tokens",
                    evidence_span_start=m.start(),
                    evidence_span_end=m.end(),
                    evidence_text=full,
                    confidence=0.9,
                )
            )

        for m in self.context_zh_pattern.finditer(text):
            num_str, scale = m.group(1), m.group(2)
            if scale == "万":
                norm = f"{float(num_str) * 10:g}K"
            else:
                norm = f"{num_str}{scale.upper()}"
            claims.append(
                ExtractedClaim(
                    field="context_window",
                    normalized_value=norm,
                    unit="tokens",
                    evidence_span_start=m.start(),
                    evidence_span_end=m.end(),
                    evidence_text=m.group(0),
                    confidence=0.9,
                )
            )

        # 3. Benchmark scores
        for m in self.benchmark_pattern.finditer(text):
            b_name = m.group(1).strip()
            score = m.group(2).strip()
            if not score.endswith("%"):
                score = f"{score}%"
            # Canonicalize benchmark name
            b_clean = re.sub(r"\s+", " ", b_name)
            norm = f"{b_clean}: {score}"
            claims.append(
                ExtractedClaim(
                    field="benchmark_score",
                    normalized_value=norm,
                    unit="%",
                    evidence_span_start=m.start(),
                    evidence_span_end=m.end(),
                    evidence_text=m.group(0),
                    confidence=0.95,
                )
            )

        # 4. Licenses
        for m in self.license_pattern.finditer(text):
            lic_match = m.group(1).strip()
            lic_norm = "Apache-2.0" if "apache" in lic_match.lower() else lic_match
            claims.append(
                ExtractedClaim(
                    field="license",
                    normalized_value=lic_norm,
                    unit="license",
                    evidence_span_start=m.start(),
                    evidence_span_end=m.end(),
                    evidence_text=m.group(0),
                    confidence=0.95,
                )
            )

        # Sort claims by offset and eliminate overlaps preferring longer spans
        claims.sort(
            key=lambda c: (
                c.evidence_span_start,
                -(c.evidence_span_end - c.evidence_span_start),
            )
        )
        non_overlapping: list[ExtractedClaim] = []
        last_end = -1

        for c in claims:
            if c.evidence_span_start >= last_end:
                non_overlapping.append(c)
                last_end = c.evidence_span_end

        return non_overlapping


claim_extractor = ClaimExtractionService()
