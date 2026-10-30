"""
AI Newsworthiness Scoring Service (Feature 4).
Replaces legacy security-derived threat_velocity with an AI-native newsworthiness metric (0-100).

Components:
1. source_weight (0-25): From tier in sources.yaml (T1 lab/official=25, T1.5 dev org=18, T2 media=10, T3=5)
2. corroboration (0-25): Independent corroborating sources in the same cluster (1=0, 2=12, 3=18, 4+=25)
3. recency (0-15): 24h half-life temporal exponential decay
4. entity_importance (0-20): Frontier lab/model match (20), tooling/inference runtime match (15), emerging (10), generic (5)
5. content_signal (0-15): Release verbs (+6), technical benchmarks/metrics (+5), artifact/code/paper links (+4)

Calibration:
Provides empirical lane percentile calculations (P25, P50, P75, P90, P95) for dynamic gating.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry, Source

logger = get_logger(__name__)


@dataclass
class NewsworthinessBreakdown:
    """Individual modular sub-components of the AI newsworthiness score."""

    source_weight: float = 0.0  # 0-25
    corroboration: float = 0.0  # 0-25
    recency: float = 0.0  # 0-15
    entity_importance: float = 0.0  # 0-20
    content_signal: float = 0.0  # 0-15
    total_score: float = 0.0  # 0-100

    def to_dict(self) -> dict[str, float]:
        return {
            "source_weight": round(self.source_weight, 2),
            "corroboration": round(self.corroboration, 2),
            "recency": round(self.recency, 2),
            "entity_importance": round(self.entity_importance, 2),
            "content_signal": round(self.content_signal, 2),
            "total_score": round(self.total_score, 2),
        }


class NewsworthinessScoringService:
    """Computes transparent, calibrated AI newsworthiness scores."""

    FRONTIER_ENTITIES: ClassVar[set[str]] = {
        "deepseek",
        "qwen",
        "claude",
        "anthropic",
        "llama",
        "meta",
        "openai",
        "gpt-4o",
        "o1",
        "o3",
        "gemini",
        "deepmind",
        "zhipu",
        "glm",
        "chatglm",
        "kimi",
        "moonshot",
        "mistral",
        "codestral",
        "01.ai",
        "yi",
        "internlm",
        "stepfun",
        "step-2",
        "minimax",
        "baichuan",
        "phi-4",
    }

    INFRA_ENTITIES: ClassVar[set[str]] = {
        "vllm",
        "sglang",
        "llama.cpp",
        "ollama",
        "huggingface",
        "pytorch",
        "triton",
        "megatron",
        "tensorrt",
        "flashattention",
        "deepspeed",
        "unsloth",
        "axolotl",
        "bitsandbytes",
    }

    RELEASE_VERBS: ClassVar[list[str]] = [
        "release",
        "released",
        "releases",
        "open-source",
        "open-sourced",
        "open-sources",
        "launch",
        "launches",
        "launched",
        "unveil",
        "unveils",
        "unveiled",
        "announce",
        "announces",
        "announced",
        "debut",
        "debuts",
        "weights available",
        "开源",
        "发布",
        "推出",
        "上线",
        "首发",
    ]

    BENCHMARK_TERMS: ClassVar[list[str]] = [
        "mmlu",
        "gsm8k",
        "humaneval",
        "swe-bench",
        "gpqa",
        "math",
        "arena-hard",
        "livebench",
        "tokens/s",
        "token/s",
        "latency",
        "throughput",
        "context window",
        "benchmark",
        "score",
        "accuracy",
        "bleu",
        "rouge",
        "%",
    ]

    ARTIFACT_INDICATORS: ClassVar[list[str]] = [
        "github.com",
        "huggingface.co",
        "hf.co",
        "arxiv.org",
        "modelscope.cn",
        "paperswithcode.com",
        "git clone",
        "pip install",
        "weights",
        "checkpoint",
    ]

    @classmethod
    def compute_source_weight(cls, tier: float) -> float:
        """Score source credibility (0-25) based on institutional hierarchy."""
        if tier <= 1.0:
            return 25.0
        elif tier <= 1.5:
            return 18.0
        elif tier <= 2.0:
            return 10.0
        return 5.0

    @classmethod
    def compute_corroboration_score(cls, n_sources: int) -> float:
        """Score multi-source corroboration (0-25) across independent reporting sources."""
        if n_sources <= 1:
            return 0.0
        elif n_sources == 2:
            return 12.0
        elif n_sources == 3:
            return 18.0
        return 25.0

    @classmethod
    def compute_recency_score(
        cls,
        published_at: datetime,
        ref_time: datetime | None = None,
        half_life_hours: float = 24.0,
    ) -> float:
        """Compute half-life decay score (0-15) with a 24-hour half-life."""
        now = ref_time or datetime.now(UTC)
        ts = (
            published_at
            if published_at.tzinfo is not None
            else published_at.replace(tzinfo=UTC)
        )
        ref = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        delta_hours = max(0.0, (ref - ts).total_seconds() / 3600.0)
        decay = 0.5 ** (delta_hours / half_life_hours)
        return round(15.0 * decay, 2)

    @classmethod
    def compute_entity_importance(cls, text: str) -> float:
        """Score entity significance (0-20) matching frontier labs and developer infrastructure."""
        lower = text.lower()
        for e in cls.FRONTIER_ENTITIES:
            pattern = rf"(?<![a-zA-Z0-9]){re.escape(e)}(?![a-zA-Z0-9])"
            if re.search(pattern, lower):
                return 20.0

        for e in cls.INFRA_ENTITIES:
            pattern = rf"(?<![a-zA-Z0-9]){re.escape(e)}(?![a-zA-Z0-9])"
            if re.search(pattern, lower):
                return 15.0

        if any(
            w in lower
            for w in [
                "model",
                "weights",
                "checkpoint",
                "paper",
                "architecture",
                "agent",
            ]
        ):
            return 10.0

        return 5.0

    @classmethod
    def compute_content_signal(cls, text: str, url: str = "") -> float:
        """Score tangible content artifacts (0-15): release verbs (+6), benchmarks (+5), code/paper links (+4)."""
        combined = f"{text} {url}".lower()
        signal = 0.0

        if any(v in combined for v in cls.RELEASE_VERBS):
            signal += 6.0
        if any(b in combined for b in cls.BENCHMARK_TERMS):
            signal += 5.0
        if any(a in combined for a in cls.ARTIFACT_INDICATORS):
            signal += 4.0

        return min(15.0, round(signal, 1))

    @classmethod
    def score_entry(
        cls,
        entry: Entry,
        source: Source | None = None,
        corroboration_count: int = 1,
        ref_time: datetime | None = None,
    ) -> tuple[float, dict[str, float]]:
        """
        Compute total AI Newsworthiness Score (0-100) and its granular breakdown.

        Returns:
            tuple[float, dict[str, float]]: (total_score, components_dict)
        """
        # 1. Source Weight (0-25)
        tier = getattr(source, "tier", 2.0) if source else 2.0
        if "tier" in entry.metadata:
            try:
                tier = float(entry.metadata["tier"])
            except (ValueError, TypeError):
                pass
        s_weight = cls.compute_source_weight(tier)

        # 2. Corroboration (0-25)
        n_corr = max(
            corroboration_count,
            int(entry.metadata.get("source_count", 1) or 1),
        )
        s_corr = cls.compute_corroboration_score(n_corr)

        # 3. Recency (0-15)
        pub_ts = entry.published_at or entry.created_at or datetime.now(UTC)
        s_recency = cls.compute_recency_score(pub_ts, ref_time=ref_time)

        # 4. Entity Importance (0-20)
        full_text = f"{entry.title} {entry.summary}".strip()
        s_entity = cls.compute_entity_importance(full_text)

        # 5. Content Signal (0-15)
        s_content = cls.compute_content_signal(full_text, url=entry.url)

        total = round(s_weight + s_corr + s_recency + s_entity + s_content, 2)
        total = max(0.0, min(100.0, total))

        breakdown = NewsworthinessBreakdown(
            source_weight=s_weight,
            corroboration=s_corr,
            recency=s_recency,
            entity_importance=s_entity,
            content_signal=s_content,
            total_score=total,
        )

        return total, breakdown.to_dict()

    @classmethod
    def calculate_percentiles(
        cls,
        scores: list[float],
        percentiles: list[float] | None = None,
    ) -> dict[str, float]:
        """Compute statistical percentiles from a distribution of newsworthiness scores."""
        if not scores:
            return {"p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0, "p95": 0.0}

        pct_list = percentiles or [25.0, 50.0, 75.0, 90.0, 95.0]
        sorted_scores = sorted(scores)
        n = len(sorted_scores)
        results: dict[str, float] = {}

        for p in pct_list:
            key = f"p{int(p)}"
            if n == 1:
                results[key] = round(sorted_scores[0], 2)
                continue
            idx = (p / 100.0) * (n - 1)
            lower_idx = int(math.floor(idx))
            upper_idx = int(math.ceil(idx))
            fraction = idx - lower_idx
            interpolated = (
                sorted_scores[lower_idx]
                + (sorted_scores[upper_idx] - sorted_scores[lower_idx]) * fraction
            )
            results[key] = round(interpolated, 2)

        return results


newsworthiness_scoring_service = NewsworthinessScoringService()
