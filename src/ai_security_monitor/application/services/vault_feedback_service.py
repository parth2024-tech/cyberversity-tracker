"""
Vault Feedback Service.
Analyzes entries pinned to the user's permanent Vault to build an adaptive
user interest profile, creating a closed-loop learning mechanism that
boosts candidate entries matching what the user personally cares about.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry
from ai_security_monitor.domain.repositories import EntryFilters
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

logger = get_logger(__name__)

# Common stop words to exclude from preference profile
VAULT_STOP_WORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "for", "with", "by", "of",
    "to", "from", "is", "are", "was", "were", "new", "released", "announces",
    "announcing", "show", "hn", "ask", "github", "via", "using", "how", "what",
}


class VaultFeedbackService:
    """Extracts preference signals from vaulted entries and computes affinity scores for candidates."""

    def __init__(
        self,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None,
        cache_ttl_seconds: int = 300,
    ):
        self._uow_factory = uow_factory or (lambda: SqlAlchemyUnitOfWork())
        self._cache_ttl_seconds = cache_ttl_seconds
        self._last_profile_refresh: datetime | None = None
        self._keyword_weights: Counter[str] = Counter()
        self._ecosystem_weights: Counter[str] = Counter()
        self._category_weights: Counter[str] = Counter()
        self._total_vaulted = 0

    async def refresh_profile(self, force: bool = False) -> None:
        """Scan permanent vault entries to rebuild the interest profile."""
        now = datetime.now(UTC)
        if (
            not force
            and self._last_profile_refresh
            and (now - self._last_profile_refresh).total_seconds() < self._cache_ttl_seconds
        ):
            return

        try:
            async with self._uow_factory() as uow:
                # Query vaulted/starred entries
                filters = EntryFilters(important_only=True, limit=200)
                vaulted_entries = await uow.entries.list(filters=filters)

            keyword_counts: Counter[str] = Counter()
            ecosystem_counts: Counter[str] = Counter()
            category_counts: Counter[str] = Counter()

            for entry in vaulted_entries:
                cat_val = (
                    entry.category.value
                    if hasattr(entry.category, "value")
                    else str(entry.category)
                )
                category_counts[cat_val] += 1

                # Extract keywords from title and summary
                text = f"{entry.title} {entry.summary}".lower()
                tokens = re.findall(r"\b[a-zA-Z0-9_\-\.]{3,20}\b", text)
                for t in tokens:
                    if t not in VAULT_STOP_WORDS and not t.isdigit():
                        keyword_counts[t] += 1

                # Extract ecosystems if analysis exists
                if entry.analysis and entry.analysis.affected_ecosystem:
                    for eco in entry.analysis.affected_ecosystem:
                        ecosystem_counts[eco.lower()] += 1

            self._keyword_weights = keyword_counts
            self._ecosystem_weights = ecosystem_counts
            self._category_weights = category_counts
            self._total_vaulted = len(vaulted_entries)
            self._last_profile_refresh = now
            logger.debug(
                f"Refreshed Vault profile from {self._total_vaulted} vaulted entries "
                f"({len(self._keyword_weights)} distinct keywords)"
            )
        except Exception as e:
            logger.warning(f"Failed to refresh Vault preference profile: {e}")

    def calculate_affinity(self, entry: Entry) -> float:
        """Calculate affinity score (0.0 to 1.0) between candidate entry and Vault profile."""
        if self._total_vaulted == 0:
            return 0.0

        score = 0.0
        text = f"{entry.title} {entry.summary}".lower()
        tokens = set(re.findall(r"\b[a-zA-Z0-9_\-\.]{3,20}\b", text))

        # 1. Keyword overlap with vaulted items
        keyword_hits = 0
        total_token_weight = 0
        for token in tokens:
            if token in self._keyword_weights:
                keyword_hits += 1
                total_token_weight += self._keyword_weights[token]

        if keyword_hits > 0:
            # Normalize keyword affinity by total vaulted items
            keyword_score = min(0.6, (total_token_weight / max(1, self._total_vaulted)) * 0.15 + (keyword_hits * 0.08))
            score += keyword_score

        # 2. Ecosystem alignment
        if entry.analysis and entry.analysis.affected_ecosystem:
            eco_hits = sum(
                1 for eco in entry.analysis.affected_ecosystem
                if eco.lower() in self._ecosystem_weights
            )
            if eco_hits > 0:
                score += min(0.3, eco_hits * 0.15)

        # 3. Category alignment
        cat_val = (
            entry.category.value
            if hasattr(entry.category, "value")
            else str(entry.category)
        )
        if cat_val in self._category_weights:
            cat_ratio = self._category_weights[cat_val] / max(1, self._total_vaulted)
            score += min(0.1, cat_ratio * 0.1)

        return min(1.0, round(score, 3))


# Global singleton vault feedback service
vault_feedback_service = VaultFeedbackService()
