"""
Watchlist Rule domain entity for custom AI framework, lab, and model tracking (Feature 11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from ai_security_monitor.domain.entities import Category, Entry


@dataclass
class WatchlistRule:
    """User-defined intelligence tracking rule with multi-attribute filtering."""

    id: UUID = field(default_factory=uuid4)
    name: str = ""
    keywords: list[str] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)
    min_threat_velocity: int = 0
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Feature 11: Multi-Attribute Rules & Alert Channels
    lab: str | None = None
    model_family: str | None = None
    region: str | None = None
    min_score: float | None = None
    channel: str = "telegram"
    channel_config: dict[str, Any] = field(default_factory=dict)

    @property
    def rules_json(self) -> dict[str, Any]:
        """Serialize rule definition into dictionary."""
        return {
            "lab": self.lab,
            "model_family": self.model_family,
            "region": self.region,
            "min_score": self.min_score,
            "keywords": self.keywords,
            "categories": [
                c.value if hasattr(c, "value") else str(c) for c in self.categories
            ],
            "min_threat_velocity": self.min_threat_velocity,
            "channel": self.channel,
        }

    def matches(self, entry: Entry) -> bool:
        """Check if an intelligence entry matches this watchlist rule."""
        if not self.enabled:
            return False

        # Category filter check
        if self.categories and entry.category not in self.categories:
            return False

        # Velocity threshold check (backwards compatibility)
        if self.min_threat_velocity > 0:
            vel = 0
            if entry.analysis:
                vel = entry.analysis.threat_velocity
            elif hasattr(entry, "threat_velocity"):
                vel = getattr(entry, "threat_velocity", 0) or 0
            if vel < self.min_threat_velocity:
                return False

        # Minimum AI Velocity / Newsworthiness / Heat score check
        if self.min_score is not None and self.min_score > 0:
            score = 0.0
            if entry.metadata:
                score = float(
                    entry.metadata.get("ai_velocity_score")
                    or entry.metadata.get("score")
                    or entry.metadata.get("heat")
                    or 0.0
                )
            if score == 0.0 and entry.analysis:
                score = float(entry.analysis.threat_velocity)
            if score < self.min_score:
                return False

        # Region check
        if self.region:
            reg_target = self.region.strip().lower()
            entry_reg = ""
            if entry.metadata:
                entry_reg = str(
                    entry.metadata.get("region")
                    or entry.metadata.get("subject_region")
                    or ""
                ).lower()
            text_preview = f"{entry.title} {entry.summary}".lower()
            if reg_target not in entry_reg and reg_target not in text_preview:
                return False

        # Lab check
        if self.lab:
            lab_target = self.lab.strip().lower()
            entry_lab = ""
            if entry.metadata:
                entry_lab = str(
                    entry.metadata.get("lab") or entry.metadata.get("author") or ""
                ).lower()
            text_preview = f"{entry.title} {entry.summary}".lower()
            if lab_target != entry_lab and lab_target not in text_preview:
                return False

        # Model Family check
        if self.model_family:
            fam_target = self.model_family.strip().lower()
            entry_fam = ""
            if entry.metadata:
                entry_fam = str(entry.metadata.get("model_family") or "").lower()
            text_preview = f"{entry.title} {entry.summary}".lower()
            if fam_target != entry_fam and fam_target not in text_preview:
                return False

        # Keyword matching
        if self.keywords:
            tags_str = " ".join(entry.tags) if entry.tags else ""
            text_to_search = f"{entry.title} {entry.summary} {tags_str}".lower()
            if entry.metadata:
                text_to_search += f" {str(entry.metadata).lower()}"

            matched_any = False
            for kw in self.keywords:
                kw_clean = kw.strip().lower()
                if kw_clean and kw_clean in text_to_search:
                    matched_any = True
                    break
            if not matched_any:
                return False

        # Has at least one valid filtering condition
        has_constraint = bool(
            self.keywords
            or self.lab
            or self.model_family
            or self.region
            or (self.min_score is not None and self.min_score > 0)
            or self.min_threat_velocity > 0
            or self.categories
        )
        return has_constraint
