"""
Reddit fetcher for AI/ML subreddits and developer community discussions.
Inspired by Horizon's resilient multi-tier Reddit scraping pattern.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

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

DEFAULT_AI_SUBREDDITS = [
    "LocalLLaMA",
    "MachineLearning",
    "ArtificialIntelligence",
    "Singularity",
]

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
REDDIT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


class RedditFetcher(BaseFetcher):
    """Fetcher for AI subreddits with top community discussion extraction."""

    @property
    def fetcher_type(self) -> str:
        return "reddit"

    async def _fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch posts and top comments from configured or default AI subreddits."""
        subreddits = (
            self.source.config.get("subreddits")
            if self.source and self.source.config
            else None
        )
        if not subreddits:
            subreddits = DEFAULT_AI_SUBREDDITS

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
                try:
                    url = f"https://www.reddit.com/r/{sub}/hot.json"
                    params: dict[str, str | int] = {"limit": fetch_limit, "raw_json": "1"}
                    resp = await client.get(url, params=params)
                    if resp.status_code != 200:
                        logger.warning(
                            f"Reddit /r/{sub} returned HTTP {resp.status_code}"
                        )
                        continue

                    data = resp.json()
                    children = data.get("data", {}).get("children", [])
                    for child in children:
                        post_data = child.get("data", {})
                        if not post_data or post_data.get("stickied"):
                            continue

                        # Check published timestamp
                        created_utc = post_data.get("created_utc")
                        if created_utc:
                            dt = datetime.fromtimestamp(created_utc, tz=UTC)
                            if dt < cutoff:
                                continue

                        post_data["_subreddit"] = sub
                        raw_posts.append(post_data)

                except Exception as e:
                    logger.warning(f"Error fetching Reddit /r/{sub}: {e}")

            # Optionally fetch top comments for top-scored posts (concurrency limited)
            if include_comments and raw_posts:
                # Sort by score descending to get comments for top posts
                sorted_posts = sorted(
                    raw_posts,
                    key=lambda p: p.get("score", 0),
                    reverse=True,
                )[:10]

                comment_tasks = [
                    self._fetch_top_comments(client, p) for p in sorted_posts
                ]
                await asyncio.gather(*comment_tasks, return_exceptions=True)

        return raw_posts

    async def _fetch_top_comments(
        self, client: httpx.AsyncClient, post: dict[str, Any]
    ) -> None:
        """Fetch up to 3 top comments for a Reddit post."""
        sub = post.get("_subreddit", "LocalLLaMA")
        post_id = post.get("id")
        if not post_id:
            return

        url = f"https://www.reddit.com/r/{sub}/comments/{post_id}.json"
        params: dict[str, str | int] = {"limit": 5, "raw_json": "1", "sort": "top"}
        try:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                body = resp.json()
                if isinstance(body, list) and len(body) > 1:
                    comment_children = (
                        body[1].get("data", {}).get("children", [])
                    )
                    top_comments = []
                    for c in comment_children:
                        cdata = c.get("data", {})
                        author = cdata.get("author", "[deleted]")
                        body_text = cdata.get("body", "").strip()
                        if body_text and body_text != "[deleted]" and len(body_text) > 10:
                            # Truncate comment length
                            clean_text = (
                                body_text[:350] + "..."
                                if len(body_text) > 350
                                else body_text
                            )
                            top_comments.append(f"[{author}]: {clean_text}")
                        if len(top_comments) >= 3:
                            break
                    if top_comments:
                        post["_top_comments"] = top_comments
        except Exception as e:
            logger.debug(f"Failed to fetch Reddit comments for {post_id}: {e}")

    def _parse_entry(self, raw: dict[str, Any]) -> Entry:
        """Parse raw Reddit post data into a domain Entry."""
        post_id = str(raw.get("id", uuid4().hex[:8]))
        sub = raw.get("_subreddit", "LocalLLaMA")
        title = raw.get("title", "Untitled Reddit Post").strip()
        permalink = raw.get("permalink", "")
        url = (
            f"https://www.reddit.com{permalink}"
            if permalink
            else f"https://www.reddit.com/r/{sub}/comments/{post_id}"
        )
        external_url = raw.get("url")
        if external_url and "reddit.com" not in external_url:
            canonical_target = external_url
        else:
            canonical_target = url

        selftext = (raw.get("selftext") or "").strip()
        if len(selftext) > 1200:
            selftext = selftext[:1197] + "..."

        score = int(raw.get("score", 0))
        num_comments = int(raw.get("num_comments", 0))
        author = raw.get("author", "redditor")
        created_utc = raw.get("created_utc")

        if created_utc:
            published_at = datetime.fromtimestamp(created_utc, tz=UTC)
        else:
            published_at = datetime.now(UTC)

        # Assemble comprehensive summary with discussion snippets
        summary_parts = []
        summary_parts.append(f"Community: r/{sub} | Score: {score} | Comments: {num_comments} | Author: u/{author}")
        if selftext:
            summary_parts.append(selftext)

        top_comments = raw.get("_top_comments", [])
        if top_comments:
            summary_parts.append("--- Community Discussion & Developer Feedback ---")
            for c in top_comments:
                summary_parts.append(f"• {c}")

        full_content = "\n\n".join(summary_parts)

        # Map to proper category based on subreddit
        category = Category.AI_TECH
        if sub.lower() in ("localllama", "artificialintelligence"):
            category = Category.AI_MODELS
        elif sub.lower() == "machinelearning":
            category = Category.AI_RESEARCH

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
