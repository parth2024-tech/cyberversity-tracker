# HackerNews fetcher for AI/ML tagged stories.

import asyncio
from datetime import UTC, datetime
from typing import Any

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


class HackerNewsFetcher(BaseFetcher):
    """Fetcher for Hacker News AI/ML stories via Algolia API."""

    @property
    def fetcher_type(self) -> str:
        return "hackernews"

    async def _fetch_raw(self) -> list[dict]:
        # Algolia Search API does not support boolean 'OR' in query strings.
        # We query recent stories using search_by_date across core AI topics and deduplicate.
        base_url = "https://hn.algolia.com/api/v1/search_by_date"
        from datetime import timedelta

        max_age_days = getattr(settings.database, "max_ingest_age_days", 14)
        cutoff_dt = datetime.now(UTC) - timedelta(days=max_age_days)
        cutoff_ts = int(cutoff_dt.timestamp())

        keywords = self.source.config.get("tags") if self.source.config else None
        if not keywords:
            keywords = [
                "AI",
                "LLM",
                "Claude",
                "OpenAI",
                "DeepSeek",
                "Qwen",
                "Mistral",
                "Llama",
                "vLLM",
                "reasoning",
                "agents",
                "machine learning",
            ]

        headers = {"User-Agent": settings.fetch.user_agent}
        seen_ids: set[str] = set()
        entries: list[dict] = []

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=headers, follow_redirects=True
        ) as client:
            for kw in keywords[:8]:
                try:
                    params = {
                        "tags": "story",
                        "query": kw,
                        "hitsPerPage": 15,
                        "numericFilters": f"created_at_i>{cutoff_ts}",
                    }
                    response = await client.get(base_url, params=params)
                    if response.status_code != 200:
                        continue
                    data = response.json()
                    for hit in data.get("hits", []):
                        oid = str(hit.get("objectID", ""))
                        if not oid or oid in seen_ids:
                            continue
                        seen_ids.add(oid)

                        title = hit.get("title", "Untitled")
                        url_str = (
                            hit.get("url")
                            or f"https://news.ycombinator.com/item?id={oid}"
                        )
                        points = hit.get("points", 0)
                        author = hit.get("author", "")
                        num_comments = hit.get("num_comments", 0)
                        created_at = hit.get("created_at", "")

                        content = f"Points: {points} | Comments: {num_comments} | Author: {author}"
                        if hit.get("story_text"):
                            content = hit["story_text"][:500] + "\n\n" + content

                        pub_at = datetime.now(UTC)
                        if created_at:
                            try:
                                pub_at = datetime.fromisoformat(
                                    created_at.replace("Z", "+00:00")
                                )
                            except Exception:
                                pass

                        entries.append(
                            {
                                "title": title,
                                "url": url_str,
                                "content": content,
                                "published_at": pub_at,
                                "tags": ["hackernews", "ai", kw.lower()],
                                "metadata": {
                                    "hn_id": oid,
                                    "points": points,
                                    "author": author,
                                    "num_comments": num_comments,
                                },
                            }
                        )
                except Exception as kw_err:
                    logger.debug(
                        f"Hacker News query failed for keyword '{kw}': {kw_err}"
                    )
                    continue

            # Fetch top discussion comments for highest-scored stories
            if entries:
                top_entries = sorted(
                    entries,
                    key=lambda e: e.get("metadata", {}).get("points", 0),
                    reverse=True,
                )[:6]
                comment_tasks = [
                    self._enrich_hn_comments(client, entry)
                    for entry in top_entries
                    if entry.get("metadata", {}).get("num_comments", 0) > 0
                ]
                await asyncio.gather(*comment_tasks, return_exceptions=True)

        return entries

    async def _enrich_hn_comments(
        self, client: httpx.AsyncClient, entry: dict[str, Any]
    ) -> None:
        """Fetch top discussion comments from Algolia item endpoint."""
        oid = entry.get("metadata", {}).get("hn_id")
        if not oid:
            return
        item_url = f"https://hn.algolia.com/api/v1/items/{oid}"
        try:
            resp = await client.get(item_url, timeout=5.0)
            if resp.status_code == 200:
                item_data = resp.json()
                children = item_data.get("children", [])
                comments = []
                import re

                for c in children:
                    c_author = c.get("author", "anon")
                    c_text = c.get("text", "")
                    if c_text and len(c_text) > 10:
                        clean_text = re.sub(r"<[^>]+>", " ", c_text).strip()
                        if len(clean_text) > 300:
                            clean_text = clean_text[:297] + "..."
                        comments.append(f"[{c_author}]: {clean_text}")
                    if len(comments) >= 3:
                        break
                if comments:
                    entry["content"] += "\n\n--- Top Discussion ---\n" + "\n".join(
                        f"• {c}" for c in comments
                    )
        except Exception:
            pass

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


fetcher_registry.register("hackernews", HackerNewsFetcher)
