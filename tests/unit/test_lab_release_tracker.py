"""
Unit tests for Feature 5: Lab Release Tracker (Primary vs Aggregator).
Verifies:
1. Primary Source / Entry entity modeling and persistence mapping.
2. Deduplication cluster anchor election:
   - Primary arrival first: primary is elected cluster anchor.
   - Aggregator arrival first followed by primary: primary promotes to cluster anchor.
   - Cluster of 3 entries (1 primary, 2 aggregators): primary is elected anchor.
3. 1.5x heat ranking boost for primary lab announcements.
4. Balanced daily digest composition guarantees at least 50% primary items if available.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.balanced_digest import (
    BalancedDigestService,
    CategoryQuota,
)
from ai_security_monitor.application.services.deduplication_service import (
    DeduplicationService,
)
from ai_security_monitor.application.services.heat_ranking_service import (
    HeatRankingService,
)
from ai_security_monitor.config.sources import SourceConfig
from ai_security_monitor.domain.entities import Category, Entry, Source, Story


def make_entry(
    title: str,
    url: str,
    is_primary: bool = False,
    published_at: datetime | None = None,
    category: Category = Category.AI_MODELS,
    summary: str | None = None,
    source_name: str | None = None,
    score: int = 80,
) -> Entry:
    meta = {"priority_score": score, "source_tier": 1.0 if is_primary else 2.0}
    if source_name:
        meta["source_name"] = source_name
    return Entry(
        id=uuid4(),
        source_id=uuid4(),
        title=title,
        url=url,
        content_hash=f"hash_{title}_{uuid4().hex[:6]}",
        summary=summary or f"Summary for {title}",
        published_at=published_at or datetime.now(UTC),
        category=category,
        is_primary=is_primary,
        metadata=meta,
    )


class TestLabReleaseTracker:
    def test_source_and_entry_primary_flag_defaults(self):
        """Source and Entry have is_primary flags defaulting to False."""
        src = Source(
            name="Community Aggregator",
            category=Category.AI_MODELS,
            type=Category.AI_MODELS,  # type: ignore
            url="https://aggregator.example.com/rss",
        )
        assert src.is_primary is False

        entry = Entry(
            source_id=uuid4(),
            title="Aggregator Post",
            url="https://aggregator.example.com/post-1",
            content_hash="h1",
            summary="Test",
            category=Category.AI_MODELS,
            published_at=datetime.now(UTC),
        )
        assert entry.is_primary is False

    def test_source_config_primary_resolution(self):
        """SourceConfig infers primary from tier, category, or explicit config."""
        # Explicit primary
        cfg_explicit = SourceConfig(
            name="Custom Official Lab",
            url="https://lab.org/feed",
            category="ai_tech",
            type="rss",
            is_primary=True,
        )
        assert cfg_explicit.primary is True

        # Inferred from tier 1.0
        cfg_tier1 = SourceConfig(
            name="DeepSeek Blog",
            url="https://deepseek.com/rss",
            category="ai_tech",
            type="rss",
            tier=1.0,
        )
        assert cfg_tier1.primary is True

        # Inferred from category ai_models
        cfg_models = SourceConfig(
            name="Frontier Lab Feed",
            url="https://models.org/rss",
            category="ai_models",
            type="rss",
            tier=1.5,
        )
        assert cfg_models.primary is True

        # Community aggregator is not primary
        cfg_agg = SourceConfig(
            name="Reddit Machine Learning",
            url="https://reddit.com/r/MachineLearning/.rss",
            category="ai_tech",
            type="rss",
            tier=2.0,
        )
        assert cfg_agg.primary is False

    def test_cluster_of_three_entries_elects_primary_anchor(self):
        """Cluster of 3 entries (1 primary, 2 aggregators) must elect the primary as the anchor."""
        dedup = DeduplicationService(similarity_threshold=0.50)
        shared_url = "https://github.com/deepseek-ai/DeepSeek-V3"

        # 1. Aggregator 1 arrives first
        agg1 = make_entry(
            title="TechCrunch: DeepSeek releases massive open source V3 model",
            url=shared_url,
            is_primary=False,
            summary="TechCrunch article summarizing the launch",
            source_name="TechCrunch",
        )
        proc1, story1, is_new1 = dedup.process_candidate(agg1, source_name="TechCrunch")
        assert is_new1 is True
        assert story1.is_primary is False
        assert story1.anchor_entry_id == agg1.id
        assert story1.title == agg1.title

        # 2. Aggregator 2 arrives second
        agg2 = make_entry(
            title="Hacker News: DeepSeek-V3 Open Weights Announced",
            url=shared_url,
            is_primary=False,
            summary="Hacker News submission on V3",
            source_name="Hacker News",
        )
        proc2, story2, is_new2 = dedup.process_candidate(
            agg2, source_name="Hacker News"
        )
        assert is_new2 is False
        assert story2.id == story1.id
        assert story2.is_primary is False
        assert story2.anchor_entry_id == agg1.id

        # 3. Official Lab Primary announcement arrives third
        primary_entry = make_entry(
            title="DeepSeek-V3: Official Technical Report & Model Weights",
            url=shared_url,
            is_primary=True,
            summary="Official DeepSeek AI announcement: 671B parameter Mixture-of-Experts model",
            source_name="DeepSeek Official",
        )
        proc3, story3, is_new3 = dedup.process_candidate(
            primary_entry, source_name="DeepSeek Official"
        )
        assert is_new3 is False
        assert story3.id == story1.id

        # Assert Primary Entry was promoted to Anchor of the cluster
        assert story3.is_primary is True
        assert story3.anchor_entry_id == primary_entry.id
        assert story3.title == primary_entry.title
        assert story3.summary == primary_entry.summary
        assert story3.canonical_url == primary_entry.url
        assert "DeepSeek Official" in story3.sources
        assert len(story3.entry_ids) == 3

    def test_cluster_with_primary_arriving_first_preserves_primary_anchor(self):
        """When the primary announcement arrives first, subsequent aggregators preserve the primary anchor."""
        dedup = DeduplicationService(similarity_threshold=0.50)
        shared_url = "https://github.com/vllm-project/vllm"

        primary_entry = make_entry(
            title="vLLM 0.7.0 Released with DeepSeek-R1 Support",
            url=shared_url,
            is_primary=True,
            summary="Official vLLM project release notes",
            source_name="vLLM Project",
        )
        proc1, story1, is_new1 = dedup.process_candidate(
            primary_entry, source_name="vLLM Project"
        )
        assert is_new1 is True
        assert story1.is_primary is True
        assert story1.anchor_entry_id == primary_entry.id
        assert story1.title == primary_entry.title

        agg1 = make_entry(
            title="VentureBeat: vLLM adds support for DeepSeek reasoning models",
            url=shared_url,
            is_primary=False,
            summary="VentureBeat summary",
            source_name="VentureBeat",
        )
        proc2, story2, is_new2 = dedup.process_candidate(
            agg1, source_name="VentureBeat"
        )
        assert is_new2 is False
        # Anchor remains the primary entry
        assert story2.is_primary is True
        assert story2.anchor_entry_id == primary_entry.id
        assert story2.title == primary_entry.title

    def test_heat_ranking_primary_boost(self):
        """Primary entries receive a 1.5x base multiplier compared to aggregators at identical timestamps."""
        now = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)
        service = HeatRankingService(half_life_hours=24.0)

        # Standalone aggregator at t0
        agg = make_entry(
            "Aggregator Article",
            "https://example.com/agg",
            is_primary=False,
            published_at=now,
        )
        heat_agg, _ = service.compute_entry_heat(agg, now=now)

        # Standalone primary at t0
        pri = make_entry(
            "Official Lab Announcement",
            "https://example.com/pri",
            is_primary=True,
            published_at=now,
        )
        heat_pri, _ = service.compute_entry_heat(pri, now=now)

        # Base decay weight is 1.0. Primary gets 1.5x boost
        assert heat_agg == 1.0
        assert heat_pri == 1.5
        assert round(heat_pri / heat_agg, 2) == 1.50

        # When ranking, primary ranks above aggregator
        ranked = service.rank_entries_by_heat([agg, pri], now=now)
        assert ranked[0].id == pri.id
        assert ranked[1].id == agg.id

    def test_story_heat_primary_boost(self):
        """Story aggregate heat scales by 1.5x when cluster is primary."""
        now = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)

        # Story with is_primary = False
        non_pri_story = Story(
            title="Secondary Story",
            canonical_url="https://example.com/s",
            fingerprint="fp1",
            category=Category.AI_MODELS,
            participant_timestamps=[now, now],
            source_count=2,
            is_primary=False,
        )
        non_pri_heat = non_pri_story.calculate_heat(now=now)
        # 1.0 + 1.0 = 2.0
        assert non_pri_heat == 2.0

        # Story with is_primary = True
        pri_story = Story(
            title="Primary Lab Story",
            canonical_url="https://example.com/p",
            fingerprint="fp2",
            category=Category.AI_MODELS,
            participant_timestamps=[now, now],
            source_count=2,
            is_primary=True,
        )
        pri_heat = pri_story.calculate_heat(now=now)
        # (1.0 + 1.0) * 1.5 = 3.0
        assert pri_heat == 3.0
        assert round(pri_heat / non_pri_heat, 2) == 1.50

    def test_balanced_digest_composition_guarantees_primary_allocation(self):
        """Daily digest must contain at least 50% primary items if available."""
        quotas = [
            CategoryQuota(name="Models", limit=5, categories=["ai_models"]),
            CategoryQuota(name="Papers", limit=5, categories=["ai_research"]),
        ]
        service = BalancedDigestService(
            quotas=quotas,
            max_total_items=10,
            min_primary_ratio=0.50,
        )

        # 10 aggregator entries with high scores (95 down to 86)
        aggregators = [
            make_entry(
                f"Aggregator Story {i}",
                f"https://agg.com/{i}",
                is_primary=False,
                category=Category.AI_MODELS,
                score=95 - i,
                source_name=f"AggSource_{i % 3}",
            )
            for i in range(10)
        ]

        # 5 primary entries with slightly lower scores (85 down to 81)
        primaries = [
            make_entry(
                f"Official Lab Release {i}",
                f"https://lab.org/{i}",
                is_primary=True,
                category=Category.AI_MODELS,
                score=85 - i,
                source_name=f"OfficialLab_{i % 3}",
            )
            for i in range(5)
        ]

        # Combined pool: aggregators outnumber and outscore primaries
        pool = aggregators + primaries
        result = service.balance(
            pool, sort_key=lambda e: e.metadata.get("priority_score", 0)
        )

        # Assert selection:
        # Without primary guarantee, the 10 slots would be dominated by high-scoring aggregators.
        # With min_primary_ratio=0.50, at least 50% of the selected digest must be primary items!
        assert result.total_selected > 0
        primary_selected = [e for e in result.items if e.is_primary]
        assert len(primary_selected) >= 5
        assert result.primary_ratio >= 0.50
        assert result.primary_count == len(primary_selected)

    @pytest.mark.asyncio
    async def test_repository_persistence_of_is_primary(self):
        """SQLAlchemy repositories accurately persist and query is_primary for Source and Entry."""
        from ai_security_monitor.domain.entities import SourceType
        from ai_security_monitor.infrastructure.database.unit_of_work import (
            SqlAlchemyUnitOfWork,
        )

        async with SqlAlchemyUnitOfWork() as uow:
            # 1. Add primary source
            src = Source(
                name=f"Primary Test Lab {uuid4().hex[:6]}",
                category=Category.AI_MODELS,
                type=SourceType.RSS,
                url=f"https://testlab-{uuid4().hex[:6]}.org/rss",
                is_primary=True,
            )
            saved_src = await uow.sources.add(src)
            assert saved_src.is_primary is True

            # 2. Add primary entry linked to source
            entry = Entry(
                source_id=saved_src.id,
                title=f"Frontier Model Release {uuid4().hex[:6]}",
                url=f"https://testlab.org/release/{uuid4().hex[:6]}",
                content_hash=f"hash_{uuid4().hex}",
                summary="Primary announcement text",
                published_at=datetime.now(UTC),
                category=Category.AI_MODELS,
                is_primary=True,
            )
            saved_entry = await uow.entries.add(entry)
            assert saved_entry.is_primary is True

        # 3. Reload from DB in a fresh unit of work to assert roundtrip
        async with SqlAlchemyUnitOfWork() as uow:
            reloaded_src = await uow.sources.get(saved_src.id)
            assert reloaded_src is not None
            assert reloaded_src.is_primary is True

            reloaded_entry = await uow.entries.get(saved_entry.id)
            assert reloaded_entry is not None
            assert reloaded_entry.is_primary is True
