"""
Narrowly Scoped Substring Verifier for Grounding Numeric Claims and Benchmark Suites.
Enforces epistemic factuality by verifying claimed numbers, benchmarks, and model identifiers
against source text with Unicode, whitespace, and synonym normalization.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry

logger = get_logger(__name__)


def normalize_text(text: str) -> str:
    """Normalize text across unicode, whitespace, and dash variations."""
    if not text:
        return ""
    # Unicode NFKD decomposition
    normalized = unicodedata.normalize("NFKD", text)
    # Replace various dash/hyphen characters with standard ASCII minus
    normalized = re.sub(r"[\u2010-\u2015\u2212\uFE58\uFE63\uFF0D]", "-", normalized)
    # Normalize quotes
    normalized = re.sub(r"[\u2018\u2019\u201A\u201B]", "'", normalized)
    normalized = re.sub(r"[\u201C\u201D\u201E\u201F]", '"', normalized)
    # Lowercase
    normalized = normalized.lower()
    # Normalize whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def extract_grounding_corpus(entry: Entry) -> str:
    """Aggregate all candidate source groundings including unshielded / raw text."""
    parts: list[str] = []
    if entry.title:
        parts.append(entry.title)
    if entry.summary:
        parts.append(entry.summary)
    try:
        content_val = entry.content  # type: ignore[attr-defined]
        if content_val:
            parts.append(str(content_val))
    except AttributeError:
        pass
    if entry.metadata:
        for k in (
            "raw_content",
            "raw_original_content",
            "original_chinese",
            "original_title",
            "unshielded_content",
            "source_snippet",
            "description",
        ):
            val = entry.metadata.get(k)
            if val and isinstance(val, str):
                parts.append(val)
    return " \n ".join(parts)


@dataclass
class VerifiedClaim:
    """A claim verified or dropped by the substring verifier."""

    claim_text: str
    claim_type: str  # "numeric", "benchmark", "model_id"
    is_verified: bool
    matched_term: str | None = None
    original_item: Any = None
    original_value: Any = None


@dataclass
class VerificationResult:
    """Result of verification pass over an entry's extracted telemetry."""

    verified_claims: list[VerifiedClaim] = field(default_factory=list)
    dropped_claims: list[VerifiedClaim] = field(default_factory=list)
    grounding_score: float = 1.0  # 0.0 to 1.0

    @property
    def total_claims(self) -> int:
        return len(self.verified_claims) + len(self.dropped_claims)

    @property
    def hallucination_rate(self) -> float:
        if not self.total_claims:
            return 0.0
        return len(self.dropped_claims) / self.total_claims


