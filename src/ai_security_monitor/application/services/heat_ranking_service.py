"""
Half-Life Heat Decay Ranking and Story Momentum Badging Service.
Computes 24h half-life heat decay: Heat = sum(0.5 ** (delta_t / 24)) across cluster participants
and assigns high-signal badges: 'surge' (>= 2 unique sources), 'rising', and 'new'.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry, Story

logger = get_logger(__name__)


class HeatRankingService:
    """Calculates half-life heat decay scores and dynamic story badges."""

    def __init__(self, half_life_hours: float = 24.0):
        self.half_life_hours = half_life_hours

    def calculate_decay_weight(
        self, timestamp: datetime, now: datetime | None = None
    ) -> float:
        """Calculate single participant weight: 0.5 ** (delta_t / 24.0)."""
        ref_time = now or datetime.now(UTC)
        ts_aware = (
            timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
        )
        ref_aware = (
            ref_time if ref_time.tzinfo is not None else ref_time.replace(tzinfo=UTC)
        )
        delta_hours = max(0.0, (ref_aware - ts_aware).total_seconds() / 3600.0)
        return round(0.5 ** (delta_hours / self.half_life_hours), 4)

    def calculate_story_heat(self, story: Story, now: datetime | None = None) -> float:
        """Compute aggregate heat for a story cluster across all participant timestamps."""
        ref_time = now or datetime.now(UTC)
        return story.calculate_heat(now=ref_time, half_life_hours=self.half_life_hours)

    def compute_entry_heat(
        self,
        entry: Entry,
        story: Story | None = None,
        now: datetime | None = None,
    ) -> tuple[float, str | None]:
        """Compute entry heat score and badge.

        If entry is linked to a Story cluster, inherits story-level consensus heat and badge.
        Otherwise computes standalone single-participant heat.
        """
        ref_time = now or datetime.now(UTC)

        if story:
            heat = story.calculate_heat(
                now=ref_time, half_life_hours=self.half_life_hours
            )
            story_badge = story.update_badge(now=ref_time)
            return heat, story_badge

        # Standalone entry
        ts = entry.published_at or entry.created_at or ref_time
        weight = self.calculate_decay_weight(ts, now=ref_time)

        # Standalone badge evaluation:
        # NOTE: 'surge' strictly requires at least 2 unique corroborating sources, so single entries cannot surge.
        ts_aware = ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
        ref_aware = (
            ref_time if ref_time.tzinfo is not None else ref_time.replace(tzinfo=UTC)
        )
        delta_hours = max(0.0, (ref_aware - ts_aware).total_seconds() / 3600.0)

        badge: str | None = None
        if delta_hours <= 6.0:
            badge = "new"
        elif delta_hours <= 12.0 and weight >= 0.70:
            badge = "rising"

        return round(weight, 3), badge

    def rank_entries_by_heat(
        self,
        entries: list[Entry],
        story_map: dict[UUID, Story] | None = None,
        now: datetime | None = None,
    ) -> list[Entry]:
        """Sort entries by half-life heat score descending."""
        ref_time = now or datetime.now(UTC)

        def get_heat(e: Entry) -> float:
            story = story_map.get(e.story_id) if (story_map and e.story_id) else None
            h, _ = self.compute_entry_heat(e, story=story, now=ref_time)
            return h

        sorted_entries = list(entries)
        sorted_entries.sort(key=get_heat, reverse=True)
        return sorted_entries


heat_ranking_service = HeatRankingService()
