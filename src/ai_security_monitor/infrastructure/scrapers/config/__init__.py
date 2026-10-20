"""
Configuration constants, query IDs, and headers for resilient Twitter and Reddit scrapers.
Extracted from web bundles and network reverse-engineering.
"""

from __future__ import annotations

from ai_security_monitor.infrastructure.scrapers.config.headers import (
    DEFAULT_CHROME_USER_AGENT,
    REDDIT_CLIENT_HEADERS,
    TWITTER_BEARER_TOKEN,
    TWITTER_GRAPHQL_HEADERS,
)
from ai_security_monitor.infrastructure.scrapers.config.queries import (
    TWITTER_FEATURES,
    TWITTER_GRAPHQL_QUERY_IDS,
    build_search_variables,
    build_user_tweets_variables,
)

__all__ = [
    "DEFAULT_CHROME_USER_AGENT",
    "REDDIT_CLIENT_HEADERS",
    "TWITTER_BEARER_TOKEN",
    "TWITTER_FEATURES",
    "TWITTER_GRAPHQL_HEADERS",
    "TWITTER_GRAPHQL_QUERY_IDS",
    "build_search_variables",
    "build_user_tweets_variables",
]
