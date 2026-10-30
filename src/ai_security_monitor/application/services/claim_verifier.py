"""
Narrowly Scoped Substring Verifier for Grounding Numeric Claims and Benchmark Suites.
Enforces epistemic factuality by verifying claimed numbers, benchmarks, and model identifiers
against source text with Unicode, whitespace, and synonym normalization.

Adheres strictly to Feature 10 (Numeric Claim Verification):
- Extracts claims only of type: parameter count, context length, benchmark score, price.
- Normalizes units: 72B = 72 billion = 720亿; 128K = 131072; 1M = 100万; $0.14 = 0.14美元.
- Verifies against ORIGINAL-language source text before translations.
- Failure behavior: drops ungrounded claims, logs the drop, and preserves prose summary.
- Epistemic invariant: Never claims '0% hallucination'; confirms presence in source corpus.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry

logger = get_logger(__name__)

EPISTEMIC_DISCLAIMER = (
    "Grounding verification confirms presence of claimed numbers or benchmarks in source text; "
    "it does not guarantee attribution to the correct model or entity (never claim 0% hallucination)."
)


class ClaimType(str, Enum):
    """Supported claim types for deterministic numeric verification."""

    PARAMETER_COUNT = "parameter_count"
    CONTEXT_LENGTH = "context_length"
    BENCHMARK_SCORE = "benchmark_score"
    PRICE = "price"
    BENCHMARK_NAME = "benchmark"
    GENERIC_NUMERIC = "numeric"


def normalize_text(text: str) -> str:
    """Normalize text across unicode, whitespace, dashes, and quotes."""
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
    """Aggregate all candidate source groundings, strictly prioritizing original untranslated text."""
    parts: list[str] = []

    # 1. Prioritize untranslated original text from metadata (crucial for Chinese/foreign sources)
    if entry.metadata:
        for k in (
            "raw_original_content",
            "original_chinese",
            "original_content",
            "original_title",
            "unshielded_content",
            "source_snippet",
            "raw_content",
            "description",
        ):
            val = entry.metadata.get(k)
            if val and isinstance(val, str) and val.strip():
                parts.append(val.strip())

    # 2. Add entry primary text fields
    if entry.title:
        parts.append(entry.title.strip())
    if entry.summary:
        parts.append(entry.summary.strip())
    try:
        content_val = getattr(entry, "content", None)
        if content_val and isinstance(content_val, str) and content_val.strip():
            parts.append(content_val.strip())
    except AttributeError:
        pass

    return " \n ".join(parts)


@dataclass
class ExtractedClaim:
    """A numeric or benchmark claim extracted from text."""

    claim_text: str
    claim_type: ClaimType
    normalized_value: str
    raw_span: str = ""
    start_pos: int = 0
    end_pos: int = 0


@dataclass
class VerifiedClaim:
    """A claim verified or dropped by the substring verifier."""

    claim_text: str
    claim_type: str
    is_verified: bool
    matched_term: str | None = None
    original_item: Any = None
    original_value: Any = None
    confidence_note: str = EPISTEMIC_DISCLAIMER


@dataclass
class VerificationResult:
    """Result of verification pass over an entry's extracted telemetry."""

    verified_claims: list[VerifiedClaim] = field(default_factory=list)
    dropped_claims: list[VerifiedClaim] = field(default_factory=list)
    grounding_score: float = 1.0  # 0.0 to 1.0
    epistemic_disclaimer: str = EPISTEMIC_DISCLAIMER

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

    def build_boundary_pattern(self, var: str) -> str:
        """Construct strict boundary regex preventing near-miss matches (e.g. 72b vs 7.2b or 7b vs 72b)."""
        escaped = re.escape(var)
        # Left boundary: if var starts with alphanumeric, cannot be preceded by alphanumeric or period
        prefix = r"(?<![a-zA-Z0-9.])" if re.match(r"^[a-zA-Z0-9]", var) else ""
        # Right boundary: if var ends with alphanumeric, cannot be followed by alphanumeric or period
        if re.search(r"[a-zA-Z0-9]$", var):
            suffix = r"(?![a-zA-Z0-9.])"
        else:
            # If ends with non-ascii (e.g. '亿', '万', '%', '元'), cannot be followed by digit or period
            suffix = r"(?![0-9.])"
        return prefix + escaped + suffix

    def generate_token_variants(
        self, term: str, claim_type: ClaimType | str | None = None
    ) -> list[str]:
        """Generate normalized variations across Chinese, English, binary powers, and formatting."""
        norm = normalize_text(term)
        if not norm:
            return []

        variants = {norm}

        # Clean trailing descriptors for matching: e.g. "72b parameters" -> "72b"
        norm_clean = re.sub(
            r"\s*(?:parameters?|params?|tokens?|context|window|accuracy|score|on\s+[\w-]+)$",
            "",
            norm,
        ).strip()
        if norm_clean and norm_clean != norm:
            variants.add(norm_clean)

        # 1. Dash vs space variations (e.g. "math-500" <-> "math 500" <-> "math500")
        for candidate in (norm, norm_clean):
            if "-" in candidate:
                variants.add(candidate.replace("-", " "))
                variants.add(candidate.replace("-", ""))
            if " " in candidate:
                variants.add(candidate.replace(" ", "-"))
                variants.add(candidate.replace(" ", ""))

        # 2. Parameter count variations (e.g. "72b" <-> "72 billion" <-> "720亿")
        for candidate in (norm_clean, norm):
            # Match "72b", "72-b", "72 b"
            param_match = re.match(r"^(\d+(?:\.\d+)?)\s*b$", candidate)
            if param_match:
                num_str = param_match.group(1)
                num_val = float(num_str)
                variants.add(f"{num_str}b")
                variants.add(f"{num_str}-b")
                variants.add(f"{num_str} billion")
                variants.add(f"{num_str}-billion")
                # Chinese: 1B = 10亿 -> 72B = 720亿
                cn_yi = (
                    int(num_val * 10) if (num_val * 10).is_integer() else (num_val * 10)
                )
                variants.add(f"{cn_yi}亿")
                variants.add(f"{cn_yi} 亿")
                variants.add(f"{cn_yi}亿参数")

            # Match "72 billion", "72-billion"
            billion_match = re.match(r"^(\d+(?:\.\d+)?)\s*(?:-| )?billion$", candidate)
            if billion_match:
                num_str = billion_match.group(1)
                num_val = float(num_str)
                variants.add(f"{num_str}b")
                variants.add(f"{num_str}-b")
                variants.add(f"{num_str} billion")
                cn_yi = (
                    int(num_val * 10) if (num_val * 10).is_integer() else (num_val * 10)
                )
                variants.add(f"{cn_yi}亿")
                variants.add(f"{cn_yi} 亿")

            # Match Chinese parameter counts: "720亿", "720 亿"
            cn_yi_match = re.match(r"^(\d+(?:\.\d+)?)\s*亿(?:参数)?$", candidate)
            if cn_yi_match:
                num_str = cn_yi_match.group(1)
                num_val = float(num_str)
                # 720亿 -> 72B
                b_val = (
                    int(num_val / 10) if (num_val / 10).is_integer() else (num_val / 10)
                )
                variants.add(f"{num_str}亿")
                variants.add(f"{num_str} 亿")
                variants.add(f"{b_val}b")
                variants.add(f"{b_val}-b")
                variants.add(f"{b_val} billion")
                variants.add(f"{b_val}-billion")

            # Trillion variations: "1.5t", "1.5 trillion" <-> "1.5万亿" <-> "15000亿"
            t_match = re.match(r"^(\d+(?:\.\d+)?)\s*(?:t|trillion)$", candidate)
            if t_match:
                num_str = t_match.group(1)
                num_val = float(num_str)
                variants.add(f"{num_str}t")
                variants.add(f"{num_str} trillion")
                variants.add(f"{num_str}万亿")
                variants.add(f"{num_str} 万亿")
                yi_val = (
                    int(num_val * 10000)
                    if (num_val * 10000).is_integer()
                    else (num_val * 10000)
                )
                variants.add(f"{yi_val}亿")

            cn_wan_yi_match = re.match(r"^(\d+(?:\.\d+)?)\s*万亿$", candidate)
            if cn_wan_yi_match:
                num_str = cn_wan_yi_match.group(1)
                variants.add(f"{num_str}万亿")
                variants.add(f"{num_str}t")
                variants.add(f"{num_str} trillion")

        # 3. Context length variations: "128k" <-> "131072" <-> "128,000" <-> "128000" <-> "131k"
        for candidate in (norm_clean, norm):
            k_match = re.match(
                r"^(\d+(?:\.\d+)?)\s*k(?: context| tokens?| window)?$", candidate
            )
            if k_match:
                num_str = k_match.group(1)
                num_val = float(num_str)
                variants.add(f"{num_str}k")
                variants.add(f"{num_str}-k")
                variants.add(f"{num_str} k")
                variants.add(f"{num_str}k context")
                variants.add(f"{num_str}k tokens")
                variants.add(f"{num_str}k 上下文")
                # Binary power: 128k -> 131072, 32k -> 32768, 64k -> 65536
                if num_val.is_integer():
                    int_k = int(num_val)
                    exact_tokens = int_k * 1024
                    variants.add(str(exact_tokens))
                    variants.add(f"{exact_tokens:,}")
                    dec_tokens = int_k * 1000
                    variants.add(str(dec_tokens))
                    variants.add(f"{dec_tokens:,}")
                    if exact_tokens != dec_tokens:
                        variants.add(f"{exact_tokens // 1000}k")

            # Context 1M <-> 100万 <-> 1,000,000
            m_match = re.match(
                r"^(\d+(?:\.\d+)?)\s*m(?: context| tokens?| window)?$", candidate
            )
            if m_match:
                num_str = m_match.group(1)
                num_val = float(num_str)
                variants.add(f"{num_str}m")
                variants.add(f"{num_str} m")
                variants.add(f"{num_str}m context")
                variants.add(f"{num_str}m tokens")
                variants.add(f"{num_str}m 上下文")
                # 1M = 100万
                wan_val = (
                    int(num_val * 100)
                    if (num_val * 100).is_integer()
                    else (num_val * 100)
                )
                variants.add(f"{wan_val}万")
                variants.add(f"{wan_val} 万")
                variants.add(f"{wan_val}万上下文")
                tokens = int(num_val * 1_000_000)
                variants.add(str(tokens))
                variants.add(f"{tokens:,}")

            cn_wan_match = re.match(r"^(\d+(?:\.\d+)?)\s*万(?:上下文)?$", candidate)
            if cn_wan_match:
                num_str = cn_wan_match.group(1)
                num_val = float(num_str)
                variants.add(f"{num_str}万")
                variants.add(f"{num_str} 万")
                m_val = num_val / 100
                m_str = str(int(m_val)) if m_val.is_integer() else str(m_val)
                variants.add(f"{m_str}m")
                variants.add(f"{m_str} million")

        # Match exact power numbers: 131072, 65536, 32768, 1048576, 1000000
        exact_pow_map = {
            "131072": ("128k", "131k", "128000", "128,000", "131072", "131,072"),
            "65536": ("64k", "65k", "64000", "64,000", "65536", "65,536"),
            "32768": ("32k", "32000", "32,000", "32768", "32,768"),
            "1048576": ("1m", "100万", "1000000", "1,000,000", "1048576"),
            "1000000": ("1m", "100万", "1000000", "1,000,000", "1 million"),
            "262144": ("256k", "262k", "256000", "256,000", "262144"),
        }
        clean_num = norm_clean.replace(",", "").strip()
        if clean_num in exact_pow_map:
            for alt in exact_pow_map[clean_num]:
                variants.add(alt)

        # 4. Percentage variations (e.g. "88.9%" <-> "88.9 percent")
        for candidate in (norm_clean, norm):
            pct_match = re.match(r"^(\d+(?:\.\d+)?)\s*%$", candidate)
            if pct_match:
                num = pct_match.group(1)
                variants.add(f"{num} percent")
                variants.add(f"{num}%")
                variants.add(f"{num} %")

        # 5. Speedup variations (e.g. "4x" <-> "4-fold" <-> "4 times" <-> "4倍")
        for candidate in (norm_clean, norm):
            speedup_match = re.match(
                r"^(\d+(?:\.\d+)?)\s*(?:x|-fold|fold|times|倍)$", candidate
            )
            if speedup_match:
                num = speedup_match.group(1)
                variants.add(f"{num}x")
                variants.add(f"{num} times")
                variants.add(f"{num}-fold")
                variants.add(f"{num}倍")
                variants.add(f"{num} 倍")

        # 6. Price variations (e.g. "$0.14" <-> "0.14美元" <-> "0.14 usd")
        for candidate in (norm_clean, norm):
            price_match = re.match(
                r"^\$?\s*(\d+(?:\.\d+)?)\s*(bn|billion|m|million|k)?\s*(?:\$|usd|dollars?|dollar|美元)?$",
                candidate,
            )
            if price_match and any(
                s in candidate for s in ("$", "usd", "dollar", "dollars", "美元")
            ):
                num = price_match.group(1)
                scale = price_match.group(2) or ""
                if scale in ("bn", "billion"):
                    variants.add(f"${num}bn")
                    variants.add(f"${num} billion")
                    variants.add(f"{num} billion dollars")
                    variants.add(f"{num}bn usd")
                elif scale in ("m", "million"):
                    variants.add(f"${num}m")
                    variants.add(f"${num} million")
                    variants.add(f"{num} million dollars")
                else:
                    variants.add(f"${num}")
                    variants.add(f"$ {num}")
                    variants.add(f"{num}$")
                    variants.add(f"{num} usd")
                    variants.add(f"{num} dollar")
                    variants.add(f"{num} dollars")
                    variants.add(f"{num}美元")
                    variants.add(f"{num} 美元")

            rmb_match = re.match(
                r"^[¥￥]?\s*(\d+(?:\.\d+)?)\s*(?:元|rmb|cny)?$", candidate
            )
            if rmb_match and any(
                s in candidate for s in ("¥", "￥", "元", "rmb", "cny")
            ):
                num = rmb_match.group(1)
                variants.add(f"¥{num}")
                variants.add(f"{num}元")
                variants.add(f"{num} 元")
                variants.add(f"{num} rmb")
                variants.add(f"{num} cny")

        return list(variants)

    def check_substring_presence(
        self,
        target_term: str,
        corpus_normalized: str,
        claim_type: ClaimType | str | None = None,
    ) -> tuple[bool, str | None]:
        """Verify if any normalized variant exists in corpus using strict numerical boundaries."""
        variants = self.generate_token_variants(target_term, claim_type)
        for var in variants:
            pat = self.build_boundary_pattern(var)
            match = re.search(pat, corpus_normalized, re.IGNORECASE)
            if match:
                return True, var
        return False, None

    def extract_claims(self, text: str) -> list[ExtractedClaim]:
        """Extract claims strictly of type: parameter count, context length, benchmark score, price."""
        norm_text = normalize_text(text)
        claims: list[ExtractedClaim] = []

        # 1. Parameter count regex
        param_patterns = [
            r"\b(\d+(?:\.\d+)?)\s*(?:b|billion)\b(?:\s*parameters?|\s*params?)?",
            r"\b(\d+(?:\.\d+)?)\s*(?:t|trillion)\b(?:\s*parameters?|\s*params?)?",
            r"(\d+(?:\.\d+)?)\s*(?:亿|万亿)\s*(?:参数)?",
        ]
        for pat in param_patterns:
            for m in re.finditer(pat, norm_text, re.IGNORECASE):
                claims.append(
                    ExtractedClaim(
                        claim_text=m.group(0).strip(),
                        claim_type=ClaimType.PARAMETER_COUNT,
                        normalized_value=m.group(0).strip(),
                        start_pos=m.start(),
                        end_pos=m.end(),
                    )
                )

        # 2. Context length regex
        context_patterns = [
            r"\b(\d+(?:\.\d+)?)\s*k\s*(?:context|tokens?|window)\b",
            r"\b(?:context\s*(?:window|length)?\s*(?:of\s*)?)(\d+(?:\.\d+)?)\s*k\b",
            r"\b(131072|65536|32768|262144|1048576)\b",
            r"\b(\d+(?:\.\d+)?)\s*m\s*(?:context|tokens?|window)\b",
            r"(\d+(?:\.\d+)?)\s*(?:k|万)\s*(?:上下文|窗口|token)",
        ]
        for pat in context_patterns:
            for m in re.finditer(pat, norm_text, re.IGNORECASE):
                claims.append(
                    ExtractedClaim(
                        claim_text=m.group(0).strip(),
                        claim_type=ClaimType.CONTEXT_LENGTH,
                        normalized_value=m.group(0).strip(),
                        start_pos=m.start(),
                        end_pos=m.end(),
                    )
                )

        # 3. Benchmark score regex
        bench_patterns = [
            r"\b(\d+(?:\.\d+)?)\s*%\s*(?:on\s+[\w-]+)?",
            r"\b(\d+(?:\.\d+)?)\s*percent\b",
            r"\b(\d+(?:\.\d+)?)\s*x\s*(?:speedup|faster|throughput)?\b",
            r"\b(\d+(?:\.\d+)?)-fold\b",
            r"\b(?:score\s*of\s*)?(\d+(?:\.\d+)?)\s*on\s+([A-Za-z0-9_-]+)",
        ]
        for pat in bench_patterns:
            for m in re.finditer(pat, norm_text, re.IGNORECASE):
                claims.append(
                    ExtractedClaim(
                        claim_text=m.group(0).strip(),
                        claim_type=ClaimType.BENCHMARK_SCORE,
                        normalized_value=m.group(0).strip(),
                        start_pos=m.start(),
                        end_pos=m.end(),
                    )
                )

        # 4. Price regex
        price_patterns = [
            r"\$\s*(\d+(?:\.\d+)?)\s*(?:bn|billion|m|million|k)?(?:\s*(?:\/|per)\s*(?:1m|million|token|tokens))?",
            r"(\d+(?:\.\d+)?)\s*(?:bn|billion|m|million|k)?\s*(?:usd|dollars?)(?:\s*(?:\/|per)\s*(?:1m|million|token|tokens))?",
            r"(?:¥|rmb|cny)\s*(\d+(?:\.\d+)?)\s*(?:亿|万)?|(\d+(?:\.\d+)?)\s*(?:亿|万)?\s*(?:元|美元)(?:\s*(?:\/|每)\s*(?:百万|100万|token|tokens))?",
        ]
        for pat in price_patterns:
            for m in re.finditer(pat, norm_text, re.IGNORECASE):
                claims.append(
                    ExtractedClaim(
                        claim_text=m.group(0).strip(),
                        claim_type=ClaimType.PRICE,
                        normalized_value=m.group(0).strip(),
                        start_pos=m.start(),
                        end_pos=m.end(),
                    )
                )

        # Deduplicate overlapping spans
        claims.sort(key=lambda c: c.start_pos)
        unique_claims: list[ExtractedClaim] = []
        last_end = -1
        for c in claims:
            if c.start_pos >= last_end:
                unique_claims.append(c)
                last_end = c.end_pos

        return unique_claims

    def verify_claim(
        self,
        claim_text: str,
        entry: Entry,
        claim_type: ClaimType | str = "numeric",
    ) -> VerifiedClaim:
        """Verify an isolated numeric or benchmark claim against source entry text."""
        corpus = extract_grounding_corpus(entry)
        corpus_norm = normalize_text(corpus)

        is_present, matched = self.check_substring_presence(
            claim_text, corpus_norm, claim_type=claim_type
        )
        return VerifiedClaim(
            claim_text=claim_text,
            claim_type=str(claim_type),
            is_verified=is_present,
            matched_term=matched,
            original_value=claim_text,
        )

    def clean_summary_claims(
        self, entry: Entry, summary: str
    ) -> tuple[str, VerificationResult]:
        """Extract and verify all numeric claims in a prose summary.

        If a claim is ungrounded:
        - Drops the ungrounded claim from the text.
        - Preserves the surrounding prose summary grammatically.
        - Logs the dropped claim.
        - Attaches epistemic disclaimer (never claim 0% hallucination).
        """
        if not summary:
            return "", VerificationResult()

        claims = self.extract_claims(summary)
        if not claims:
            return summary, VerificationResult()

        corpus = extract_grounding_corpus(entry)
        corpus_norm = normalize_text(corpus)

        result = VerificationResult()
        cleaned_summary = summary

        for claim in claims:
            # Check presence
            is_ok, matched = self.check_substring_presence(
                claim.claim_text, corpus_norm, claim_type=claim.claim_type
            )
            if is_ok:
                result.verified_claims.append(
                    VerifiedClaim(
                        claim_text=claim.claim_text,
                        claim_type=claim.claim_type.value,
                        is_verified=True,
                        matched_term=matched,
                        original_value=claim.claim_text,
                    )
                )
            else:
                result.dropped_claims.append(
                    VerifiedClaim(
                        claim_text=claim.claim_text,
                        claim_type=claim.claim_type.value,
                        is_verified=False,
                        matched_term=None,
                        original_value=claim.claim_text,
                    )
                )
                logger.warning(
                    f"Dropped ungrounded {claim.claim_type.value} claim: '{claim.claim_text}' "
                    f"(entry {entry.id}: {entry.title[:40]})"
                )
                # Drop clause from prose summary
                cleaned_summary = self._drop_clause_from_text(
                    cleaned_summary, claim.claim_text
                )

        if result.total_claims > 0:
            result.grounding_score = len(result.verified_claims) / result.total_claims

        return cleaned_summary, result

    def _drop_clause_from_text(self, text: str, target: str) -> str:
        """Remove a target ungrounded claim phrase while preserving grammatical prose."""
        escaped = re.escape(target)
        patterns = [
            # Trailing clause: ", achieving 99.8% on GPQA."
            r",\s*(?:achieving|scoring|with|reaching|priced at)?\s*"
            + escaped
            + r"\s*(?=[,\.\;]|$)",
            # Middle clause: "with 99.8% on GPQA, "
            r"(?:and\s+)?(?:achieving|scoring|with|reaching|priced at)?\s*"
            + escaped
            + r"\s*,\s*",
            # Direct target
            escaped,
        ]
        cleaned = text
        for p in patterns:
            if re.search(p, cleaned, re.IGNORECASE):
                cleaned = re.sub(p, "", cleaned, count=1, flags=re.IGNORECASE)
                break

        # Tidy up double punctuation and trailing commas
        cleaned = re.sub(r"\s*,\s*,", ",", cleaned)
        cleaned = re.sub(r",\s*\.", ".", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned

    def filter_benchmark_metrics(
        self, entry: Entry, metrics: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], VerificationResult]:
        """Filter candidate benchmark metrics, dropping ungrounded/hallucinated items.

        Policy:
        - If benchmark name or score is grounded in source text, retain it.
        - If both benchmark and score are absent, DROP it.
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
                bench_name, corpus_norm, claim_type=ClaimType.BENCHMARK_NAME
            )

            # Check composite sub-benchmarks (e.g. "AIME 2024 / MATH-500")
            if not bench_ok and "/" in bench_name:
                for sub in bench_name.split("/"):
                    sub_ok, sub_match = self.check_substring_presence(
                        sub.strip(), corpus_norm, claim_type=ClaimType.BENCHMARK_NAME
                    )
                    if sub_ok:
                        bench_ok = True
                        bench_match = sub_match
                        break

            # Check numeric score presence
            score_ok, score_match = False, None
            if score_val:
                score_ok, score_match = self.check_substring_presence(
                    score_val, corpus_norm, claim_type=ClaimType.BENCHMARK_SCORE
                )
                if not score_ok:
                    # Extract primary numeric component
                    num_match = re.search(
                        r"\d+(?:\.\d+)?(?:\s*%|\s*x|\s*b|\s*tflops)?",
                        score_val,
                        re.IGNORECASE,
                    )
                    if num_match:
                        score_ok, score_match = self.check_substring_presence(
                            num_match.group(0),
                            corpus_norm,
                            claim_type=ClaimType.BENCHMARK_SCORE,
                        )

            # A claim is verified if either the benchmark is cited or its numeric score is grounded
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
                    f"Dropped ungrounded benchmark claim: '{bench_name}: {score_val}' "
                    f"(entry: {entry.title[:40]})"
                )

        if result.total_claims > 0:
            result.grounding_score = len(result.verified_claims) / result.total_claims

        return verified_items, result


substring_verifier = ScopedSubstringVerifier()
