"""
Unit tests for DeduplicationService and Story aggregate.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.deduplication_service import (
    DeduplicationService,
    canonicalize_url,
    compute_title_similarity,
    normalize_title,
)
from ai_security_monitor.domain.entities import Category, Entry, Story


def test_canonicalize_url_strips_tracking_params():
    url = "https://example.com/article?utm_source=twitter&utm_medium=social&ref=ai_radar&id=123"
    canonical = canonicalize_url(url)
    assert "utm_source" not in canonical
    assert "utm_medium" not in canonical
    assert "ref=" not in canonical
    assert "id=123" in canonical


def test_canonicalize_url_normalizes_github_and_arxiv():
    gh_release = "https://github.com/vllm-project/vllm/releases/tag/v0.6.0"
    assert canonicalize_url(gh_release) == "https://github.com/vllm-project/vllm"

    arxiv_pdf = "https://arxiv.org/pdf/2401.12345.pdf"
    assert canonicalize_url(arxiv_pdf) == "https://arxiv.org/abs/2401.12345"


def test_title_normalization_and_similarity():
    title_1 = "[R] DeepSeek-V3 Technical Report Released"
    title_2 = "Show HN: DeepSeek-V3 technical report & weights"

    norm_1 = normalize_title(title_1)
    norm_2 = normalize_title(title_2)

    assert "deepseek-v3" in norm_1
    assert "deepseek-v3" in norm_2

    similarity = compute_title_similarity(title_1, title_2)
    assert similarity >= 0.30  # High token overlap


def test_deduplication_service_story_clustering():
    dedup = DeduplicationService(similarity_threshold=0.50)

    # 1. First entry from arXiv
    entry_arxiv = Entry(
        source_id=uuid4(),
        title="DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via RL",
        url="https://arxiv.org/abs/2501.12948",
        content_hash="hash_arxiv_001",
        published_at=datetime.now(UTC),
        category=Category.AI_RESEARCH,
    )

    proc_1, story_1, is_new_1 = dedup.process_candidate(entry_arxiv, source_name="arXiv AI")
    assert is_new_1 is True
    assert story_1.source_count == 1
    assert story_1.confidence_score == 0.60
    assert story_1.canonical_url == "https://arxiv.org/abs/2501.12948"
    assert proc_1.story_id == story_1.id

    # 2. Corroborating entry from Hacker News (same canonical url or matching title)
    entry_hn = Entry(
        source_id=uuid4(),
        title="DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning",
        url="https://arxiv.org/pdf/2501.12948.pdf?utm_source=hackernews",
        content_hash="hash_hn_002",
        published_at=datetime.now(UTC),
        category=Category.AI_TECH,
    )

    proc_2, story_2, is_new_2 = dedup.process_candidate(entry_hn, source_name="Hacker News")
    assert is_new_2 is False
    assert story_2.id == story_1.id
    assert story_2.source_count == 2
    assert story_2.confidence_score == 0.85
    assert "Hacker News" in story_2.sources
    assert proc_2.story_id == story_1.id


def test_story_confidence_scaling():
    story = Story(
        title="Test Foundation Model Release",
        canonical_url="https://example.com/model",
        fingerprint="dummy_fp",
        category=Category.AI_MODELS,
    )
    assert story.confidence_score == 0.60

    e1 = Entry(
        source_id=uuid4(),
        title="Test 1",
        url="https://example.com/1",
        content_hash="h1",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )
    e2 = Entry(
        source_id=uuid4(),
        title="Test 2",
        url="https://example.com/2",
        content_hash="h2",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )

    story.add_entry(e1, source_name="Source A")
    story.add_entry(e2, source_name="Source B")
    assert story.source_count == 2
    assert story.confidence_score == 0.85

    e3 = Entry(
        source_id=uuid4(),
        title="Test 3",
        url="https://example.com/3",
        content_hash="h3",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )
    story.add_entry(e3, source_name="Source C")
    assert story.source_count == 3
    assert story.confidence_score >= 0.90
