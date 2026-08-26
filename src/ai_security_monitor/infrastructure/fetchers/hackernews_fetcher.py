# HackerNews fetcher for AI/ML tagged stories.

from datetime import datetime

import httpx

from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import Entry
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)


class HackerNewsFetcher(BaseFetcher):
    """Fetcher for Hacker News AI/ML stories via Algolia API."""

    @property
    def fetcher_type(self) -> str:
        return "hackernews"

    async def _fetch_raw(self) -> list[dict]:
        # Use Algolia API to search for AI/ML stories
        url = "https://hn.algolia.com/api/v1/search"
        params = {
            "tags": "story",
            "query": "AI OR ML OR LLM OR GPT OR neural OR transformer OR machine learning",
            "hitsPerPage": 50,
            "page": 0,
        }
        headers = {"User-Agent": settings.fetch.user_agent}

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

        data = response.json()
        entries = []

        for hit in data.get("hits", []):
            title = hit.get("title", "Untitled")
            url_str = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            points = hit.get("points", 0)
            author = hit.get("author", "")
            num_comments = hit.get("num_comments", 0)
            created_at = hit.get("created_at", "")

            content = f"Points: {points} | Comments: {num_comments} | Author: {author}"
            if hit.get("story_text"):
                content = hit["story_text"][:500] + "\n\n" + content

            entries.append({
                "title": title,
                "url": url_str,
                "content": content,
                "published_at": datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else datetime.utcnow(),
                "tags": ["hackernews", "ai", "ml", "llm", "gpt"],
                "metadata": {
                    "hn_id": hit.get("objectID"),
                    "points": points,
                    "author": author,
                    "num_comments": num_comments,
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


fetcher_registry.register("hackernews", HackerNewsFetcher)
