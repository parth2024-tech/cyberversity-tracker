"""
Vault Feedback Service.
Analyzes entries pinned to the user's permanent Vault to build an adaptive
user interest profile, creating a closed-loop learning mechanism that
boosts candidate entries matching what the user personally cares about.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.analyzers.embedding_service import (
    embedding_service,
)
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

logger = get_logger(__name__)

# Common stop words to exclude from preference profile
VAULT_STOP_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "in",
    "on",
    "at",
    "for",
    "with",
    "by",
    "of",
    "to",
    "from",
    "is",
    "are",
    "was",
    "were",
    "new",
    "released",
    "announces",
    "announcing",
    "show",
    "hn",
    "ask",
    "github",
    "via",
    "using",
    "how",
    "what",
}


class VaultFeedbackService:
    """Extracts preference signals from vaulted entries and computes affinity scores for candidates."""

    def __init__(
        self,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None,
        cache_ttl_seconds: int = 300,
        rocchio_alpha: float = 0.35,
    ):
        self._uow_factory = uow_factory or (lambda: SqlAlchemyUnitOfWork())
        self._cache_ttl_seconds = cache_ttl_seconds
        self._rocchio_alpha = rocchio_alpha
        self._last_profile_refresh: datetime | None = None
        self._keyword_weights: Counter[str] = Counter()
        self._ecosystem_weights: Counter[str] = Counter()
        self._category_weights: Counter[str] = Counter()
        self._total_vaulted = 0
        self._total_dismissed = 0
        # Pillar 2: Active Personalization Loop (Rocchio Dynamic Vector Centroid)
        self._user_centroid: list[float] | None = None

    @property
    def user_centroid(self) -> list[float] | None:
        """Current normalized user preference centroid vector."""
        return self._user_centroid

    def set_user_centroid(self, centroid: list[float] | None) -> None:
        """Directly inject preference centroid (used in tests or manual profiles)."""
        if centroid is not None:
            norm = math.sqrt(sum(x * x for x in centroid))
            if norm > 1e-9:
                self._user_centroid = [x / norm for x in centroid]
                return
        self._user_centroid = None

    def get_centroid_summary(self) -> dict[str, Any]:
        """Telemetry summary of active Rocchio personalization centroid."""
        return {
            "total_vaulted": self._total_vaulted,
            "total_dismissed": self._total_dismissed,
            "centroid_active": self._user_centroid is not None,
            "centroid_dimension": len(self._user_centroid)
            if self._user_centroid
            else 0,
            "rocchio_alpha": self._rocchio_alpha,
            "top_keywords": [k for k, _ in self._keyword_weights.most_common(5)],
        }

    async def refresh_profile(self, force: bool = False) -> None:
        """Scan permanent vault entries (positive) and dismissed entries (negative)
        to rebuild both the keyword profile and the Rocchio vector centroid.
        """
        now = datetime.now(UTC)
        if (
            not force
            and self._last_profile_refresh
            and (now - self._last_profile_refresh).total_seconds()
            < self._cache_ttl_seconds
        ):
            return

        try:
            async with self._uow_factory() as uow:
                # 1. Query vaulted/starred entries (Positive Feedback)
                filters_v = EntryFilters(important_only=True)
                vaulted_entries = await uow.entries.list(
                    filters=filters_v, pagination=PaginationParams(limit=200)
                )

                # 2. Query dismissed/purged entries (Negative Feedback)
                filters_d = EntryFilters(purged_only=True)
                dismissed_entries = await uow.entries.list(
                    filters=filters_d, pagination=PaginationParams(limit=200)
                )

            keyword_counts: Counter[str] = Counter()
            ecosystem_counts: Counter[str] = Counter()
            category_counts: Counter[str] = Counter()

            pos_vectors: list[list[float]] = []
            for entry in vaulted_entries:
                cat_val = (
                    entry.category.value
                    if hasattr(entry.category, "value")
                    else str(entry.category)
                )
                category_counts[cat_val] += 1

                # Extract keywords from title and summary
                text = f"{entry.title} {entry.summary}".strip()
                tokens = re.findall(r"\b[a-zA-Z0-9_\-\.]{3,20}\b", text.lower())
                for t in tokens:
                    if t not in VAULT_STOP_WORDS and not t.isdigit():
                        keyword_counts[t] += 1

                # Extract ecosystems if analysis exists
                if entry.analysis and entry.analysis.affected_ecosystem:
                    for eco in entry.analysis.affected_ecosystem:
                        ecosystem_counts[eco.lower()] += 1

                if text:
                    pos_vectors.append(embedding_service.embed_text(text))

            neg_vectors: list[list[float]] = []
            for entry in dismissed_entries:
                text = f"{entry.title} {entry.summary}".strip()
                if text:
                    neg_vectors.append(embedding_service.embed_text(text))

            # Compute Rocchio Centroid: c_user = c_pos - alpha * c_neg
            dim = embedding_service.dimension
            if pos_vectors:
                c_pos = [0.0] * dim
                for v in pos_vectors:
                    for i in range(dim):
                        c_pos[i] += v[i]
                c_pos = [x / len(pos_vectors) for x in c_pos]

                c_neg = [0.0] * dim
                if neg_vectors:
                    for v in neg_vectors:
                        for i in range(dim):
                            c_neg[i] += v[i]
                    c_neg = [x / len(neg_vectors) for x in c_neg]

                c_user = [c_pos[i] - self._rocchio_alpha * c_neg[i] for i in range(dim)]
                norm = math.sqrt(sum(x * x for x in c_user))
                if norm > 1e-9:
                    self._user_centroid = [x / norm for x in c_user]
                else:
                    self._user_centroid = None
            else:
                self._user_centroid = None

            self._keyword_weights = keyword_counts
            self._ecosystem_weights = ecosystem_counts
            self._category_weights = category_counts
            self._total_vaulted = len(vaulted_entries)
            self._total_dismissed = len(dismissed_entries)
            self._last_profile_refresh = now
            logger.debug(
                f"Refreshed Vault profile from {self._total_vaulted} vaulted and "
                f"{self._total_dismissed} dismissed entries (centroid active: {self._user_centroid is not None})"
            )
        except Exception as e:
            logger.warning(f"Failed to refresh Vault preference profile: {e}")

    def calculate_affinity(self, entry: Entry) -> float:
        """Calculate dynamic personalized affinity score (0.0 to 1.0)
        combining Rocchio vector centroid cosine similarity and heuristic profile alignment.
        """
        if self._total_vaulted == 0 and self._user_centroid is None:
            return 0.0

        heuristic_score = 0.0
        text = f"{entry.title} {entry.summary}".strip()
        tokens = set(re.findall(r"\b[a-zA-Z0-9_\-\.]{3,20}\b", text.lower()))

        # 1. Keyword overlap with vaulted items
        keyword_hits = 0
        total_token_weight = 0
        for token in tokens:
            if token in self._keyword_weights:
                keyword_hits += 1
                total_token_weight += self._keyword_weights[token]

        if keyword_hits > 0:
            keyword_score = min(
                0.6,
                (total_token_weight / max(1, self._total_vaulted)) * 0.15
                + (keyword_hits * 0.08),
            )
            heuristic_score += keyword_score

        # 2. Ecosystem alignment
        if entry.analysis and entry.analysis.affected_ecosystem:
            eco_hits = sum(
                1
                for eco in entry.analysis.affected_ecosystem
                if eco.lower() in self._ecosystem_weights
            )
            if eco_hits > 0:
                heuristic_score += min(0.3, eco_hits * 0.15)

        # 3. Category alignment
        cat_val = (
            entry.category.value
            if hasattr(entry.category, "value")
            else str(entry.category)
        )
        if cat_val in self._category_weights:
            cat_ratio = self._category_weights[cat_val] / max(1, self._total_vaulted)
            heuristic_score += min(0.1, cat_ratio * 0.1)

        heuristic_score = min(1.0, heuristic_score)

        # 4. Pillar 2: Rocchio Vector Centroid Cosine Similarity
        if self._user_centroid is not None and text:
            entry_vec = embedding_service.embed_text(text)
            cos_sim = embedding_service.cosine_similarity(
                entry_vec, self._user_centroid
            )
            vector_affinity = max(0.0, cos_sim)
            # 70% dynamic vector centroid + 30% heuristic profile
            blended = 0.70 * vector_affinity + 0.30 * heuristic_score
            return min(1.0, round(blended, 3))

        return min(1.0, round(heuristic_score, 3))


# Global singleton vault feedback service
vault_feedback_service = VaultFeedbackService()
