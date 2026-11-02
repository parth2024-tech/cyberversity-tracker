"""
Unit tests for Semantic Vector Memory & Concept Deduplication (Pillar 1).
Verifies FastEmbed embedding generation, sqlite-vec in-process virtual table,
and cross-platform story deduplication across disparate sources.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.deduplication_service import (
    DeduplicationService,
)
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.infrastructure.analyzers.embedding_service import (
    EmbeddingService,
    embedding_service,
)


def test_embedding_service_dimensions_and_normalization():
    """EmbeddingService generates unit-normalized vectors with expected dimension."""
    text = "DeepSeek-R1 reasoning models and test-time compute scaling"
    vec = embedding_service.embed_text(text)

    assert len(vec) == 384
    norm = math.sqrt(sum(x * x for x in vec))
    assert pytest.approx(norm, rel=1e-3) == 1.0


def test_embedding_service_batch_and_empty():
    """EmbeddingService handles batch inputs and empty strings gracefully."""
    empty_vec = embedding_service.embed_text("")
    assert len(empty_vec) == 384
    assert all(x == 0.0 for x in empty_vec)

    batch = embedding_service.embed_batch(
        [
            "vLLM inference engine with PagedAttention",
            "SGLang runtime optimization for fast batching",
        ]
    )
    assert len(batch) == 2
    assert len(batch[0]) == 384
    assert len(batch[1]) == 384


def test_embedding_service_cosine_similarity():
    """Cosine similarity handles identical, similar, and orthogonal vectors."""
    # Identical
    vec_a = embedding_service.embed_text("Frontier reasoning foundation models")
    sim_self = EmbeddingService.cosine_similarity(vec_a, vec_a)
    assert pytest.approx(sim_self, rel=1e-3) == 1.0

    # Similar
    vec_b = embedding_service.embed_text("Frontier reasoning foundation architecture")
    sim_similar = EmbeddingService.cosine_similarity(vec_a, vec_b)
    assert sim_similar > 0.70

    # Mismatched dimensions
    assert EmbeddingService.cosine_similarity([1.0, 2.0], [1.0]) == 0.0
    assert EmbeddingService.cosine_similarity([], []) == 0.0


def test_semantic_deduplication_cross_platform_clustering():
    """Cross-platform concept deduplication merges disparate titles covering the same story."""
    threshold = 0.50 if embedding_service.is_fallback else 0.75
    dedup = DeduplicationService(semantic_threshold=threshold)

    # Entry 1: arXiv primary paper
    entry_arxiv = Entry(
        source_id=uuid4(),
        title="DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning",
        url="https://arxiv.org/abs/2501.12948",
        summary="We introduce DeepSeek-R1-Zero and DeepSeek-R1, reasoning foundation models.",
        content_hash="hash_arxiv_r1",
        published_at=datetime.now(UTC),
        category=Category.AI_RESEARCH,
    )
    processed_1, story_1, is_new_1 = dedup.process_candidate(
        entry_arxiv, source_name="arXiv"
    )
    assert is_new_1 is True
    assert story_1.source_count == 1

    # Entry 2: Hacker News discussion with completely different URL and phrasing
    entry_hn = Entry(
        source_id=uuid4(),
        title="Show HN: DeepSeek-R1 reasoning models and open weights release",
        url="https://news.ycombinator.com/item?id=42700000",
        summary="Discussion of the new DeepSeek-R1 reasoning models and weights.",
        content_hash="hash_hn_r1",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )

    # Semantic match check
    semantic_match = dedup.find_semantic_duplicate(entry_hn, threshold=threshold)
    assert semantic_match is not None
    assert semantic_match.id == story_1.id

    # Process through candidate pipeline
    processed_2, story_2, is_new_2 = dedup.process_candidate(
        entry_hn, source_name="Hacker News"
    )
    assert is_new_2 is False  # Merged!
    assert story_2.id == story_1.id
    assert story_2.source_count == 2
    assert "Hacker News" in story_2.sources


def test_sqlite_vec_virtual_table_integration():
    """Verify in-process sqlite-vec C extension loads and runs KNN vector match."""
    sqlite_vec = pytest.importorskip("sqlite_vec")

    db = sqlite3.connect(":memory:")
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    cursor = db.cursor()
    cursor.execute(
        "CREATE VIRTUAL TABLE test_vec USING vec0(id text primary key, embedding float[4]);"
    )

    # Insert two sample vectors
    cursor.execute(
        "INSERT INTO test_vec(id, embedding) VALUES (?, ?);",
        ["doc_ai", "[0.5, 0.5, 0.5, 0.5]"],
    )
    cursor.execute(
        "INSERT INTO test_vec(id, embedding) VALUES (?, ?);",
        ["doc_other", "[0.0, 0.0, 0.0, 1.0]"],
    )

    # Query nearest neighbor
    cursor.execute(
        "SELECT id, distance FROM test_vec WHERE embedding MATCH ? ORDER BY distance LIMIT 1;",
        ["[0.5, 0.5, 0.5, 0.5]"],
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "doc_ai"
    assert pytest.approx(row[1], abs=1e-5) == 0.0
    db.close()
