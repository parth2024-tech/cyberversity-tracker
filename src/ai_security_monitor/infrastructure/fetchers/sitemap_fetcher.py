"""
XML Sitemap and Google News Sitemap Fetcher.
Provides dual-channel ingestion alongside RSS/Atom feeds to recover articles
dropped by shallow RSS feed windows.
Enforces 14-day freshness guard and HTTP conditional requests (ETag / If-Modified-Since).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx
from defusedxml import ElementTree

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)

logger = get_logger(__name__)

# Common XML Namespaces for Sitemaps
SITEMAP_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}


def _parse_iso_or_rfc(date_str: str) -> datetime:
    """Parse ISO-8601 or RFC date string into UTC datetime."""
    if not date_str:
        return datetime.now(UTC)
    date_str = date_str.strip()
    try:
        # Handle trailing Z or timezone offsets
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        pass

    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return datetime.now(UTC)


def _title_from_url(url: str) -> str:
    """Infer a human-readable title from URL slug when title tag is absent."""
    parts = [p for p in url.split("/") if p]
    if parts:
        slug = parts[-1].split(".")[0].split("?")[0]
        words = re.sub(r"[-_]", " ", slug).split()
        if words:
            return " ".join(words).title()
    return "Intelligence Article"


class SitemapFetcher(BaseFetcher):
    """High-recall XML Sitemap and Google News Sitemap fetcher.

    Supports:
    - Standard /sitemap.xml with <lastmod> delta filtering
    - Google News /news-sitemap.xml with <news:news> tags
    - HTTP conditional requests (ETag / If-Modified-Since) returning HTTP 304
    - Strict 14-day freshness enforcement
    """

    @property
    def fetcher_type(self) -> str:
        return "sitemap"

    async def _fetch_raw(self) -> list[dict]:
        """Fetch and parse XML sitemap with freshness guard."""
        if not self.source.url:
            return []

        stealth_headers = {
            "User-Agent": (
                "Mozilla/5.0 (X-UA-Compatible; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
            ),
            "Accept": "application/xml,text/xml,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # HTTP Conditional Request Handshake
        source_cfg = self.source.config or {}
        etag = source_cfg.get("etag")
        last_modified = source_cfg.get("last_modified")

        if etag:
            stealth_headers["If-None-Match"] = str(etag)
        if last_modified:
            stealth_headers["If-Modified-Since"] = str(last_modified)

        response: httpx.Response | None = None
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers=stealth_headers,
            follow_redirects=True,
        ) as client:
            try:
                resp = await client.get(self.source.url)
                if resp.status_code == 304:
                    logger.info(
                        f"Sitemap {self.source.name!r} returned HTTP 304 Not Modified. "
                        "Sitemap unchanged; zero payload parsed."
                    )
                    return []
                resp.raise_for_status()
                response = resp
            except Exception as e:
                logger.warning(f"Failed to fetch sitemap from {self.source.url}: {e}")
                raise

        if not response or not response.content:
            return []

        # Persist ETag & Last-Modified for future conditional polls
        if self.source.config is None:
            self.source.config = {}
        new_etag = response.headers.get("etag")
        new_lm = response.headers.get("last-modified")
        if new_etag:
            self.source.config["etag"] = new_etag
        if new_lm:
            self.source.config["last_modified"] = new_lm

        raw_xml = response.content
        return self._parse_sitemap_xml(raw_xml)

    def _parse_sitemap_xml(self, raw_xml: bytes) -> list[dict]:
        """Parse XML bytes into entry dictionaries with 14-day freshness filtering."""
        try:
            root = ElementTree.fromstring(raw_xml)
        except Exception as parse_err:
            logger.warning(
                f"XML parse error for sitemap {self.source.name!r}: {parse_err}"
            )
            return []

        entries: list[dict] = []
        cutoff = datetime.now(UTC) - timedelta(days=14)

        # Match all <url> elements regardless of namespace prefix
        for url_elem in root.iter():
            tag = url_elem.tag.lower()
            if not tag.endswith("url"):
                continue

            loc_str = ""
            lastmod_str = ""
            news_title = ""
            news_pub_date = ""

            for child in url_elem:
                child_tag = child.tag.lower()
                if child_tag.endswith("loc") and child.text:
                    loc_str = child.text.strip()
                elif child_tag.endswith("lastmod") and child.text:
                    lastmod_str = child.text.strip()
                elif child_tag.endswith("news"):
                    for news_child in child:
                        nc_tag = news_child.tag.lower()
                        if nc_tag.endswith("title") and news_child.text:
                            news_title = news_child.text.strip()
                        elif nc_tag.endswith("publication_date") and news_child.text:
                            news_pub_date = news_child.text.strip()

            if not loc_str or not loc_str.startswith("http"):
                continue

            # Determine publication timestamp
            pub_date_raw = news_pub_date or lastmod_str
            pub_dt = _parse_iso_or_rfc(pub_date_raw)

            # Strict 14-Day Ingestion Freshness Guard
            if pub_dt < cutoff:
                continue

            title = news_title or _title_from_url(loc_str)

            entries.append(
                {
                    "title": title,
                    "url": loc_str,
                    "published_at": pub_dt,
                    "summary": f"Sitemap intelligence entry from {self.source.name}",
                    "tags": ["sitemap", "ai_ecosystem"],
                    "metadata": {
                        "channel": "sitemap",
                        "sitemap_url": self.source.url,
                        "region": (self.source.config or {}).get("region", "global"),
                        "country": (self.source.config or {}).get("country", "GLOBAL"),
                        "provenance_type": (self.source.config or {}).get(
                            "provenance_type", "sitemap_discovery"
                        ),
                    },
                }
            )

        logger.info(
            f"Parsed {len(entries)} fresh articles (<=14d) from sitemap {self.source.name!r}"
        )
        return entries

    def _parse_entry(self, raw: dict) -> Entry:
        """Parse raw entry dict into Entry domain entity."""
        title = raw.get("title") or "Untitled Sitemap Entry"
        url = raw.get("url") or (
            str(self.source.url)
            if self.source and self.source.url
            else "https://example.com"
        )
        pub_at = raw.get("published_at") or datetime.now(UTC)
        content_hash = ContentHash.from_content(
            title,
            url,
            str(pub_at),
        )
        summary = raw.get("summary") or title

        return Entry(
            source_id=self.source.id,
            title=title,
            url=url,
            content_hash=str(content_hash),
            summary=summary[:500],
            published_at=pub_at,
            category=self.source.category,
            tags=raw.get("tags", []),
            metadata=raw.get("metadata", {})
            if isinstance(raw.get("metadata"), dict)
            else {},
        )


# Register sitemap fetcher in global registry
fetcher_registry.register("sitemap", SitemapFetcher)
