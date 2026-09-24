# HackerNews fetcher for AI/ML tagged stories.

from datetime import UTC, datetime

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
