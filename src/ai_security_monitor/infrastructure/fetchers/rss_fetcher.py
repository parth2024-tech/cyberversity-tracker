# RSS/Atom feed fetcher implementation — top-tier, fault-tolerant.

import asyncio
import json
import re
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any

import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as dt_parser

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.domain.exceptions import FetchNotModifiedError
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)
from ai_security_monitor.infrastructure.fetchers.curl_cffi_pool import curl_cffi_pool

logger = get_logger(__name__)

# Chinese national standard encodings for legacy PRC/TW feeds
_CHINESE_ENCODINGS = ("gb18030", "gbk", "gb2312", "big5")

# Core AI keywords regex for strict filtering when require_ai is enabled
_AI_RELEVANCE_RE = re.compile(
    r"\b(ai|artificial intelligence|llm|llms|agent|agents|model|models|gpt|claude|gemini|deepseek|qwen|llama|mistral|transformer|transformers|diffusion|rag|vllm|sglang|ollama|deep learning|machine learning|neural|multimodal|inference|reasoning|benchmark|evals?)\b",
    re.IGNORECASE,
)


class _DuckResponse:
    """Duck-typed response adapter wrapping curl_cffi or custom responses."""

    def __init__(
        self,
        status_code: int,
        content: bytes,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP request failed with status {self.status_code}")


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
        response: Any = None

        stealth_headers = {
            "User-Agent": (
                "Mozilla/5.0 (X-UA-Compatible; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
            ),
            "Accept": "application/atom+xml,application/rdf+xml,application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="133", "Google Chrome";v="133"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Linux"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
        }

        # HTTP Conditional Request Handshake (ETag / If-Modified-Since)
        source_cfg = self.source.config or {}
        etag = source_cfg.get("etag")
        last_modified = source_cfg.get("last_modified")

        if etag:
            stealth_headers["If-None-Match"] = str(etag)
        if last_modified:
            stealth_headers["If-Modified-Since"] = str(last_modified)

        async with httpx.AsyncClient(
            timeout=min(float(self.timeout), 20.0),
            headers=stealth_headers,
            follow_redirects=True,
        ) as client:
            for target_url in urls:
                try:
                    resp = await client.get(target_url)
                    if resp.status_code == 304:
                        stored_count = source_cfg.get("stored_entries_count")
                        # Defect Ledger D3: Stored validators outlive data (ETag lockout)
                        # When a source has < 3 entries stored, ignore 304, drop validators and refetch full payload.
                        if stored_count is not None and stored_count < 3:
                            logger.warning(
                                f"Source {self.source.name!r} returned HTTP 304 but only has {stored_count} stored entries. "
                                "Discarding stale ETag/Last-Modified validators and refetching full payload."
                            )
                            if self.source.config is not None:
                                self.source.config.pop("etag", None)
                                self.source.config.pop("last_modified", None)
                            # Remove conditional headers from client for unconditional refetch
                            for h_key in (
                                "if-none-match",
                                "if-modified-since",
                                "If-None-Match",
                                "If-Modified-Since",
                            ):
                                client.headers.pop(h_key, None)
                            refetch_resp = await client.get(target_url)
                            if refetch_resp.status_code == 200:
                                response = refetch_resp
                                break
                            resp = refetch_resp

                        if resp.status_code == 304:
                            logger.info(
                                f"Source {self.source.name!r} returned HTTP 304 Not Modified. "
                                "Feed unchanged; skipping body payload."
                            )
                            raise FetchNotModifiedError(self.source.name)
                    resp.raise_for_status()
                    response = resp
                    break
                except FetchNotModifiedError:
                    raise
                except Exception as req_err:
                    # Attempt TLS impersonation fallback via pooled curl_cffi for WAF / 403 / 429 challenges
                    status_code = getattr(
                        getattr(req_err, "response", None), "status_code", 0
                    )
                    if status_code in (403, 429, 503) or isinstance(
                        req_err, (httpx.ConnectError, httpx.ConnectTimeout)
                    ):
                        try:
                            # Pass only conditional cache headers (ETag, Last-Modified)
                            # Never pass manual User-Agent or Sec-Ch-* to prevent JA3 fingerprint mismatch
                            cond_headers: dict[str, str] = {}
                            source_cfg_dict = self.source.config or {}
                            etag_val = source_cfg_dict.get("etag")
                            lm_val = source_cfg_dict.get("last_modified")
                            if etag_val:
                                cond_headers["If-None-Match"] = str(etag_val)
                            if lm_val:
                                cond_headers["If-Modified-Since"] = str(lm_val)

                            curl_resp = await curl_cffi_pool.get(
                                target_url,
                                timeout=min(float(self.timeout), 20.0),
                                headers=cond_headers if cond_headers else None,
                            )
                            if curl_resp.status_code == 200:
                                logger.info(
                                    f"Bypassed WAF/403 block on {target_url} via Chrome TLS impersonation (Pooled)"
                                )
                                response = _DuckResponse(
                                    curl_resp.status_code,
                                    curl_resp.content,
                                    dict(curl_resp.headers),
                                )
                                break
                            elif curl_resp.status_code == 304:
                                raise FetchNotModifiedError(
                                    f"Feed not modified: {self.source.url}"
                                )
                        except FetchNotModifiedError:
                            raise
                        except Exception as curl_err:
                            logger.debug(
                                f"curl_cffi fallback failed for {target_url}: {curl_err}"
                            )

                    last_error = req_err
                    response = None
                    continue

        if response is None:
            if last_error:
                raise last_error
            raise RuntimeError(f"Failed to retrieve feed from {self.source.url}")

        # Persist ETag and Last-Modified for future conditional polls
        if self.source.config is None:
            self.source.config = {}
        new_etag = response.headers.get("etag")
        new_lm = response.headers.get("last-modified")
        if new_etag:
            self.source.config["etag"] = new_etag
        if new_lm:
            self.source.config["last_modified"] = new_lm

        raw_bytes: bytes = response.content
        if not raw_bytes or len(raw_bytes.strip()) == 0:
            raise RuntimeError(
                f"Source {self.source.name!r} returned an empty response body."
            )

        # ── Content-type guard & Adaptive Ingestion Mesh ────────────────────
        ct_header = (
            response.headers.get("content-type", "").lower().split(";")[0].strip()
        )
        first_bytes = raw_bytes[:100].lower().replace(b" ", b"")

        # ── JSON Feed / API endpoint support ────────────────────────────────
        is_json_response = ct_header in ("application/json", "text/json") or (
            first_bytes.startswith((b"{", b"["))
        )
        if is_json_response:
            try:
                parsed_json = json.loads(raw_bytes.decode("utf-8", errors="replace"))
                json_entries = self._extract_json_entries(
                    parsed_json, response.headers.get("url", self.source.url)
                )
                if json_entries:
                    logger.info(
                        f"Extracted {len(json_entries)} entries from JSON API for {self.source.name!r}"
                    )
                    return json_entries
            except Exception as json_err:
                logger.debug(f"JSON parsing failed for {self.source.name!r}: {json_err}")

        # ── HTML Portal / SPA Auto-Discovery and DOM Extractor Fallback ─────
        is_html_response = ct_header in ("text/html", "application/xhtml+xml") or (
            first_bytes.startswith((b"<!doctype", b"<html"))
        )
        if is_html_response:
            # 1. Attempt Auto-Discovery of live RSS/Atom feed from HTML <head> off-thread
            try:
                feed_link_href = await asyncio.to_thread(
                    self._sync_find_feed_link_in_head, raw_bytes[:16384]
                )
                if feed_link_href:
                    discovered_url = urllib.parse.urljoin(
                        self.source.url, feed_link_href
                    )
                    if discovered_url != self.source.url:
                        logger.info(
                            f"Auto-discovered live feed URL {discovered_url!r} for {self.source.name!r}"
                        )
                        refetch_resp = await client.get(discovered_url)
                        if refetch_resp.status_code == 200:
                            feed = feedparser.parse(refetch_resp.content)
                            discovered_entries = self._extract_entries(feed)
                            if discovered_entries:
                                if self.source.config is None:
                                    self.source.config = {}
                                self.source.config["discovered_feed_url"] = discovered_url
                                return discovered_entries
            except Exception as disco_err:
                logger.debug(f"Feed auto-discovery failed for {self.source.name!r}: {disco_err}")

            # 2. High-Speed HTML Portal Extractor Fallback (Off-thread to keep event loop free)
            portal_entries = await asyncio.to_thread(
                self._extract_html_portal_entries, raw_bytes, self.source.url
            )
            if portal_entries:
                logger.info(
                    f"Extracted {len(portal_entries)} live entries from HTML explore portal for {self.source.name!r}"
                )
                return portal_entries

            raise RuntimeError(
                f"Source {self.source.name!r} returned HTML instead of RSS/Atom with no extractable articles or RSS link "
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
        source_cfg = self.source.config or {}
        limit_val = source_cfg.get("limit")
        try:
            max_feed_entries = (
                int(limit_val)
                if limit_val is not None
                else getattr(settings.fetch, "max_entries_per_feed", 25)
            )
        except (ValueError, TypeError):
            max_feed_entries = getattr(settings.fetch, "max_entries_per_feed", 25)

        require_ai = bool(
            source_cfg.get("require_ai") or source_cfg.get("filter_mode") == "ai"
        )

        entries: list[dict] = []

        for item in feed.entries:
            if len(entries) >= max_feed_entries:
                break

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
            parsed_date = False
            if hasattr(item, "published_parsed") and item.published_parsed:
                try:
                    y, m, d, hh, mm, ss = item.published_parsed[:6]
                    published_at = datetime(y, m, d, hh, mm, ss, tzinfo=UTC)
                    parsed_date = True
                except Exception:
                    pass
            elif hasattr(item, "updated_parsed") and item.updated_parsed:
                try:
                    y, m, d, hh, mm, ss = item.updated_parsed[:6]
                    published_at = datetime(y, m, d, hh, mm, ss, tzinfo=UTC)
                    parsed_date = True
                except Exception:
                    pass

            # Fallback to dateutil fuzzy parser for non-standard RFC timestamps (e.g. Chinese YYYY年MM月DD日, VTT, European portals)
            if not parsed_date:
                raw_date_str = (
                    getattr(item, "published", None)
                    or getattr(item, "updated", None)
                    or (item.get("pubDate") if hasattr(item, "get") else None)
                )
                if raw_date_str and isinstance(raw_date_str, str):
                    try:
                        clean_date_str = raw_date_str
                        # Normalize Chinese calendar formats: 2025年02月18日 -> 2025-02-18
                        clean_date_str = re.sub(
                            r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?",
                            r"\1-\2-\3 ",
                            clean_date_str,
                        )
                        clean_date_str = re.sub(
                            r"(\d{1,2})\s*时\s*(\d{1,2})\s*分(?:\s*(\d{1,2})\s*秒)?",
                            lambda m: (
                                f" {m.group(1)}:{m.group(2)}:{m.group(3)} "
                                if m.group(3)
                                else f" {m.group(1)}:{m.group(2)} "
                            ),
                            clean_date_str,
                        )
                        is_cst_utc8 = bool(
                            re.search(
                                r"(?:CST|UTC\+8|\+0800|\+08:00|北京时间)",
                                raw_date_str,
                                re.IGNORECASE,
                            )
                        )
                        parsed_dt = dt_parser.parse(clean_date_str, fuzzy=True)
                        if parsed_dt.tzinfo is None:
                            is_cn_source = bool(
                                self.source
                                and (
                                    getattr(self.source, "config", {}).get("country")
                                    == "CN"
                                    or getattr(self.source, "config", {}).get("region")
                                    == "china"
                                )
                            )
                            if is_cst_utc8 or is_cn_source:
                                from datetime import timedelta, timezone

                                parsed_dt = parsed_dt.replace(
                                    tzinfo=timezone(timedelta(hours=8))
                                )
                            else:
                                parsed_dt = parsed_dt.replace(tzinfo=UTC)
                        published_at = parsed_dt.astimezone(UTC)
                        parsed_date = True
                    except Exception:
                        pass

            raw_title = getattr(item, "title", "Untitled")
            clean_title = self._clean_html(raw_title)

            # ── Optional Strict AI Relevance Gate ───────────────────────────
            if require_ai:
                combined_check = f"{clean_title} {content}"
                if not _AI_RELEVANCE_RE.search(combined_check):
                    continue

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

            # Direct Repository Extraction for Curation / Social Feeds (e.g. Reddit r/BestGitHubRepos)
            item_url = getattr(item, "link", "")
            is_curated_repo_feed = (
                self.source.category == Category.GITHUB_TRENDING
                or "github" in self.source.name.lower()
                or "reddit.com/r/" in item_url.lower()
            )
            extracted_repo_url = None
            if is_curated_repo_feed:
                raw_full = f"{content} {getattr(item, 'summary', '')}"
                gh_match = re.search(
                    r"https?://(?:www\.)?github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)(?:[/?#\s]|$)",
                    raw_full,
                )
                if gh_match:
                    repo_path = gh_match.group(1).rstrip("/.")
                    if not any(
                        repo_path.startswith(p)
                        for p in ("features", "pricing", "about", "site", "topics")
                    ):
                        extracted_repo_url = f"https://github.com/{repo_path}"
                elif (
                    "reddit.com/r/" in item_url.lower()
                    and self.source.category == Category.GITHUB_TRENDING
                ):
                    # Skip meta / newsletter announcements that don't contain any GitHub repository
                    if any(
                        spam_kw in clean_title.lower()
                        for spam_kw in (
                            "never miss",
                            "newsletter",
                            "weekly digest",
                            "join our",
                        )
                    ):
                        continue

            final_url = extracted_repo_url or item_url
            entry_meta = {
                "feed_title": feed.feed.get("title", ""),
                "feed_link": feed.feed.get("link", ""),
                "region": (self.source.config or {}).get("region", "global"),
                "country": (self.source.config or {}).get("country", "GLOBAL"),
                "provenance_type": "trending_repo"
                if extracted_repo_url
                else (self.source.config or {}).get("provenance_type", "rss_feed"),
            }
            if extracted_repo_url:
                entry_meta["repo_url"] = extracted_repo_url
                entry_meta["curated_via"] = self.source.name
                if "reddit.com" in item_url:
                    entry_meta["reddit_discussion_url"] = item_url

            entries.append(
                {
                    "title": clean_title,
                    "url": final_url,
                    "content": content,
                    "published_at": published_at,
                    "tags": [tag.term for tag in getattr(item, "tags", [])],
                    "metadata": entry_meta,
                }
            )

        return entries

    def _parse_entry(self, raw: dict) -> Entry:
        """Parse raw entry into Entry entity."""
        title = raw.get("title") or "Untitled RSS Item"
        url = raw.get("url") or (
            str(self.source.url)
            if self.source and self.source.url
            else "https://news.ycombinator.com"
        )
        pub_at = raw.get("published_at") or datetime.now(UTC)
        content_hash = ContentHash.from_content(
            title,
            url,
            str(pub_at),
        )
        content = raw.get("content") or ""

        return Entry(
            source_id=self.source.id,
            title=title,
            url=url,
            content_hash=str(content_hash),
            summary=content[:500] if content else title,
            published_at=pub_at,
            category=self.source.category,
            tags=raw.get("tags", []),
            metadata=raw.get("metadata", {})
            if isinstance(raw.get("metadata"), dict)
            else {},
        )

    def _sync_find_feed_link_in_head(self, html_prefix: bytes) -> str | None:
        """Find live alternate RSS/Atom feed links in HTML head (synchronous, run off-thread)."""
        try:
            soup = BeautifulSoup(html_prefix, "html.parser")
            for link in soup.find_all("link"):
                rel = link.get("rel")
                rel_str = " ".join(rel) if isinstance(rel, list) else str(rel or "")
                if "alternate" in rel_str.lower():
                    t_str = str(link.get("type") or "").lower()
                    if any(x in t_str for x in ("rss", "atom", "xml")):
                        href = link.get("href")
                        if href:
                            return str(href)
        except Exception:
            pass
        return None

    def _extract_json_entries(self, data: Any, base_url: str) -> list[dict]:
        """Extract entries from structured JSON API endpoints (e.g. Jiqizhixin, ModelScope, Gitee)."""
        items: list[Any] = []
        is_jiqizhixin = "jiqizhixin" in base_url
        is_modelscope = "modelscope" in base_url

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # ModelScope structure
            if is_modelscope and "Data" in data and isinstance(data["Data"], dict):
                items = data["Data"].get("Models") or data["Data"].get("items") or []
            # Jiqizhixin structure
            elif is_jiqizhixin and "articles" in data:
                items = data["articles"]
            else:
                for k in ("items", "data", "articles", "entries", "posts", "models", "Models", "repositories"):
                    val = data.get(k)
                    if isinstance(val, list):
                        items = val
                        break

        entries: list[dict] = []
        now = datetime.now(UTC)
        two_weeks_ago = now - timedelta(days=14)
        limit = min(int((self.source.config or {}).get("limit", 25)), 35)

        for item in items:
            if len(entries) >= limit:
                break
            if not isinstance(item, dict):
                continue
            title = (
                item.get("title")
                or item.get("name")
                or item.get("ChineseName")
                or item.get("headline")
                or ""
            )
            if not title or len(str(title).strip()) < 5:
                continue

            # ModelScope target link canonicalization
            if is_modelscope:
                model_name = str(item.get("Name") or item.get("name") or item.get("TargetUrl") or "")
                url_val = f"https://modelscope.cn/models/{model_name}" if model_name else base_url
            # Jiqizhixin article canonicalization
            elif is_jiqizhixin:
                art_id = str(item.get("id") or item.get("slug") or "")
                url_val = f"https://www.jiqizhixin.com/articles/{art_id}" if art_id else base_url
            else:
                raw_u = item.get("url") or item.get("link") or item.get("target_url")
                if raw_u:
                    url_val = str(raw_u)
                else:
                    item_id = item.get("id") or item.get("slug")
                    if item_id:
                        url_val = urllib.parse.urljoin(base_url, f"articles/{item_id}")
                    else:
                        url_val = base_url

            summary = (
                item.get("summary")
                or item.get("description")
                or item.get("content")
                or item.get("snippet")
                or ""
            )

            # Date extraction
            pub_date = now
            raw_date = (
                item.get("published_at")
                or item.get("publish_time")
                or item.get("created_at")
                or item.get("GmtModified")
                or item.get("updated_at")
                or item.get("pubDate")
                or item.get("date")
            )
            if raw_date and isinstance(raw_date, str):
                try:
                    dt = dt_parser.parse(raw_date, fuzzy=True)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    pub_date = dt.astimezone(UTC)
                except Exception:
                    pass
            elif isinstance(raw_date, (int, float)):
                # Unix timestamp (seconds or milliseconds)
                try:
                    ts = raw_date / 1000.0 if raw_date > 1e11 else raw_date
                    pub_date = datetime.fromtimestamp(ts, tz=UTC)
                except Exception:
                    pass

            if pub_date < two_weeks_ago:
                continue

            entry_meta = {
                "feed_title": self.source.name,
                "feed_link": base_url,
                "region": (self.source.config or {}).get("region", "global"),
                "country": (self.source.config or {}).get("country", "GLOBAL"),
                "provenance_type": (self.source.config or {}).get(
                    "provenance_type", "json_api"
                ),
            }

            entries.append(
                {
                    "title": str(title).strip(),
                    "url": str(url_val).strip(),
                    "content": self._clean_html(str(summary).strip())
                    if summary
                    else str(title).strip(),
                    "published_at": pub_date,
                    "tags": [
                        self.source.category.value
                        if hasattr(self.source.category, "value")
                        else str(self.source.category)
                    ],
                    "metadata": entry_meta,
                }
            )

        return entries

    def _extract_html_portal_entries(
        self, html_bytes: bytes, base_url: str
    ) -> list[dict]:
        """Extract structured articles / repository cards directly from HTML explore portals (CPU-bound, runs off-thread)."""
        try:
            soup = BeautifulSoup(html_bytes, "html.parser")
        except Exception:
            return []

        entries: list[dict] = []
        seen_urls: set[str] = set()
        now = datetime.now(UTC)
        two_weeks_ago = now - timedelta(days=14)

        # Decompose non-content elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        candidates: list[tuple[str, str, str, Any]] = []
        # Check standard article containers
        for container in soup.select(
            "article, .article-item, .news-item, .post-item, .explore-repo__list .item, .project-item, tr, li"
        ):
            a_tag = container.find("a", href=True)
            if not a_tag:
                continue
            text = a_tag.get_text(strip=True)
            if len(text) < 10:
                heading = container.find(
                    ["h1", "h2", "h3", "h4", ".title", ".name"]
                )
                if heading:
                    text = heading.get_text(strip=True)
            if len(text) >= 10:
                summary_el = container.find(
                    ["p", ".desc", ".description", ".summary", ".content"]
                )
                summary = summary_el.get_text(strip=True) if summary_el else ""
                candidates.append((text, str(a_tag["href"]), summary, container))

        # Fallback: scan all anchor tags with article-like paths
        if not candidates:
            for a_tag in soup.find_all("a", href=True):
                text = a_tag.get_text(strip=True)
                href_str = str(a_tag["href"])
                if len(text) >= 12 and not href_str.startswith(("javascript:", "#", "mailto:")):
                    if any(
                        nav in text
                        for nav in (
                            "首页",
                            "关于",
                            "登录",
                            "注册",
                            "Home",
                            "About",
                            "Login",
                            "Register",
                            "Contact",
                            "Privacy",
                            "Terms",
                        )
                    ):
                        continue
                    candidates.append((text, href_str, "", None))

        limit = min(int((self.source.config or {}).get("limit", 20)), 30)

        # Disallowed file extensions and path fragments for portal articles
        disallowed_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".pdf", ".zip")
        disallowed_paths = ("/tag/", "/category/", "/categories/", "/user/", "/users/", "/author/", "/search", "/page/", "/terms", "/privacy", "/about", "/contact")

        for text, href, summary, container in candidates:
            if len(entries) >= limit:
                break
            full_url = urllib.parse.urljoin(base_url, href)
            lower_url = full_url.lower()

            # Canonicalization and junk filter
            if (
                full_url in seen_urls
                or full_url == base_url
                or len(full_url) < 12
                or not full_url.startswith(("http://", "https://"))
                or any(lower_url.endswith(ext) for ext in disallowed_exts)
                or any(p in lower_url for p in disallowed_paths)
            ):
                continue
            seen_urls.add(full_url)

            # Date extraction
            pub_date = now
            if container:
                time_tag = container.find(["time", ".date", ".time"])
                if time_tag:
                    raw_time = time_tag.get("datetime") or time_tag.get_text(strip=True)
                    if raw_time:
                        try:
                            clean_dt = dt_parser.parse(raw_time, fuzzy=True)
                            if clean_dt.tzinfo is None:
                                clean_dt = clean_dt.replace(tzinfo=UTC)
                            pub_date = clean_dt.astimezone(UTC)
                        except Exception:
                            pass

            # Strict 14-day freshness invariant
            if pub_date < two_weeks_ago:
                continue

            entry_meta = {
                "feed_title": self.source.name,
                "feed_link": base_url,
                "region": (self.source.config or {}).get("region", "global"),
                "country": (self.source.config or {}).get("country", "GLOBAL"),
                "provenance_type": (self.source.config or {}).get(
                    "provenance_type", "html_portal"
                ),
            }

            entries.append(
                {
                    "title": text.strip(),
                    "url": full_url.strip(),
                    "content": self._clean_html(summary.strip())
                    if summary
                    else text.strip(),
                    "published_at": pub_date,
                    "tags": [
                        self.source.category.value
                        if hasattr(self.source.category, "value")
                        else str(self.source.category)
                    ],
                    "metadata": entry_meta,
                }
            )

        return entries

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
