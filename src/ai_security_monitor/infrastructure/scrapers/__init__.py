"""
Resilient Scrapers Package.
Targeting internal GraphQL and REST APIs with HTTP/2 session pooling and TLS spoofing.
"""

from __future__ import annotations

from ai_security_monitor.infrastructure.scrapers.core.client import (
    ResilientScraperClient,
)
from ai_security_monitor.infrastructure.scrapers.core.rate_limiter import RateLimiter
from ai_security_monitor.infrastructure.scrapers.core.session_pool import (
    SessionPool,
    TwitterAccount,
    default_session_pool,
)
from ai_security_monitor.infrastructure.scrapers.extractors.reddit_endpoints import (
    RedditEndpointsExtractor,
)
from ai_security_monitor.infrastructure.scrapers.extractors.twitter_graphql import (
    TwitterGraphQLExtractor,
)
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
    "RateLimiter",
    "RedditComment",
    "RedditEndpointsExtractor",
    "RedditPost",
    "ResilientScraperClient",
    "SessionPool",
    "Tweet",
    "TweetAuthor",
    "TweetMetrics",
    "TwitterAccount",
    "TwitterGraphQLExtractor",
    "default_session_pool",
]