class ScopedSubstringVerifier:
    """Deterministic, narrowly scoped fact-checking verifier for AI telemetry."""

    KNOWN_BENCHMARK_FAMILIES = (
        "math-500",
        "aime",
        "swe-bench",
        "mmlu-pro",
        "mmlu",
        "gpqa",
        "humaneval",
        "gsm8k",
        "gaia",
        "webarena",
        "vbench",
        "toolbench",
        "mt-bench",
        "arc-c",
        "hellaswag",
        "drop",
        "livecodebench",
    )

    def generate_token_variants(self, term: str) -> list[str]:
        """Generate normalized variations for a numeric or named benchmark term."""
        norm = normalize_text(term)
        if not norm:
            return []

        variants = {norm}

        # Dash vs space variations (e.g. "math-500" <-> "math 500" <-> "math500")
        if "-" in norm:
            variants.add(norm.replace("-", " "))
            variants.add(norm.replace("-", ""))
        if " " in norm:
            variants.add(norm.replace(" ", "-"))
            variants.add(norm.replace(" ", ""))

        # Parameter count variations (e.g. "72b" <-> "72 billion")
        param_match = re.match(r"^(\d+(?:\.\d+)?)\s*b$", norm)
        if param_match:
            num = param_match.group(1)
            variants.add(f"{num} billion")
            variants.add(f"{num}-billion")
            variants.add(f"{num}b")

        billion_match = re.match(r"^(\d+(?:\.\d+)?)\s*(?:-| )?billion$", norm)
        if billion_match:
            num = billion_match.group(1)
            variants.add(f"{num}b")
            variants.add(f"{num}-b")

        # Percentage variations (e.g. "88.9%" <-> "88.9 percent")
        pct_match = re.match(r"^(\d+(?:\.\d+)?)\s*%$", norm)
        if pct_match:
            num = pct_match.group(1)
            variants.add(f"{num} percent")
            variants.add(f"{num}%")
            variants.add(f"{num} %")

        # Speedup variations (e.g. "4x" <-> "4-fold" <-> "4 times")
        speedup_match = re.match(r"^(\d+(?:\.\d+)?)\s*x$", norm)
        if speedup_match:
            num = speedup_match.group(1)
            variants.add(f"{num}x")
            variants.add(f"{num} times")
            variants.add(f"{num}-fold")

        return list(variants)

    def check_substring_presence(
        self, target_term: str, corpus_normalized: str
    ) -> tuple[bool, str | None]:
        """Verify if any normalized variant of the target term exists in normalized corpus."""
        variants = self.generate_token_variants(target_term)
        for var in variants:
            # Word boundary regex or direct substring for composite terms
            if len(var) <= 2:
                # Short tokens need strict boundaries
                pattern = r"(?<![a-z0-9])" + re.escape(var) + r"(?![a-z0-9])"
                if re.search(pattern, corpus_normalized):
                    return True, var
            else:
                if var in corpus_normalized:
                    return True, var
        return False, None

    def verify_claim(
        self, claim_text: str, entry: Entry, claim_type: str = "numeric"
    ) -> VerifiedClaim:
        """Verify an isolated numeric or benchmark claim against source entry text."""
        corpus = extract_grounding_corpus(entry)
        corpus_norm = normalize_text(corpus)

        is_present, matched = self.check_substring_presence(claim_text, corpus_norm)
        return VerifiedClaim(
            claim_text=claim_text,
            claim_type=claim_type,
            is_verified=is_present,
            matched_term=matched,
            original_value=claim_text,
        )

    def filter_benchmark_metrics(
        self, entry: Entry, metrics: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], VerificationResult]:
        """Filter a list of benchmark metrics, strictly dropping ungrounded/hallucinated items.

        Policy:
        - If the benchmark name or score is present in the source text, retain it.
        - If both the benchmark and score are absent from the source text, DROP it.
        """
        if not metrics:
            return [], VerificationResult()

        corpus = extract_grounding_corpus(entry)
        corpus_norm = normalize_text(corpus)

        verified_items: list[dict[str, Any]] = []
        result = VerificationResult()

        for item in metrics:
            bench_name = str(item.get("benchmark", "")).strip()
            score_val = str(item.get("score", "")).strip()

            # Check benchmark name
            bench_ok, bench_match = self.check_substring_presence(
                bench_name, corpus_norm
            )

            # Check individual sub-benchmarks if name is composite (e.g. "AIME 2024 / MATH-500")
            if not bench_ok and "/" in bench_name:
                for sub in bench_name.split("/"):
                    sub_ok, sub_match = self.check_substring_presence(
                        sub.strip(), corpus_norm
                    )
                    if sub_ok:
                        bench_ok = True
                        bench_match = sub_match
                        break

            # Check score presence if benchmark wasn't found directly
            score_ok, score_match = False, None
            if score_val:
                # Extract primary numeric value from score string (e.g. "79.8%" from "79.8% (Pass@1)")
                num_match = re.search(
                    r"\d+(?:\.\d+)?(?:\s*%|\s*x|\s*b|\s*tflops)?",
                    score_val,
                    re.IGNORECASE,
                )
                if num_match:
                    score_ok, score_match = self.check_substring_presence(
                        num_match.group(0), corpus_norm
                    )

            # A claim is verified if either the benchmark is explicitly cited or its exact numeric score is grounded
            if bench_ok or score_ok:
                verified_claim = VerifiedClaim(
                    claim_text=f"{bench_name}: {score_val}",
                    claim_type="benchmark",
                    is_verified=True,
                    matched_term=bench_match or score_match,
                    original_item=item,
                )
                result.verified_claims.append(verified_claim)
                verified_items.append(item)
            else:
                dropped_claim = VerifiedClaim(
                    claim_text=f"{bench_name}: {score_val}",
                    claim_type="benchmark",
                    is_verified=False,
                    matched_term=None,
                    original_item=item,
                )
                result.dropped_claims.append(dropped_claim)
                logger.info(
                    f"Dropped ungrounded benchmark claim: '{bench_name}: {score_val}' (entry: {entry.title[:40]})"
                )

        if result.total_claims > 0:
            result.grounding_score = len(result.verified_claims) / result.total_claims

        return verified_items, result


substring_verifier = ScopedSubstringVerifier()
