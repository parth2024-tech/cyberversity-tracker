"""Unit tests for 24h half-life heat decay ranking, participant aggregation, and badges."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ai_security_monitor.application.services.deduplication_service import (
    DeduplicationService,
)
from ai_security_monitor.application.services.heat_ranking_service import (
    HeatRankingService,
    heat_ranking_service,
)
from ai_security_monitor.domain.entities import Category, Entry, Story


def make_test_entry(
    title: str,
    published_at: datetime,
    source_name: str | None = None,
    url: str | None = None,
) -> Entry:
    meta = {}
    if source_name:
        meta["source_name"] = source_name
    return Entry(
        id=uuid4(),
        source_id=uuid4(),
        title=title,
        url=url or f"https://example.com/{title.replace(' ', '_')}",
        content_hash=f"hash_{title}_{published_at.timestamp()}",
        summary=f"Summary for {title}",
        published_at=published_at,
        category=Category.AI_MODELS,
        metadata=meta,
    )


def test_half_life_decay_weights():
    """Verify mathematical fidelity of 24h half-life decay weights at 0h, 24h, 48h, 72h."""
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
    service = HeatRankingService(half_life_hours=24.0)

    # 0 hours old -> 1.0
    w0 = service.calculate_decay_weight(now, now=now)
    assert w0 == 1.0

    # 24 hours old -> 0.5
    w24 = service.calculate_decay_weight(now - timedelta(hours=24), now=now)
    assert w24 == 0.5

    # 48 hours old -> 0.25
    w48 = service.calculate_decay_weight(now - timedelta(hours=48), now=now)
    assert w48 == 0.25

    # 72 hours old -> 0.125
    w72 = service.calculate_decay_weight(now - timedelta(hours=72), now=now)
    assert w72 == 0.125


def test_story_multi_participant_heat_aggregation():
    """Story aggregate heat must sum 0.5**(delta_t/24) across all participant timestamps."""
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)

    t0 = now  # 1.0
    t24 = now - timedelta(hours=24)  # 0.5

    story = Story(
        title="OpenAI o3 Model Release",
        canonical_url="https://openai.com/index/o3",
        fingerprint="fp_o3",
        category=Category.AI_MODELS,
        participant_timestamps=[t0, t24],
        source_count=2,
        sources=["OpenAI Official", "The Verge"],
    )

    heat = story.calculate_heat(now=now)
    assert heat == 1.5


def test_surge_badge_strictly_requires_two_unique_sources():
    """A story cannot be tagged 'surge' unless it has at least 2 unique corroborating sources."""
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)

    # High heat (2 fresh posts) but from only 1 single source
    single_source_story = Story(
        title="Solo Lab Release Spam",
        canonical_url="https://example.com/solo",
        fingerprint="fp_solo",
        category=Category.AI_MODELS,
        participant_timestamps=[now, now - timedelta(hours=1)],
        source_count=1,
        sources=["Solo Blog"],
    )

    single_badge = single_source_story.update_badge(now=now)
    # Heat is ~1.97, but source_count is 1 -> CANNOT be 'surge', falls back to 'rising'
    assert single_badge != "surge"
    assert single_badge == "rising"

    # Multi-source story (2 independent outlets) with strong heat -> surges!
    multi_source_story = Story(
        title="DeepSeek R1 Official Open Weights",
        canonical_url="https://github.com/deepseek-ai/DeepSeek-R1",
        fingerprint="fp_r1",
        category=Category.AI_MODELS,
        participant_timestamps=[now, now - timedelta(hours=2)],
        source_count=2,
        sources=["DeepSeek Official", "Hugging Face"],
    )

    multi_badge = multi_source_story.update_badge(now=now)
    assert multi_badge == "surge"
    assert multi_source_story.heat_badge == "surge"


def test_new_and_rising_badges_for_standalone_entries():
    """Standalone entries receive 'new' if <= 6h old, 'rising' if <= 12h old with good velocity."""
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)

    new_entry = make_test_entry("Fresh arXiv Paper", published_at=now - timedelta(hours=2))
    h1, b1 = heat_ranking_service.compute_entry_heat(new_entry, now=now)
    assert b1 == "new"
    assert h1 > 0.9

    rising_entry = make_test_entry("Midday Repo", published_at=now - timedelta(hours=8))
    h2, b2 = heat_ranking_service.compute_entry_heat(rising_entry, now=now)
    assert b2 == "rising"

    older_entry = make_test_entry("Older Blog Post", published_at=now - timedelta(hours=36))
    h3, b3 = heat_ranking_service.compute_entry_heat(older_entry, now=now)
    assert b3 is None
    assert h3 < 0.4


def test_deduplication_service_elevates_cluster_to_surge():
    """Ingesting corroborating entries across distinct sources elevates the story and entry to 'surge'."""
    now = datetime.now(UTC)
    dedup = DeduplicationService()

    entry1 = make_test_entry(
        title="DeepSeek-R1 Released: Open Reasoning Model",
        published_at=now - timedelta(hours=1),
        source_name="DeepSeek AI",
        url="https://github.com/deepseek-ai/DeepSeek-R1",
    )
    e1, story1, is_new1 = dedup.process_candidate(entry1, source_name="DeepSeek AI")
    assert is_new1 is True
    assert story1.source_count == 1
    # First entry from single source: 'rising' or 'new'
    assert e1.metadata["heat_badge"] in ("new", "rising")

    # Second entry: wire report covering the exact same GitHub repository
    entry2 = make_test_entry(
        title="DeepSeek-R1 Released: Open Reasoning Model",
        published_at=now - timedelta(minutes=30),
        source_name="Hacker News Trending",
        url="https://github.com/deepseek-ai/DeepSeek-R1",
    )
    e2, story2, is_new2 = dedup.process_candidate(entry2, source_name="Hacker News Trending")
    assert is_new2 is False
    assert story2.id == story1.id
    assert story2.source_count == 2
    # Second independent source arrives: elevates cluster to 'surge'!
    assert story2.heat_badge == "surge"
    assert e2.metadata["heat_badge"] == "surge"
    assert e2.metadata["heat_score"] >= 1.6
