"""arXiv feed fetcher with strict rate limiting and RSS fallback.

Architecture notes:
- The class-level _lock only protects the 3-second pacing sleep, NOT the
  full HTTP request. Previously, holding the lock during the HTTP call
  caused a queue of 14 fetchers to wait 3×13 = 39s before the last one
  even started its HTTP request, causing them all to exceed the global
  25-second per-source timeout in fetch_all(). Now the HTTP call runs
  outside the lock so all 14 regional sources complete within the timeout.
- Per-source timeout is set to 30s internally; the monitor_service timeout
  for arxiv sources is extended to 90s to handle queuing.
"""

import asyncio
import re
import time
from datetime import UTC, datetime

import feedparser
import httpx

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)

logger = get_logger(__name__)

# Maps query keywords to the best arXiv RSS category for fallback
_RSS_CATEGORY_MAP = (
    ("cs.RO", "cs.RO"),
    ("cs.CV", "cs.CV"),
    ("cs.CL", "cs.CL"),
    ("cs.LG", "cs.LG"),
    ("stat.ML", "cs.LG"),
    ("cs.CR", "cs.AI"),
)


class ArxivFetcher(BaseFetcher):
    """Fetcher for arXiv API with rate limiting and RSS fallback."""

    # Class-level pacing state — only guards the 3-second sleep, not the HTTP call
    _lock: asyncio.Lock = asyncio.Lock()
    _last_request_time: float = 0.0

    @property
    def fetcher_type(self) -> str:
        return "arxiv"

    async def _fetch_raw(self) -> list[dict]:
        """Fetch from arXiv API with strict rate limiting and fallback to RSS.

        The lock is held only for the pacing sleep (3s). The HTTP request
        itself runs outside the lock so other arXiv fetchers can acquire
        the lock and start their pacing window while the previous HTTP
        request is still in-flight. This reduces head-of-line blocking
        from O(n × 3s) to O(3s) amortised.
        """
        max_results = 25
        if self.source.config and isinstance(self.source.config, dict):
            max_results = min(int(self.source.config.get("max_results", 25)), 35)

        query = self.source.query or "cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.CV"
        url = "https://export.arxiv.org/api/query"
        params = {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        # ── Pacing: hold lock only for the sleep ───────────────────────────
        async with ArxivFetcher._lock:
            elapsed = time.time() - ArxivFetcher._last_request_time
            if elapsed < 3.0:
                await asyncio.sleep(3.0 - elapsed)
            ArxivFetcher._last_request_time = time.time()
        # Lock released — HTTP request runs concurrently with next fetcher's pacing

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "User-Agent": (
                        "AetherGuard-AI-Monitor/2.0 "
                        "(mailto:research@aetherguard.ai; "
                        "https://github.com/your-org/ai-security-monitor)"
                    )
                },
                follow_redirects=True,
            ) as client:
                response = await client.get(url, params=params)
                if response.status_code == 200 and len(response.content) > 100:
                    feed = feedparser.parse(response.content)
                    if feed.entries:
                        logger.debug(
                            f"arXiv API returned {len(feed.entries)} papers "
                            f"for {self.source.name!r}"
                        )
                        return self._parse_feed_items(feed.entries)
                elif response.status_code == 429:
                    logger.warning(
                        f"arXiv API rate limit 429 for {self.source.name!r}. "
                        "Falling back to arXiv RSS."
                    )
        except Exception as api_err:
            logger.warning(
                f"arXiv API query failed for {self.source.name!r}: {api_err}. "
                "Falling back to RSS."
            )

        # Fallback to arXiv RSS
        return await self._fetch_raw_rss(query)

    async def _fetch_raw_rss(self, query: str) -> list[dict]:
        """Fallback to official arXiv RSS feeds when export API throttles or times out."""
        cat = "cs.AI"
        for keyword, rss_cat in _RSS_CATEGORY_MAP:
            if keyword in query:
                cat = rss_cat
                break

        rss_url = f"https://rss.arxiv.org/rss/{cat}"
        headers = {
            "User-Agent": (
                "AetherGuard-AI-Monitor/2.0 (mailto:research@aetherguard.ai)"
            )
        }

        try:
            async with httpx.AsyncClient(
                timeout=20.0, headers=headers, follow_redirects=True
            ) as client:
                res = await client.get(rss_url)
                if res.status_code == 200:
                    feed = feedparser.parse(res.content)
                    if feed.entries:
                        logger.info(
                            f"arXiv RSS fallback ({cat}): retrieved "
                            f"{len(feed.entries)} papers for {self.source.name!r}"
                        )
                        return self._parse_feed_items(feed.entries[:30])
        except Exception as rss_err:
            logger.error(
                f"arXiv RSS fallback failed for {self.source.name!r}: {rss_err}"
            )

        return []

    def _parse_feed_items(self, feed_entries: list) -> list[dict]:
        entries = []
        for item in feed_entries:
            content = self._clean_html(getattr(item, "summary", ""))

            published_at = datetime.now(UTC)
            if hasattr(item, "published_parsed") and item.published_parsed:
                try:
                    published_at = datetime(*item.published_parsed[:6], tzinfo=UTC)
                except Exception:
                    pass
            elif hasattr(item, "updated_parsed") and item.updated_parsed:
                try:
                    published_at = datetime(*item.updated_parsed[:6], tzinfo=UTC)
                except Exception:
                    pass

            authors = [a.name for a in getattr(item, "authors", [])]

            raw_title = getattr(item, "title", "Untitled").replace("\n", " ").strip()
            # Strip arXiv announce-type prefixes from RSS feeds
            clean_title = re.sub(
                r"^(?:arXiv:\S+\s+)?(?:Announce Type:\s*\w+\s*)?(?:Title:\s*)?",
                "",
                raw_title,
                flags=re.I,
            ).strip()

            entries.append(
                {
                    "title": clean_title or raw_title,
                    "url": getattr(item, "link", ""),
                    "content": content,
                    "published_at": published_at,
                    "tags": [tag.term for tag in getattr(item, "tags", [])]
                    + ["arxiv", "research"],
                    "metadata": {
                        "authors": authors,
                        "arxiv_id": getattr(item, "id", "").split("/")[-1],
                        "categories": [tag.term for tag in getattr(item, "tags", [])],
                    },
                }
            )
        return entries

    def _parse_entry(self, raw: dict) -> Entry:
        content_hash = ContentHash.from_content(
            raw["title"],
            raw["url"],
            str(raw["published_at"]),
        )

        return Entry(
            source_id=self.source.id,
            title=raw["title"],
            url=raw["url"],
            content_hash=str(content_hash),
            summary=raw["content"][:500] if raw["content"] else "",
            published_at=raw["published_at"],
            category=self.source.category,
            tags=raw.get("tags", []),
            metadata=raw.get("metadata", {}),
        )

    def _clean_html(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = (
            text.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
        )
        text = re.sub(r"\s+", " ", text).strip()
        return text


fetcher_registry.register("arxiv", ArxivFetcher)
