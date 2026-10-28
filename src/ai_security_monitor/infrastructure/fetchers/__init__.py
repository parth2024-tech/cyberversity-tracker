"""
Fetchers infrastructure package - plugin registration.
"""

# Import all fetchers to register them
from ai_security_monitor.infrastructure.fetchers import (
    arxiv_fetcher,
    base,
    github_trending_fetcher,
    google_news_fetcher,
    hackernews_fetcher,
    huggingface_china_fetcher,
    huggingface_daily_papers_fetcher,
    huggingface_trending_fetcher,
    modelscope_fetcher,
    ossinsight_fetcher,
    reddit_fetcher,
    rss_fetcher,
    sitemap_fetcher,
    twitter_x_fetcher,
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
    "arxiv_fetcher",
    "base",
    "github_trending_fetcher",
    "google_news_fetcher",
    "hackernews_fetcher",
    "huggingface_china_fetcher",
    "huggingface_daily_papers_fetcher",
    "huggingface_trending_fetcher",
    "modelscope_fetcher",
    "ossinsight_fetcher",
    "reddit_fetcher",
    "rss_fetcher",
    "sitemap_fetcher",
    "twitter_x_fetcher",
]
