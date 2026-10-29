# RSS/Atom feed fetcher implementation — top-tier, fault-tolerant.

import re
from datetime import UTC, datetime

import feedparser
import httpx
from dateutil import parser as dt_parser

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)

logger = get_logger(__name__)

# Chinese national standard encodings for legacy PRC/TW feeds
_CHINESE_ENCODINGS = ("gb18030", "gbk", "gb2312", "big5")

# Core AI keywords regex for strict filtering when require_ai is enabled
_AI_RELEVANCE_RE = re.compile(
    r"\b(ai|artificial intelligence|llm|llms|agent|agents|model|models|gpt|claude|gemini|deepseek|qwen|llama|mistral|transformer|transformers|diffusion|rag|vllm|sglang|ollama|deep learning|machine learning|neural|multimodal|inference|reasoning|benchmark|evals?)\b",
    re.IGNORECASE,
)


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
            timeout=self.timeout,
            headers=stealth_headers,
            follow_redirects=True,
        ) as client:
            for target_url in urls:
                try:
                    resp = await client.get(target_url)
                    if resp.status_code == 304:
                        logger.info(
                            f"Source {self.source.name!r} returned HTTP 304 Not Modified. "
                            "Feed unchanged; skipping body payload."
                        )
                        return []
                    resp.raise_for_status()
                    response = resp
                    break
                except Exception as req_err:
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

        # ── Content-type & HTML response guard ──────────────────────────────
        # If the server returned an HTML page (SPA redirect, Cloudflare WAF,
        # cookie-gate, landing page redirect, etc.) there is no point trying
        # to parse it as XML.
        # Raise immediately so the caller records a proper error rather than
        # silently reporting 0 entries + status: success.
        ct_header = (
            response.headers.get("content-type", "").lower().split(";")[0].strip()
        )
        first_1000 = raw_bytes[:1000].strip().lower()
        has_feed_marker = any(
            marker in first_1000 for marker in (b"<rss", b"<feed", b"<rdf:rdf")
        )
        is_html_markup = (
            first_1000.startswith((b"<!doctype html", b"<html", b"<!doctypehtml"))
            or (b"<html" in first_1000 and not has_feed_marker)
        )
        is_html_type = ct_header in ("text/html", "application/xhtml+xml")
        if (is_html_type or is_html_markup) and not has_feed_marker:
            raise RuntimeError(
                f"Source {self.source.name!r} returned HTML instead of RSS/Atom "
                f"(content-type: {ct_header or 'unknown'}). Feed URL may be dead, behind a "
                "login wall, redirecting to a landing page, or serving a JavaScript SPA."
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

            # Fallback to dateutil fuzzy parser for non-standard RFC timestamps (e.g., VTT, European portals)
            if not parsed_date:
                raw_date_str = (
                    getattr(item, "published", None)
                    or getattr(item, "updated", None)
                    or (item.get("pubDate") if hasattr(item, "get") else None)
                )
                if raw_date_str and isinstance(raw_date_str, str):
                    try:
                        parsed_dt = dt_parser.parse(raw_date_str, fuzzy=True)
                        if parsed_dt.tzinfo is None:
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
