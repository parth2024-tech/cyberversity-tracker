"""
Pluggable Triage Scoring Pipeline.
Calculates transparent, composable, and explainable multi-signal priority scores
(P0, P1, P2) for all candidate intelligence entries.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ai_security_monitor.application.services.deduplication_service import (
    deduplication_service,
)
from ai_security_monitor.application.services.vault_feedback_service import (
    vault_feedback_service,
)
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ScoringResult:
    """Detailed output of the scoring pipeline with explainability breakdown."""

    priority: int  # 0 = P0 (Frontier/Urgent), 1 = P1 (Trending/High), 2 = P2 (Standard)
    composite_score: float  # 0.0 to 100.0
    breakdown: dict[str, float]  # Signal name -> normalized score (0.0 to 1.0)
    weighted_scores: dict[str, float]  # Signal name -> weighted contribution
    explanation: str  # Human-readable rationale of why this priority was assigned


class ScoringSignal(ABC):
    """Abstract base class for a composable scoring signal."""

    name: str

    @abstractmethod
    def evaluate(self, entry: Entry, context: dict | None = None) -> tuple[float, str]:
        """Evaluate signal on entry.

        Returns:
            tuple[float, str]: (normalized_score 0.0-1.0, short_reason)
        """
        pass


class SourceAuthoritySignal(ScoringSignal):
    """Scores the epistemic authority and rigor of the source."""

    name = "source_authority"

    def evaluate(self, entry: Entry, context: dict | None = None) -> tuple[float, str]:
        source_type = ""
        if context and "source_type" in context:
            source_type = str(context["source_type"]).lower()
        elif entry.metadata and "source_type" in entry.metadata:
            source_type = str(entry.metadata["source_type"]).lower()

        url = (entry.url or "").lower()

        if "arxiv.org" in url or source_type == "arxiv":
            return 0.95, "Primary peer-reviewed academic preprint (arXiv)"
        if "github.com" in url or source_type == "github_trending":
            return 0.85, "Direct open-source repository release (GitHub)"
        if "news.ycombinator.com" in url or source_type == "hackernews":
            return 0.75, "High-velocity developer consensus (Hacker News)"
        if any(
            host in url
            for host in (
                "anthropic.com",
                "openai.com",
                "deepseek.com",
                "mistral.ai",
                "huggingface.co",
            )
        ):
            return 0.95, "Official frontier AI lab release"

        return 0.50, "General technology publication"


class VelocitySignal(ScoringSignal):
    """Scores the momentum and velocity of the entry."""

    name = "velocity"

    def evaluate(self, entry: Entry, context: dict | None = None) -> tuple[float, str]:
        vel = 50
        if entry.analysis and entry.analysis.threat_velocity is not None:
            vel = entry.analysis.threat_velocity
        elif entry.metadata and "velocity" in entry.metadata:
            try:
                vel = int(entry.metadata["velocity"])
            except (ValueError, TypeError):
                vel = 50

        normalized = max(0.0, min(1.0, vel / 100.0))
        reason = f"Measured momentum velocity ({vel}/100)"
        return normalized, reason


class TopicRelevanceSignal(ScoringSignal):
    """Scores relevance to frontier models, reasoning architectures, and inference infrastructure."""

    name = "topic_relevance"

    # Priority keyword patterns
    REASONING_PATTERNS = re.compile(
        r"\b(reasoning|deepseek-r1|r1|o1|o3|chain-of-thought|test-time compute|inference-time scaling|extended thinking)\b",
        re.IGNORECASE,
    )
    FRONTIER_MODELS_PATTERNS = re.compile(
        r"\b(deepseek|qwen|claude|gemini|llama-3|llama3|mistral|open weights|weights released|moe|mixture-of-experts)\b",
        re.IGNORECASE,
    )
    INFERENCE_INFRA_PATTERNS = re.compile(
        r"\b(vllm|sglang|llama\.cpp|ollama|tensorrt-llm|triton|kernel|serving|inference engine)\b",
        re.IGNORECASE,
    )
    HARDWARE_PATTERNS = re.compile(
        r"\b(blackwell|b200|gb200|h100|h200|mi300|npu|tpu|accelerator)\b",
        re.IGNORECASE,
    )

    def evaluate(self, entry: Entry, context: dict | None = None) -> tuple[float, str]:
        text = f"{entry.title} {entry.summary}".lower()
        cat_val = (
            entry.category.value
            if hasattr(entry.category, "value")
            else str(entry.category)
        )

        if self.REASONING_PATTERNS.search(text):
            return 1.0, "Seminal Reasoning Architecture & Test-Time Compute"
        if self.FRONTIER_MODELS_PATTERNS.search(text) or cat_val == "ai_models":
            return 0.90, "Frontier Foundation Model Release / Open Weights"
        if self.INFERENCE_INFRA_PATTERNS.search(text):
            return 0.85, "Critical Inference Runtime & Serving Infrastructure"
        if self.HARDWARE_PATTERNS.search(text):
            return 0.80, "AI Hardware & Next-Gen Accelerators"
        if cat_val in ("github_trending", "ai_research"):
            return 0.70, "Trending AI Developer Ecosystem / Research"

        return 0.40, "General AI Ecosystem Discussion"


class StoryCorroborationSignal(ScoringSignal):
    """Scores cross-source confirmation from multiple independent sources."""

    name = "corroboration"

    def evaluate(self, entry: Entry, context: dict | None = None) -> tuple[float, str]:
        story_id = entry.story_id
        if not story_id and context and "story" in context:
            story = context["story"]
        elif story_id:
            story = deduplication_service.get_story(story_id)
        else:
            story = None

        if not story:
            return 0.50, "Single-source observation"

        sources_count = story.source_count
        if sources_count >= 3:
            return (
                1.0,
                f"Multi-source confirmed consensus ({sources_count} sources: {', '.join(story.sources[:3])})",
            )
        if sources_count == 2:
            return 0.80, f"Cross-source corroborated ({', '.join(story.sources)})"

        return 0.50, "Single source reporting"


class VaultAffinitySignal(ScoringSignal):
    """Scores alignment with topics, models, and frameworks the user has pinned to the Vault."""

    name = "vault_affinity"

    def evaluate(self, entry: Entry, context: dict | None = None) -> tuple[float, str]:
        affinity = vault_feedback_service.calculate_affinity(entry)
        if affinity >= 0.70:
            return (
                affinity,
                f"High alignment with user Vault preferences ({affinity:.2f})",
            )
        if affinity >= 0.30:
            return (
                affinity,
                f"Moderate alignment with user Vault preferences ({affinity:.2f})",
            )
        return affinity, "Standard preference baseline"


class ScoringPipeline:
    """Composable multi-signal scoring pipeline for autonomous triage."""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        p0_threshold: float = 75.0,
        p1_threshold: float = 48.0,
    ):
        self.signals: list[ScoringSignal] = [
            TopicRelevanceSignal(),
            SourceAuthoritySignal(),
            VelocitySignal(),
            StoryCorroborationSignal(),
            VaultAffinitySignal(),
        ]
        # Default balanced weights summing to 1.0
        self.weights = weights or {
            "topic_relevance": 0.35,
            "source_authority": 0.25,
            "velocity": 0.20,
            "corroboration": 0.10,
            "vault_affinity": 0.10,
        }
        self.p0_threshold = p0_threshold
        self.p1_threshold = p1_threshold

    def score(self, entry: Entry, context: dict | None = None) -> ScoringResult:
        """Run all signals, calculate composite weighted score, and formulate explainability."""
        breakdown: dict[str, float] = {}
        weighted_scores: dict[str, float] = {}
        reasons: list[str] = []

        total_weight = sum(self.weights.values()) or 1.0
        composite = 0.0

        for signal in self.signals:
            weight = self.weights.get(signal.name, 0.0)
            score, reason = signal.evaluate(entry, context)
            breakdown[signal.name] = round(score, 3)
            contrib = (score * weight) / total_weight * 100.0
            weighted_scores[signal.name] = round(contrib, 2)
            composite += contrib
            if score >= 0.70 and weight > 0:
                reasons.append(reason)

        composite = round(max(0.0, min(100.0, composite)), 1)

        # Priority determination: domain hierarchy with composite threshold elevation
        cat_val = (
            entry.category.value
            if hasattr(entry.category, "value")
            else str(entry.category)
        )
        title_lower = (entry.title or "").lower()
        if cat_val == "ai_models" or any(
            k in title_lower
            for k in (
                "deepseek",
                "r1",
                "frontier",
                "qwen",
                "weights release",
                "open weights",
            )
        ):
            priority = 0
            tier = "P0 (Frontier/Urgent)"
        elif cat_val == "ai_research" and any(
            k in title_lower
            for k in (
                "reasoning",
                "breakthrough",
                "benchmark",
                "sota",
                "test-time",
            )
        ):
            priority = 0
            tier = "P0 (Frontier/Urgent)"
        elif cat_val in ("github_trending", "cyber_tools") or any(
            k in title_lower
            for k in ("vllm", "sglang", "llama.cpp", "ollama", "runtime", "engine")
        ):
            priority = 1
            tier = "P1 (Trending/High)"
        elif composite >= self.p0_threshold:
            priority = 0
            tier = "P0 (Frontier/Urgent)"
        elif composite >= self.p1_threshold:
            priority = 1
            tier = "P1 (Trending/High)"
        else:
            priority = 2
            tier = "P2 (Standard)"

        # Construct concise human-readable explanation
        key_reasons = (
            " + ".join(reasons[:2]) if reasons else "Standard ecosystem telemetry"
        )
        explanation = f"{tier} [Score: {composite}]: {key_reasons}"

        return ScoringResult(
            priority=priority,
            composite_score=composite,
            breakdown=breakdown,
            weighted_scores=weighted_scores,
            explanation=explanation,
        )


# Global singleton scoring pipeline
scoring_pipeline = ScoringPipeline()
