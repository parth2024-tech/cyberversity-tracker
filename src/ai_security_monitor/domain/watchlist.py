"""
Watchlist Rule domain entity for custom framework & asset threat tracking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from ai_security_monitor.domain.entities import Category, Entry


@dataclass
class WatchlistRule:
    """User-defined threat hunting rule for tracking custom frameworks and keywords."""
    id: UUID = field(default_factory=uuid4)
    name: str = ""
    keywords: list[str] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)
    min_threat_velocity: int = 0
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)

    def matches(self, entry: Entry) -> bool:
        """Check if an intelligence entry matches this watchlist rule."""
        if not self.enabled:
            return False

        # Category filter check
        if self.categories and entry.category not in self.categories:
            return False

        # Velocity threshold check
        if self.min_threat_velocity > 0:
            vel = 0
            if entry.analysis:
                vel = entry.analysis.threat_velocity
            elif hasattr(entry, "threat_velocity"):
                vel = getattr(entry, "threat_velocity") or 0
            if vel < self.min_threat_velocity:
                return False

        # Keyword matching across title, summary, and tags
        text_to_search = f"{entry.title} {entry.summary} {' '.join(entry.tags)}".lower()
        if entry.metadata:
            text_to_search += f" {str(entry.metadata).lower()}"

        for kw in self.keywords:
            kw_clean = kw.strip().lower()
            if kw_clean and kw_clean in text_to_search:
                return True

        return False
