"""
Scraper models package.
"""

from __future__ import annotations

from ai_security_monitor.infrastructure.scrapers.models.reddit_post import (
    RedditComment,
    RedditPost,
)
from ai_security_monitor.infrastructure.scrapers.models.tweet import (
    Tweet,
    TweetAuthor,
    TweetMetrics,
)

__all__ = [
    "RedditComment",
    "RedditPost",
    "Tweet",
    "TweetAuthor",
    "TweetMetrics",
]
