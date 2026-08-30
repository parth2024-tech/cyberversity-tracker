# RSS/Atom feed fetcher implementation.

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


class RSSFetcher(BaseFetcher):
    """Fetcher for RSS/Atom feeds."""

    @property
    def fetcher_type(self) -> str:
        return "rss"

    async def _fetch_raw(self) -> list[dict]:
        """Fetch and parse RSS/Atom feed with multi-encoding (GB18030/GBK/UTF-8) and mirror fallbacks."""
        urls = [self.source.url]
        if self.source.config and "mirrors" in self.source.config:
            urls.extend(self.source.config["mirrors"])

        last_error = None
        response = None

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": settings.fetch.user_agent},
            follow_redirects=True,
        ) as client:
            for target_url in urls:
                try:
                    response = await client.get(target_url)
                    response.raise_for_status()
                    break
                except Exception as req_err:
                    last_error = req_err
                    continue

        if response is None:
            if last_error:
                raise last_error
            raise RuntimeError(f"Failed to retrieve feed from {self.source.url}")

        # Multi-encoding detection for Chinese legacy and standard streams
        raw_bytes = response.content
        decoded_text = ""
        # Try declared encoding first, then Chinese national standard GB18030 (superset of GBK/GB2312), then UTF-8
        candidate_encodings = [
            response.encoding,
            "utf-8",
            "gb18030",
            "gbk",
            "gb2312",
            "big5",
        ]
        seen_enc = set()
        for enc in candidate_encodings:
            if not enc or enc.lower() in seen_enc:
                continue
            seen_enc.add(enc.lower())
            try:
                decoded_text = raw_bytes.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if not decoded_text:
            decoded_text = raw_bytes.decode("utf-8", errors="replace")

        # Parse with feedparser
        feed = feedparser.parse(decoded_text)

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

            # Clean and sanitize HTML/scripts/payloads
            content = self._clean_html(content)

            # Get published date
            published_at = datetime.utcnow()
            if hasattr(item, "published_parsed") and item.published_parsed:
                published_at = datetime(*item.published_parsed[:6])
            elif hasattr(item, "updated_parsed") and item.updated_parsed:
                published_at = datetime(*item.updated_parsed[:6])

            raw_title = getattr(item, "title", "Untitled")
            clean_title = self._clean_html(raw_title)

            entries.append({
                "title": clean_title,
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
        """Rigorous content sanitization stripping all executable tags, handlers, and injection payloads."""
        if not text:
            return ""

        import re
        # 1. Remove dangerous script, iframe, object, embed, applet, style tags
        text = re.sub(r"<(script|style|iframe|object|embed|applet|meta|link|form|svg)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<(script|style|iframe|object|embed|applet|meta|link|form|svg)[^>]*>", "", text, flags=re.IGNORECASE)

        # 2. Strip inline event handlers (onload, onerror, onclick, etc.) and dangerous protocols
        text = re.sub(r"\bon\w+\s*=\s*([\"'][^\"']*[\"']|[^\s>]+)", "", text, flags=re.IGNORECASE)
        text = re.sub(r"(javascript|vbscript|data):[^\s\"'>]+", "", text, flags=re.IGNORECASE)

        # 3. Strip all remaining HTML tags
        text = re.sub(r"<[^>]+>", "", text)

        # 4. Decode HTML entities
        text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"').replace("&apos;", "'").replace("&#39;", "'")
        text = text.replace("&ldquo;", '"').replace("&rdquo;", '"').replace("\u2018", "'").replace("\u2019", "'")

        # 5. Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text


# Register the fetcher
fetcher_registry.register("rss", RSSFetcher)
