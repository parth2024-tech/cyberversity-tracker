# arXiv API fetcher implementation.

from datetime import datetime

import feedparser
import httpx

from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import Entry
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)


class ArxivFetcher(BaseFetcher):
    """Fetcher for arXiv API."""

    @property
    def fetcher_type(self) -> str:
        return "arxiv"

    async def _fetch_raw(self) -> list[dict]:
        """Fetch from arXiv API."""
        query = self.source.query or "cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.CV"
        url = "http://export.arxiv.org/api/query"
        params = {
            "search_query": query,
            "start": 0,
            "max_results": 100,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": settings.fetch.user_agent},
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

        feed = feedparser.parse(response.content)
        entries = []

        for item in feed.entries:
            # Extract content
            content = getattr(item, "summary", "")
            content = self._clean_html(content)

            # Get published date
            published_at = datetime.utcnow()
            if hasattr(item, "published_parsed") and item.published_parsed:
                published_at = datetime(*item.published_parsed[:6])

            # Authors
            authors = [author.name for author in getattr(item, "authors", [])]

            entries.append({
                "title": getattr(item, "title", "Untitled").replace("\n", " ").strip(),
                "url": getattr(item, "link", ""),
                "content": content,
                "published_at": published_at,
                "tags": [tag.term for tag in getattr(item, "tags", [])] + ["arxiv"],
                "metadata": {
                    "authors": authors,
                    "arxiv_id": getattr(item, "id", "").split("/")[-1],
                    "categories": [tag.term for tag in getattr(item, "tags", [])],
                }
            })

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
        import re
        text = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&nbsp;", " ").replace("&", "&").replace("<", "<").replace(">", ">")
        text = re.sub(r"\s+", " ", text).strip()
        return text


fetcher_registry.register("arxiv", ArxivFetcher)
