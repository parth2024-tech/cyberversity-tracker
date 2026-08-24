"""
Fetchers infrastructure package - plugin registration.
"""

# Import all fetchers to register them
from ai_security_monitor.infrastructure.fetchers import (
    arxiv_fetcher,
    base,
    cisa_fetcher,
    github_fetcher,
    github_trending_fetcher,
    hackernews_fetcher,
    nvd_fetcher,
    rss_fetcher,
)
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    FetcherRegistry,
    FetchResult,
    fetcher_registry,
)

__all__ = [
    "BaseFetcher",
    "FetchResult",
    "fetcher_registry",
    "FetcherRegistry",
]
