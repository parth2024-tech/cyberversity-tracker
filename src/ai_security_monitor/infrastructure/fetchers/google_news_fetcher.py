"""
Google News RSS search fetcher.
Key-less real-time worldwide news scraper for AI ecosystem queries.
Inspired by Horizon's Google News RSS search scraper.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta
from typing import Any

import feedparser
import httpx

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry, SourceType
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)

logger = get_logger(__name__)

DEFAULT_AI_QUERIES = [
    "artificial intelligence",
    "DeepSeek OR Qwen OR Mistral OR Llama",
    "vLLM OR Ollama OR SGLang OR llama.cpp",
    "reasoning models OR test-time compute",
]


class GoogleNewsFetcher(BaseFetcher):
    """Fetcher for Google News RSS search endpoints across AI ecosystem topics."""

    BASE_URL = "https://news.google.com/rss/search"

    @property
    def fetcher_type(self) -> str:
        return "google_news"

    async def _fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch news from Google News RSS search endpoints."""
        queries = (
            self.source.config.get("queries")
            if self.source and self.source.config
            else None
        )
        if not queries:
            single_q = self.source.query if self.source and self.source.query else None
            queries = [single_q] if single_q else DEFAULT_AI_QUERIES

        max_age_days = getattr(settings.database, "max_ingest_age_days", 14)
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        max_results_per_query = int(
            self.source.config.get("max_results_per_query", 15)
            if self.source and self.source.config
            else 15
        )

        language = str(
            self.source.config.get("language", "en")
            if self.source and self.source.config
            else "en"
        )
        country = str(
            self.source.config.get("country", "US")
            if self.source and self.source.config
            else "US"
        )
        ceid = f"{country}:{language}"

        raw_entries: list[dict[str, Any]] = []
        seen_links: set[str] = set()

        # Google News operator for recency within 14 days
        time_operator = f"when:{max_age_days}d"

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": settings.fetch.user_agent},
            follow_redirects=True,
        ) as client:
            for q in queries:
                full_query = f"{q.strip()} {time_operator}"
                params = {
                    "q": full_query,
                    "hl": language,
                    "gl": country,
                    "ceid": ceid,
                }
                try:
                    resp = await client.get(self.BASE_URL, params=params)
                    if resp.status_code != 200:
                        logger.warning(
                            f"Google News search for '{q}' returned status {resp.status_code}"
                        )
                        continue

                    feed = feedparser.parse(resp.text)
                    count = 0
                    for item in feed.entries:
                        link = item.get("link", "").strip()
                        if not link or link in seen_links:
                            continue

                        # Check published date
                        pub_dt = self._parse_pub_date(item)
                        if pub_dt and pub_dt < cutoff:
                            continue

                        seen_links.add(link)
                        raw_entries.append(
                            {
                                "title": item.get("title", ""),
                                "link": link,
                                "summary": item.get("summary", ""),
                                "published_at": pub_dt or datetime.now(UTC),
                                "source_title": (
                                    item.get("source", {}).get("title")
                                    if isinstance(item.get("source"), dict)
                                    else ""
                                ),
                                "_query": q,
                            }
                        )
                        count += 1
                        if count >= max_results_per_query:
                            break

                except Exception as e:
                    logger.warning(f"Error fetching Google News for query '{q}': {e}")

        return raw_entries

    def _parse_pub_date(self, entry: Any) -> datetime | None:
        """Parse feedparser published date into UTC datetime."""
        published_parsed = getattr(entry, "published_parsed", None)
        if published_parsed:
            try:
                ts = calendar.timegm(published_parsed)
                return datetime.fromtimestamp(ts, tz=UTC)
            except Exception:
                pass
        return None

    def _parse_entry(self, raw: dict[str, Any]) -> Entry:
        """Parse raw Google News item into domain Entry."""
        raw_title = raw.get("title", "Untitled News").strip()
        publisher = raw.get("source_title", "")
        clean_title = raw_title

        # Clean publisher suffix: "Headline - Publisher"
        if publisher and raw_title.endswith(f" - {publisher}"):
            clean_title = raw_title[: -len(f" - {publisher}")].strip()
        elif " - " in raw_title:
            parts = raw_title.rsplit(" - ", 1)
            clean_title = parts[0].strip()
            if not publisher:
                publisher = parts[1].strip()

        link = raw.get("link", "")
        summary_raw = raw.get("summary", "")
        published_at = raw.get("published_at", datetime.now(UTC))
        query = raw.get("_query", "AI Ecosystem")

        clean_summary = summary_raw.replace("<p>", "").replace("</p>", "").strip()
        if not clean_summary:
            clean_summary = (
                f"{clean_title} (Reported by {publisher or 'News Corridor'})"
            )

        metadata = {
            "source_name": f"Google News ({publisher or 'Global Wire'})",
            "publisher": publisher,
            "query": query,
            "source_type": SourceType.GOOGLE_NEWS.value,
        }

        # Classify based on query/title
        category = Category.AI_TECH
        t_low = clean_title.lower()
        if any(
            k in t_low
            for k in (
                "deepseek",
                "qwen",
                "llama",
                "mistral",
                "claude",
                "gpt",
                "model",
                "weights",
            )
        ):
            category = Category.AI_MODELS
        elif any(
            k in t_low
            for k in (
                "vllm",
                "ollama",
                "sglang",
                "runtime",
                "infra",
                "gpu",
                "chip",
                "nvidia",
            )
        ):
            category = Category.CYBER_TOOLS
        elif any(
            k in t_low
            for k in ("research", "paper", "arxiv", "reasoning", "benchmark", "compute")
        ):
            category = Category.AI_RESEARCH

        return Entry(
            source_id=self.source.id,
            title=clean_title,
            url=link,
            summary=clean_summary[:1200],
            content_hash=str(ContentHash.from_content(f"{clean_title}\n{link}")),
            category=category,
            published_at=published_at,
            metadata=metadata,
        )


fetcher_registry.register("google_news", GoogleNewsFetcher)
