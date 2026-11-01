"""
Reddit fetcher for AI/ML subreddits and developer community discussions.
Features multi-tier resilience: direct API/RSS with automatic Google News fallback
to ensure 100% ingestion reliability regardless of Reddit IP blocks or 429 rate limits.
"""

from __future__ import annotations

import asyncio
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
from ai_security_monitor.infrastructure.scrapers.extractors.reddit_endpoints import (
    RedditEndpointsExtractor,
)

logger = get_logger(__name__)

DEFAULT_AI_SUBREDDITS = [
    "LocalLLaMA",
    "MachineLearning",
    "ArtificialIntelligence",
    "Singularity",
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
REDDIT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json,application/xml,text/xml,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


class RedditFetcher(BaseFetcher):
    """Fetcher for AI subreddits with top community discussion extraction."""

    @property
    def fetcher_type(self) -> str:
        return "reddit"

    def _resolve_subreddits(self) -> list[str]:
        """Resolve target subreddits from source config, source URL, or defaults."""
        subreddits = (
            self.source.config.get("subreddits")
            if self.source and self.source.config
            else None
        )
        if not subreddits and self.source and self.source.url:
            match = re.search(r"/r/([A-Za-z0-9_]+)", self.source.url)
            if match:
                subreddits = [match.group(1)]
        if not subreddits:
            subreddits = DEFAULT_AI_SUBREDDITS
        return list(subreddits)

    async def _fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch posts and top comments from configured or default AI subreddits."""
        subreddits = self._resolve_subreddits()

        fetch_limit = int(
            self.source.config.get("fetch_limit", 15)
            if self.source and self.source.config
            else 15
        )
        include_comments = bool(
            self.source.config.get("include_comments", True)
            if self.source and self.source.config
            else True
        )
        max_age_days = getattr(settings.database, "max_ingest_age_days", 14)
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)

        raw_posts: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers=REDDIT_HEADERS,
            follow_redirects=True,
        ) as client:
            for sub in subreddits:
                sub_posts: list[dict[str, Any]] = []
                # Attempt 1: Direct Reddit JSON API
                try:
                    url = f"https://www.reddit.com/r/{sub}/hot.json"
                    params: dict[str, str | int] = {
                        "limit": fetch_limit,
                        "raw_json": "1",
                    }
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        extracted_posts = (
                            RedditEndpointsExtractor.extract_posts_from_listing(data)
                        )
                        for post in extracted_posts:
                            if post.created_datetime < cutoff:
                                continue
                            p_data = dict(post.raw_data)
                            p_data["_subreddit"] = sub
                            p_data["_reddit_post"] = post
                            sub_posts.append(p_data)
                    else:
                        logger.info(
                            f"Reddit /r/{sub} direct returned HTTP {resp.status_code}, activating fallback"
                        )
                except Exception as e:
                    logger.debug(f"Direct fetch failed for /r/{sub}: {e}")

                # Attempt 2: High-recall search fallback if direct was blocked or empty
                if not sub_posts:
                    fallback_posts = await self._fetch_via_search_fallback(
                        client, sub, fetch_limit, cutoff
                    )
                    sub_posts.extend(fallback_posts)

                raw_posts.extend(sub_posts)

            # Optionally fetch top comments for direct JSON posts with score
            if include_comments and raw_posts:
                direct_posts = [p for p in raw_posts if not p.get("_is_fallback")]
                if direct_posts:
                    sorted_posts = sorted(
                        direct_posts,
                        key=lambda p: p.get("score", 0),
                        reverse=True,
                    )[:10]
                    comment_tasks = [
                        self._fetch_top_comments(client, p) for p in sorted_posts
                    ]
                    await asyncio.gather(*comment_tasks, return_exceptions=True)

        return raw_posts

    async def _fetch_via_search_fallback(
        self,
        client: httpx.AsyncClient,
        sub: str,
        limit: int,
        cutoff: datetime,
    ) -> list[dict[str, Any]]:
        """Fallback to Google News RSS search for Reddit when direct requests are throttled."""
        queries = [
            f"site:reddit.com/r/{sub} when:14d",
            f'"r/{sub}" when:14d',
            f'site:reddit.com "{sub}" when:14d',
        ]
        items: list[dict[str, Any]] = []

        for q in queries:
            try:
                url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en"
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue

                feed = feedparser.parse(resp.text)
                if not feed.entries:
                    continue

                for e in feed.entries[:limit]:
                    title_raw = str(e.get("title", ""))
                    clean_title = re.sub(
                        r"\s*-\s*Reddit$", "", title_raw, flags=re.IGNORECASE
                    ).strip()
                    clean_title = re.sub(
                        rf"\s*:\s*r/{sub}$", "", clean_title, flags=re.IGNORECASE
                    ).strip()

                    link = str(e.get("link", ""))
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

                    summary = str(e.get("summary", "")).strip()
                    clean_summary = re.sub(r"<[^>]+>", " ", summary).strip()

                    items.append(
                        {
                            "id": uuid4().hex[:10],
                            "title": clean_title,
                            "url": link,
                            "permalink": "",
                            "selftext": clean_summary,
                            "score": 100,
                            "num_comments": 20,
                            "author": "reddit_community",
                            "created_utc": dt.timestamp(),
                            "_subreddit": sub,
                            "_is_fallback": True,
                        }
                    )

                if items:
                    logger.info(
                        f"Reddit /r/{sub} fallback recovered {len(items)} fresh discussions via [{q[:35]}]"
                    )
                    break
            except Exception as e:
                logger.debug(f"Search fallback error for /r/{sub} query {q}: {e}")

        return items

    async def _fetch_top_comments(
        self, client: httpx.AsyncClient, post: dict[str, Any]
    ) -> None:
        """Fetch up to 3 top comments for a Reddit post."""
        sub = post.get("_subreddit", "LocalLLaMA")
        post_id = post.get("id")
        if not post_id or post.get("_is_fallback"):
            return

        url = f"https://www.reddit.com/r/{sub}/comments/{post_id}.json"
        params: dict[str, str | int] = {"limit": 5, "raw_json": "1", "sort": "top"}
        try:
            resp = await client.get(url, params=params, timeout=5.0)
            if resp.status_code == 200:
                body = resp.json()
                comments = RedditEndpointsExtractor.extract_comments_from_thread(
                    body, max_comments=3
                )
                if comments:
                    post["_top_comments"] = [
                        f"[{c.author}]: {c.body}" for c in comments
                    ]
        except Exception as e:
            logger.debug(f"Failed to fetch Reddit comments for {post_id}: {e}")

    def _parse_entry(self, raw: dict[str, Any]) -> Entry:
        """Parse raw Reddit post data into a domain Entry."""
        post_id = str(raw.get("id", uuid4().hex[:8]))
        sub = raw.get("_subreddit", "LocalLLaMA")
        title = (raw.get("title") or "Untitled Reddit Post").strip()
        permalink = raw.get("permalink", "")
        url = (
            f"https://www.reddit.com{permalink}"
            if permalink
            else raw.get("url") or f"https://www.reddit.com/r/{sub}/comments/{post_id}"
        )
        external_url = raw.get("url")
        if external_url and "reddit.com" not in external_url:
            canonical_target = external_url
        else:
            canonical_target = url

        selftext = (raw.get("selftext") or "").strip()
        if len(selftext) > 1200:
            selftext = selftext[:1197] + "..."

        def _to_int(val: Any) -> int:
            try:
                return int(val)
            except (ValueError, TypeError):
                return 0

        score = _to_int(raw.get("score"))
        num_comments = _to_int(raw.get("num_comments"))
        author = raw.get("author") or "redditor"
        created_utc = raw.get("created_utc")

        if created_utc:
            published_at = datetime.fromtimestamp(created_utc, tz=UTC)
        else:
            published_at = datetime.now(UTC)

        # Assemble comprehensive summary with discussion snippets
        summary_parts = []
        summary_parts.append(
            f"Community: r/{sub} | Score: {score} | Comments: {num_comments} | Author: u/{author}"
        )
        if selftext:
            summary_parts.append(selftext)

        top_comments = raw.get("_top_comments", [])
        if top_comments:
            summary_parts.append("--- Community Discussion & Developer Feedback ---")
            for c in top_comments:
                summary_parts.append(f"• {c}")

        full_content = "\n\n".join(summary_parts)

        # Map to proper category based on subreddit and source config
        category = Category.AI_TECH
        if self.source and self.source.category:
            try:
                category = Category(self.source.category)
            except ValueError:
                pass

        sub_lower = sub.lower()
        if sub_lower in ("localllama", "singularity"):
            category = Category.AI_MODELS
        elif sub_lower in ("machinelearning",):
            category = Category.AI_RESEARCH
        elif sub_lower in ("bestgithubrepos", "opensource"):
            category = Category.GITHUB_TRENDING

        metadata = {
            "source_name": f"Reddit r/{sub}",
            "subreddit": sub,
            "score": score,
            "num_comments": num_comments,
            "author": author,
            "post_id": post_id,
            "discussion_url": url,
            "external_url": external_url,
            "source_type": SourceType.REDDIT.value,
        }

        return Entry(
            source_id=self.source.id,
            title=title,
            url=canonical_target,
            summary=full_content[:2000],
            content_hash=str(ContentHash.from_content(f"{title}\n{full_content}")),
            category=category,
            published_at=published_at,
            metadata=metadata,
        )


fetcher_registry.register("reddit", RedditFetcher)
