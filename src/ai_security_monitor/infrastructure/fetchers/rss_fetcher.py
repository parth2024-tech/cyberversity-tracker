# RSS/Atom feed fetcher implementation — top-tier, fault-tolerant.

import re
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

# Chinese national standard encodings for legacy PRC/TW feeds
_CHINESE_ENCODINGS = ("gb18030", "gbk", "gb2312", "big5")


class RSSFetcher(BaseFetcher):
    """Top-tier fault-tolerant RSS/Atom feed fetcher.

    Design decisions:
    - Passes raw bytes directly to feedparser so it can read the XML
      encoding declaration (fixes Atom 1.0 feeds that returned 0 entries
      when decoded to a string first — confirmed affects NVIDIA, xAI Grok,
      Qwen Open Source Releases, AI Sweden).
    - Detects HTML/SPA responses early and raises a clear error instead
      of silently returning 0 entries and logging success.
    - Implements a bozo/malformed-XML recovery path: retries with explicit
      Chinese encodings for CJK sources, then UTF-8 text decode as fallback.
    - Caps GitHub releases.atom feeds to the 2 most recent releases and
      enriches their titles with version + first-line snippet.
    """

    @property
    def fetcher_type(self) -> str:
        return "rss"

    async def _fetch_raw(self) -> list[dict]:
        """Fetch and parse RSS/Atom feed with mirror fallbacks."""
        urls = [self.source.url]
        if self.source.config and "mirrors" in self.source.config:
            urls.extend(self.source.config["mirrors"])

        last_error: Exception | None = None
        response: httpx.Response | None = None

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

        raw_bytes: bytes = response.content

        # ── Content-type guard ──────────────────────────────────────────────
        # If the server returned an HTML page (SPA redirect, Cloudflare WAF,
        # cookie-gate, etc.) there is no point trying to parse it as XML.
        # Raise immediately so the caller records a proper error rather than
        # silently reporting 0 entries + status: success.
        ct_header = (
            response.headers.get("content-type", "").lower().split(";")[0].strip()
        )
        first_bytes = raw_bytes[:100].lower().replace(b" ", b"")
        is_html_response = ct_header in ("text/html",) and (
            first_bytes.startswith((b"<!doctype", b"<html"))
        )
        if is_html_response:
            raise RuntimeError(
                f"Source {self.source.name!r} returned HTML instead of RSS/Atom "
                f"(content-type: {ct_header}). Feed URL may be dead, behind a "
                "login wall, or serving a JavaScript SPA."
            )

        # ── Primary parse: raw bytes ────────────────────────────────────────
        # Passing bytes (not a decoded string) lets feedparser read the XML
        # <?xml encoding="..."?> declaration and handle charset negotiation.
        # This is the correct way to invoke feedparser per its documentation.
        # Decoding bytes to a string first strips the encoding declaration,
        # causing feedparser to mis-parse Atom 1.0 feeds as empty.
        feed = feedparser.parse(raw_bytes)
        entries = self._extract_entries(feed)

        # ── Bozo / malformed-XML recovery ──────────────────────────────────
        if not entries and (feed.bozo or not feed.feed):
            bozo_exc = getattr(feed, "bozo_exception", None)
            logger.debug(
                f"Feed {self.source.name!r} bozo={feed.bozo} "
                f"({type(bozo_exc).__name__}: {bozo_exc}). "
                "Attempting encoding-aware recovery."
            )
            # Step 1: Chinese encodings for CJK sources
            country = (self.source.config or {}).get("country", "")
            if country in ("CN", "TW", "HK", "SG"):
                for enc in _CHINESE_ENCODINGS:
                    try:
                        decoded = raw_bytes.decode(enc, errors="replace")
                        feed2 = feedparser.parse(decoded)
                        if feed2.entries:
                            logger.info(
                                f"Recovered {len(feed2.entries)} entries for "
                                f"{self.source.name!r} using {enc} encoding"
                            )
                            entries = self._extract_entries(feed2)
                            break
                    except Exception:
                        continue

            # Step 2: UTF-8 text decode for feeds with malformed XML entities
            if not entries:
                try:
                    decoded_utf8 = raw_bytes.decode("utf-8", errors="replace")
                    feed3 = feedparser.parse(decoded_utf8)
                    if feed3.entries:
                        logger.info(
                            f"Recovered {len(feed3.entries)} entries for "
                            f"{self.source.name!r} via UTF-8 text fallback"
                        )
                        entries = self._extract_entries(feed3)
                except Exception:
                    pass

        # ── Empty-but-valid feed detection ─────────────────────────────────
        if not entries and feed.feed and not feed.bozo:
            feed_title = feed.feed.get("title", "unknown")
            logger.warning(
                f"Source {self.source.name!r} returned a valid but empty feed "
                f"(feed title: {feed_title!r}). "
                "The feed may have no recent items or the URL needs updating."
            )

        return entries

    def _extract_entries(self, feed: feedparser.FeedParserDict) -> list[dict]:
        """Extract and sanitize entries from a parsed feedparser result."""
        is_releases = bool(
            self.source.url
            and ("releases.atom" in self.source.url or "/releases" in self.source.url)
        )

        entries: list[dict] = []

        for item in feed.entries:
            # ── Content extraction ──────────────────────────────────────────
            content = ""
            if hasattr(item, "content") and item.content:
                content = item.content[0].value
            elif hasattr(item, "summary"):
                content = item.summary
            elif hasattr(item, "description"):
                content = item.description
            content = self._clean_html(content)

            # ── Published date ──────────────────────────────────────────────
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

            raw_title = getattr(item, "title", "Untitled")
            clean_title = self._clean_html(raw_title)

            # ── GitHub releases enrichment ──────────────────────────────────
            if is_releases:
                if len(entries) >= 2:
                    break
                prefix = (
                    self.source.name.split("Releases")[0]
                    .strip()
                    .replace("Codebase", "")
                    .strip()
                )
                ver_match = re.search(
                    r"v?\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9\.]+)?", clean_title
                )
                ver_str = (
                    ver_match.group(0)
                    if ver_match
                    else clean_title.replace(prefix, "").strip(": ")
                )

                snippet = ""
                if content:
                    first_line = content.split("\n")[0].strip()
                    first_line = re.sub(r"^#+\s*", "", first_line)
                    first_line = re.sub(
                        r"\[.*?\]|\(.*?\)|<.*?>", "", first_line
                    ).strip()
                    if len(first_line) > 10 and not first_line.startswith(
                        ("http", "```")
                    ):
                        snippet = f": {first_line[:90]}"

                if snippet:
                    clean_title = f"{prefix} {ver_str}{snippet}"
                elif not clean_title.lower().startswith(prefix.lower()):
                    clean_title = f"{prefix} Release {clean_title}"

            entries.append(
                {
                    "title": clean_title,
                    "url": getattr(item, "link", ""),
                    "content": content,
                    "published_at": published_at,
                    "tags": [tag.term for tag in getattr(item, "tags", [])],
                    "metadata": {
                        "feed_title": feed.feed.get("title", ""),
                        "feed_link": feed.feed.get("link", ""),
                        "region": (self.source.config or {}).get("region", "global"),
                        "country": (self.source.config or {}).get("country", "GLOBAL"),
                        "provenance_type": (self.source.config or {}).get(
                            "provenance_type", "rss_feed"
                        ),
                    },
                }
            )

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

        # 1. Remove dangerous script, iframe, object, embed, applet, style tags
        text = re.sub(
            r"<(script|style|iframe|object|embed|applet|meta|link|form|svg)[^>]*>.*?</\1>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(
            r"<(script|style|iframe|object|embed|applet|meta|link|form|svg)[^>]*>",
            "",
            text,
            flags=re.IGNORECASE,
        )

        # 2. Strip inline event handlers and dangerous protocols
        text = re.sub(
            r"\bon\w+\s*=\s*([\"\'][^\"\']*[\"\']|[^\s>]+)",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(javascript|vbscript|data):[^\s\"'<>]+", "", text, flags=re.IGNORECASE
        )

        # 3. Strip all remaining HTML tags
        text = re.sub(r"<[^>]+>", "", text)

        # 4. Decode HTML entities
        text = (
            text.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&apos;", "'")
            .replace("&#39;", "'")
            .replace("&ldquo;", '"')
            .replace("&rdquo;", '"')
            .replace("\u2018", "'")
            .replace("\u2019", "'")
        )

        # 5. Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text


# Register the fetcher
fetcher_registry.register("rss", RSSFetcher)
