"""
Pydantic schemas for normalized Reddit posts and comment trees.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class RedditComment(BaseModel):
    """Normalized Reddit comment."""

    id: str
    author: str = "[deleted]"
    body: str = ""
    score: int = 0
    created_utc: float | None = None


class RedditPost(BaseModel):
    """Normalized Reddit submission post."""

    id: str
    title: str
    subreddit: str
    author: str = "redditor"
    score: int = 0
    num_comments: int = 0
    url: str = ""
    permalink: str = ""
    selftext: str = ""
    created_utc: float = Field(default_factory=lambda: datetime.now(UTC).timestamp())
    stickied: bool = False
    is_self: bool = True
    top_comments: list[RedditComment] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @property
    def created_datetime(self) -> datetime:
        """Convert created_utc to timezone-aware UTC datetime."""
        return datetime.fromtimestamp(self.created_utc, tz=UTC)

    @property
    def full_permalink(self) -> str:
        """Fully-qualified Reddit discussion permalink."""
        if self.permalink.startswith("http"):
            return self.permalink
        return f"https://www.reddit.com{self.permalink}"
