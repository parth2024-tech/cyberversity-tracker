"""
Twitter/X fetcher for frontier AI models, research announcements, and developer tools.
Queries live breaking X/Twitter updates via dedicated high-recall news syndication.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

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

DEFAULT_AI_TWITTER_QUERIES = [
    'site:x.com ("arXiv" OR "benchmark" OR "reasoning model") AI when:14d',
    'site:x.com ("DeepSeek" OR "Claude" OR "OpenAI" OR "Qwen" OR "Llama") model when:14d',
    'site:x.com ("vLLM" OR "Ollama" OR "SGLang" OR "llama.cpp" OR "ComfyUI") when:14d',
    'site:x.com ("agent" OR "coding agent" OR "AI agent") framework when:14d',
]

DEFAULT_AI_TWITTER_HANDLES = [
    "_akhaliq",
    "deepseek_ai",
    "AnthropicAI",
    "OpenAI",
    "sama",
    "karpathy",
    "ylecun",
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
TWITTER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/xml,text/xml,text/plain,*/*",
}


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
        """Fetch matching tweets from Twitter / X syndication feeds."""
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

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers=TWITTER_HEADERS,
            follow_redirects=True,
        ) as client:
            for q in queries:
                try:
                    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en"
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        logger.warning(
                            f"Twitter/X query [{q[:35]}] returned HTTP {resp.status_code}"
                        )
                        continue

                    feed = feedparser.parse(resp.text)
                    if not feed.entries:
                        continue

                    for e in feed.entries[:fetch_limit]:
                        link = str(e.get("link", ""))
                        if not link or link in seen_links:
                            continue
                        seen_links.add(link)

                        title_raw = str(e.get("title", ""))
                        clean_title = re.sub(
                            r"\s*-\s*X$", "", title_raw, flags=re.IGNORECASE
                        ).strip()
                        clean_title = html.unescape(clean_title)

                        pub_parsed = e.get("published_parsed")
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

                        summary_raw = str(e.get("summary", "")).strip()
                        clean_summary = re.sub(r"<[^>]+>", " ", summary_raw).strip()
                        clean_summary = html.unescape(clean_summary)

                        # Extract any author handle from query or title
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
                    logger.warning(f"Error fetching Twitter/X query [{q[:35]}]: {e}")

        return raw_entries

    def _parse_entry(self, raw: dict[str, Any]) -> Entry:
        """Parse raw tweet dictionary into a domain Entry."""
        title = raw.get("title", "Untitled Tweet").strip()
        url = raw.get("url", "")
        author = raw.get("author", "X / Twitter")
        summary_text = raw.get("summary", "")
        published_at = raw.get("published_at") or datetime.now(UTC)

        # Build informative content text with provenance
        content_lines = [
            f"Source: Twitter/X | Author: {author}",
            "",
            title,
        ]
        if summary_text and summary_text != title:
            content_lines.append("")
            content_lines.append(summary_text)

        full_content = "\n".join(content_lines)

        # Categorization logic
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
