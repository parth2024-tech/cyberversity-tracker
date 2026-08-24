"""
Fetchers infrastructure package - plugin registration.
"""

# Import all fetchers to register them
from ai_security_monitor.infrastructure.fetchers import (
    base,
    rss_fetcher,
    arxiv_fetcher,
    nvd_fetcher,
    github_fetcher,
    cisa_fetcher,
    hackernews_fetcher,
    github_trending_fetcher,
)

from ai_security_monitor.infrastructure.fetchers.base import BaseFetcher, FetchResult, fetcher_registry, FetcherRegistry

__all__ = [
    "BaseFetcher",
    "FetchResult",
    "fetcher_registry",
    "FetcherRegistry",
]