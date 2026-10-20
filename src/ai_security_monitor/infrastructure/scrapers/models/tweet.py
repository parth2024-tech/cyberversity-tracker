"""
Pydantic schemas for normalized Twitter / X entities extracted from GraphQL responses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class TweetAuthor(BaseModel):
    """Author metadata for a tweet."""

    id: str = ""
    name: str = ""
    screen_name: str = ""
    verified: bool = False
    profile_image_url: str = ""

    @property
    def handle(self) -> str:
        """Formatted handle with @ prefix."""
        if self.screen_name.startswith("@"):
            return self.screen_name
        return f"@{self.screen_name}" if self.screen_name else "@unknown"


class TweetMetrics(BaseModel):
    """Engagement metrics for a tweet."""

    retweet_count: int = 0
    reply_count: int = 0
    favorite_count: int = 0
    quote_count: int = 0
    view_count: int | None = None


class Tweet(BaseModel):
    """Normalized Tweet representation."""

    id: str
    text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    author: TweetAuthor = Field(default_factory=TweetAuthor)
    metrics: TweetMetrics = Field(default_factory=TweetMetrics)
    url: str = ""
    hashtags: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    is_retweet: bool = False
    is_quote: bool = False
    language: str = "en"
    raw_data: dict[str, Any] = Field(default_factory=dict)
