"""
Twitter/X fetcher powered by the resilient internal GraphQL scraper engine
with automatic syndication fallback to ensure 100% continuous uptime.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import feedparser

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry, SourceType
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)
from ai_security_monitor.infrastructure.scrapers.config.queries import (
    TWITTER_FEATURES,
    TWITTER_GRAPHQL_QUERY_IDS,
    build_search_variables,
)
from ai_security_monitor.infrastructure.scrapers.core.client import (
    ResilientScraperClient,
)
from ai_security_monitor.infrastructure.scrapers.extractors.twitter_graphql import (
    TwitterGraphQLExtractor,
)
from ai_security_monitor.infrastructure.scrapers.models.tweet import Tweet

logger = get_logger(__name__)

DEFAULT_AI_TWITTER_QUERIES = [
    'site:x.com ("arXiv" OR "benchmark" OR "reasoning model") AI when:14d',
    'site:x.com ("DeepSeek" OR "Claude" OR "OpenAI" OR "Qwen" OR "Llama") model when:14d',
    'site:x.com ("vLLM" OR "Ollama" OR "SGLang" OR "llama.cpp" OR "ComfyUI") when:14d',
    'site:x.com ("agent" OR "coding agent" OR "AI agent") framework when:14d',
]


class TwitterXFetcher(BaseFetcher):
    """Fetcher for live AI community announcements on Twitter / X."""

    @property
    def fetcher_type(self) -> str:
        return "twitter_x"

    def _resolve_queries(self) -> list[str]:
        """Resolve query set from source configuration or defaults."""
        if self.source and self.source.config:
            if "queries" in self.source.config:
                return list(self.source.config["queries"])
            if "handles" in self.source.config:
                return [
                    f"site:x.com/{h} when:14d" for h in self.source.config["handles"]
                ]
            if "query" in self.source.config:
                return [str(self.source.config["query"])]

        if self.source and self.source.url and "x.com" in self.source.url:
            handle_match = re.search(r"x\.com/([A-Za-z0-9_]+)", self.source.url)
            if handle_match:
                return [f"site:x.com/{handle_match.group(1)} when:14d"]

        return DEFAULT_AI_TWITTER_QUERIES

    async def _fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch matching tweets via GraphQL or high-recall syndication fallback."""
        queries = self._resolve_queries()
        fetch_limit = int(
            self.source.config.get("fetch_limit", 25)
            if self.source and self.source.config
            else 25
        )
        max_age_days = getattr(settings.database, "max_ingest_age_days", 14)
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)

        raw_entries: list[dict[str, Any]] = []
        seen_links: set[str] = set()

        async with ResilientScraperClient(timeout=self.timeout) as scraper_client:
            for q in queries:
                # Attempt 1: Internal Twitter GraphQL endpoint if authenticated or guest token available
                graphql_success = False
                clean_kw = re.sub(r"site:x\.com\S*|when:\S*", "", q).strip(' ()"')
                if clean_kw and scraper_client.session_pool.has_authenticated_accounts:
                    try:
                        (
                            headers,
                            cookies,
                            _,
                        ) = await scraper_client.session_pool.prepare_request(
                            scraper_client.raw_client
                        )
                        query_id = TWITTER_GRAPHQL_QUERY_IDS["SearchTimeline"]
                        url = f"https://x.com/i/api/graphql/{query_id}/SearchTimeline"
                        variables = build_search_variables(clean_kw, count=fetch_limit)
                        params = {
                            "variables": json.dumps(variables),
                            "features": json.dumps(TWITTER_FEATURES),
                        }
                        resp = await scraper_client.request(
                            method="GET",
                            url=url,
                            headers=headers,
                            cookies=cookies,
                            params=params,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            tweets = (
                                TwitterGraphQLExtractor.extract_tweets_from_timeline(
                                    data
                                )
                            )
                            for tweet in tweets:
                                if tweet.created_at < cutoff:
                                    continue
                                if tweet.url in seen_links:
                                    continue
                                seen_links.add(tweet.url)
                                raw_entries.append(
                                    {
                                        "_is_graphql_tweet": True,
                                        "_tweet_model": tweet,
                                        "query": q,
                                    }
                                )
                            if tweets:
                                graphql_success = True
                                logger.info(
                                    f"Extracted {len(tweets)} tweets via Twitter GraphQL API for [{clean_kw}]"
                                )
                    except Exception as e:
                        logger.debug(
                            f"Direct Twitter GraphQL failed for [{clean_kw}]: {e}"
                        )

                # Attempt 2: High-recall syndication search bridge if GraphQL returned empty or unauthenticated
                if not graphql_success:
                    try:
                        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en"
                        resp = await scraper_client.raw_client.get(url)
                        if resp.status_code != 200:
                            logger.warning(
                                f"Twitter/X query [{q[:35]}] returned HTTP {resp.status_code}"
                            )
                            continue

                        feed = feedparser.parse(resp.text)
                        if not feed.entries:
                            continue

                        for entry_item in feed.entries[:fetch_limit]:
                            link = str(entry_item.get("link", ""))
                            if not link or link in seen_links:
                                continue
                            seen_links.add(link)

                            title_raw = str(entry_item.get("title", ""))
                            clean_title = re.sub(
                                r"\s*-\s*X$", "", title_raw, flags=re.IGNORECASE
                            ).strip()
                            clean_title = html.unescape(clean_title)

                            pub_parsed = entry_item.get("published_parsed")
                            if pub_parsed:
                                dt = datetime(
                                    pub_parsed[0],
                                    pub_parsed[1],
                                    pub_parsed[2],
                                    pub_parsed[3],
                                    pub_parsed[4],
                                    pub_parsed[5],
                                    tzinfo=UTC,
                                )
                                if dt < cutoff:
                                    continue
                            else:
                                dt = datetime.now(UTC)

                            summary_raw = str(entry_item.get("summary", "")).strip()
                            clean_summary = re.sub(r"<[^>]+>", " ", summary_raw).strip()
                            clean_summary = html.unescape(clean_summary)

                            author = "X / Twitter"
                            handle_match = re.search(r"@([A-Za-z0-9_]+)", clean_title)
                            if handle_match:
                                author = f"@{handle_match.group(1)}"
                            else:
                                q_handle_match = re.search(
                                    r"site:x\.com/([A-Za-z0-9_]+)", q
                                )
                                if q_handle_match:
                                    author = f"@{q_handle_match.group(1)}"

                            raw_entries.append(
                                {
                                    "_is_graphql_tweet": False,
                                    "id": uuid4().hex[:10],
                                    "title": clean_title,
                                    "url": link,
                                    "summary": clean_summary,
                                    "published_at": dt,
                                    "author": author,
                                    "query": q,
                                }
                            )

                    except Exception as e:
                        logger.warning(
                            f"Error fetching Twitter/X query [{q[:35]}]: {e}"
                        )

        return raw_entries

    def _parse_entry(self, raw: dict[str, Any]) -> Entry:
        """Parse raw dictionary or normalized Tweet model into a domain Entry."""
        if raw.get("_is_graphql_tweet") and isinstance(raw.get("_tweet_model"), Tweet):
            tweet: Tweet = raw["_tweet_model"]
            query_ctx = raw.get("query", "")
            title = tweet.text.split("\n")[0][:180].strip() or "Untitled Tweet"

            summary_lines = [
                f"Source: Twitter/X | Author: {tweet.author.handle} ({tweet.author.name})",
                "",
                tweet.text,
            ]
            if tweet.metrics.favorite_count or tweet.metrics.retweet_count:
                summary_lines.append("")
                summary_lines.append(
                    f"Engagement: ❤️ {tweet.metrics.favorite_count} | 🔁 {tweet.metrics.retweet_count} | 💬 {tweet.metrics.reply_count}"
                )
            full_content = "\n".join(summary_lines)

            category = Category.AI_TECH
            if self.source and self.source.category:
                try:
                    category = Category(self.source.category)
                except ValueError:
                    pass

            text_lower = tweet.text.lower()
            if any(
                w in text_lower
                for w in ("arxiv", "paper", "research", "benchmark", "breakthrough")
            ):
                category = Category.AI_RESEARCH
            elif any(
                w in text_lower
                for w in (
                    "weights",
                    "model",
                    "deepseek",
                    "claude",
                    "llama",
                    "qwen",
                    "gpt",
                )
            ):
                category = Category.AI_MODELS
            elif any(
                w in text_lower
                for w in ("vllm", "ollama", "sglang", "framework", "agent", "github")
            ):
                category = Category.CYBER_TOOLS

            metadata = {
                "source_name": self.source.name
                if self.source
                else "Twitter/X Intelligence",
                "author": tweet.author.handle,
                "author_name": tweet.author.name,
                "query": query_ctx,
                "provenance_type": "tweet",
                "source_type": SourceType.TWITTER_X.value,
                "metrics": tweet.metrics.model_dump(),
                "tags": ["twitter", "x", "social_intelligence", "ai_ecosystem"],
            }

            return Entry(
                source_id=self.source.id,
                title=title,
                url=tweet.url or f"https://x.com/i/web/status/{tweet.id}",
                summary=full_content[:2000],
                content_hash=str(ContentHash.from_content(f"{title}\n{full_content}")),
                category=category,
                published_at=tweet.created_at,
                metadata=metadata,
            )

        # Standard syndication fallback
        title = raw.get("title", "Untitled Tweet").strip()
        url = raw.get("url", "")
        author = raw.get("author", "X / Twitter")
        summary_text = raw.get("summary", "")
        published_at = raw.get("published_at") or datetime.now(UTC)

        content_lines = [
            f"Source: Twitter/X | Author: {author}",
            "",
            title,
        ]
        if summary_text and summary_text != title:
            content_lines.append("")
            content_lines.append(summary_text)

        full_content = "\n".join(content_lines)

        category = Category.AI_TECH
        if self.source and self.source.category:
            try:
                category = Category(self.source.category)
            except ValueError:
                pass

        title_lower = title.lower()
        if any(
            w in title_lower
            for w in ("arxiv", "paper", "research", "benchmark", "breakthrough")
        ):
            category = Category.AI_RESEARCH
        elif any(
            w in title_lower
            for w in ("weights", "model", "deepseek", "claude", "llama", "qwen", "gpt")
        ):
            category = Category.AI_MODELS
        elif any(
            w in title_lower
            for w in ("vllm", "ollama", "sglang", "framework", "agent", "github")
        ):
            category = Category.CYBER_TOOLS

        metadata = {
            "source_name": self.source.name
            if self.source
            else "Twitter/X Intelligence",
            "author": author,
            "query": raw.get("query", ""),
            "provenance_type": "tweet",
            "source_type": SourceType.TWITTER_X.value,
            "tags": ["twitter", "x", "social_intelligence", "ai_ecosystem"],
        }

        return Entry(
            source_id=self.source.id,
            title=title,
            url=url,
            summary=full_content[:2000],
            content_hash=str(ContentHash.from_content(f"{title}\n{full_content}")),
            category=category,
            published_at=published_at,
            metadata=metadata,
        )


fetcher_registry.register("twitter_x", TwitterXFetcher)
