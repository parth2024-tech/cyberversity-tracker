"""
Unit tests for Pluggable Triage ScoringPipeline.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.triage_scoring_pipeline import (
    ScoringPipeline,
    SourceAuthoritySignal,
    TopicRelevanceSignal,
    VelocitySignal,
    scoring_pipeline,
)
from ai_security_monitor.domain.entities import Analysis, Category, Entry


def test_source_authority_signal():
    signal = SourceAuthoritySignal()

    entry_arxiv = Entry(
        source_id=uuid4(),
        title="Scaling Laws for Neural Language Models",
        url="https://arxiv.org/abs/2001.08361",
        content_hash="h_arxiv",
        published_at=datetime.now(UTC),
        category=Category.AI_RESEARCH,
    )
    score_arxiv, _ = signal.evaluate(entry_arxiv)
    assert score_arxiv == 0.95

    entry_gh = Entry(
        source_id=uuid4(),
        title="vLLM: Easy, fast, and cheap LLM serving",
        url="https://github.com/vllm-project/vllm",
        content_hash="h_gh",
        published_at=datetime.now(UTC),
        category=Category.GITHUB_TRENDING,
    )
    score_gh, _ = signal.evaluate(entry_gh)
    assert score_gh == 0.85


def test_topic_relevance_signal():
    signal = TopicRelevanceSignal()

    entry_reasoning = Entry(
        source_id=uuid4(),
        title="DeepSeek-R1: Incentivizing Reasoning Capability via RL",
        url="https://example.com/r1",
        content_hash="h_r1",
        published_at=datetime.now(UTC),
        category=Category.AI_RESEARCH,
    )
    score, reason = signal.evaluate(entry_reasoning)
    assert score == 1.0
    assert "Reasoning" in reason

    entry_vllm = Entry(
        source_id=uuid4(),
        title="vLLM high throughput inference engine v0.6",
        url="https://example.com/vllm",
        content_hash="h_vllm",
        published_at=datetime.now(UTC),
        category=Category.CYBER_TOOLS,
    )
    score_vllm, reason_vllm = signal.evaluate(entry_vllm)
    assert score_vllm >= 0.85
    assert "Inference" in reason_vllm


def test_scoring_pipeline_p0_assignment_and_explainability():
    pipeline = ScoringPipeline()

    entry_frontier = Entry(
        source_id=uuid4(),
        title="DeepSeek-R1 Open Weights and Test-Time Compute Technical Report",
        url="https://arxiv.org/abs/2501.12948",
        content_hash="h_p0",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        analysis=Analysis(
            entry_id=uuid4(),
            attack_vector="Reasoning Model",
            risk_assessment="Frontier Benchmark",
            mitigation="Open Deployment",
            threat_velocity=90,
            severity_index=85,
        ),
    )

    res = pipeline.score(entry_frontier)
    assert res.priority == 0  # Must be P0
    assert res.composite_score >= 75.0
    assert "P0" in res.explanation
    assert "breakdown" in dir(res)
    assert res.breakdown["source_authority"] == 0.95
    assert res.breakdown["topic_relevance"] == 1.0


def test_scoring_pipeline_p2_for_generic_discussion():
    pipeline = ScoringPipeline()

    entry_generic = Entry(
        source_id=uuid4(),
        title="Thoughts on how computers have evolved over time",
        url="https://personalblog.xyz/post",
        content_hash="h_p2",
        published_at=datetime.now(UTC),
        category=Category.AI_TECH,
        analysis=Analysis(
            entry_id=uuid4(),
            attack_vector="N/A",
            risk_assessment="N/A",
            mitigation="N/A",
            threat_velocity=30,
            severity_index=20,
        ),
    )

    res = pipeline.score(entry_generic)
    assert res.priority == 2  # P2
    assert res.composite_score < 50.0
    assert "P2" in res.explanation
