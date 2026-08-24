# RSS/Atom feed fetcher implementation.

from typing import Optional
import feedparser
import httpx
from datetime import datetime
from uuid import UUID

from ai_security_monitor.domain.entities import Entry, Source, Category, SourceType
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import BaseFetcher, fetcher_registry
from ai_security_monitor.config.settings import settings


class RSSFetcher(BaseFetcher):
    """Fetcher for RSS/Atom feeds."""

    @property
    def fetcher_type(self) -> str:
        return "rss"

    async def _fetch_raw(self) -> list[dict]:
        """Fetch and parse RSS/Atom feed."""
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": settings.fetch.user_agent},
        ) as client:
            response = await client.get(self.source.url)
            response.raise_for_status()

        # Parse with feedparser
        feed = feedparser.parse(response.content)

        if feed.bozo and feed.bozo_exception:
            # Log but continue - feedparser can handle many malformed feeds
            print(f"Feed parse warning for {self.source.name}: {feed.bozo_exception}")

        entries = []
        for item in feed.entries:
            # Extract content
            content = ""
            if hasattr(item, "content") and item.content:
                content = item.content[0].value
            elif hasattr(item, "summary"):
                content = item.summary
            elif hasattr(item, "description"):
                content = item.description

            # Clean HTML
            content = self._clean_html(content)

            # Get published date
            published_at = datetime.utcnow()
            if hasattr(item, "published_parsed") and item.published_parsed:
                published_at = datetime(*item.published_parsed[:6])
            elif hasattr(item, "updated_parsed") and item.updated_parsed:
                published_at = datetime(*item.updated_parsed[:6])

            entries.append({
                "title": getattr(item, "title", "Untitled"),
                "url": getattr(item, "link", ""),
                "content": content,
                "published_at": published_at,
                "tags": [tag.term for tag in getattr(item, "tags", [])],
                "metadata": {
                    "feed_title": feed.feed.get("title", ""),
                    "feed_link": feed.feed.get("link", ""),
                }
            })

        return entries

    def _parse_entry(self, raw: dict) -> Entry:
        """Parse raw entry into Entry entity."""
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
        """Basic HTML cleaning."""
        if not text:
            return ""

        import re
        # Remove scripts and styles
        text = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # Decode common entities
        text = text.replace("&nbsp;", " ").replace("&", "&").replace("<", "<").replace(">", ">")
        text = text.replace("&ldquo;", '"').replace("&rdquo;", '"').replace("\u2018", "'").replace("\u2019", "'")
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text


# Register the fetcher
fetcher_registry.register("rss", RSSFetcher)
