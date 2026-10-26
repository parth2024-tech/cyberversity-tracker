"""Hugging Face Trending Repositories and Foundation Models fetcher.

Fetches high-velocity trending open-source models, repositories, and spaces
from the official public Hugging Face Trending API (api.huggingface.co/api/trending).
Ensures worldwide multi-source coverage of trending AI codebases.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry, Source, SourceType
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)

logger = get_logger(__name__)


class HuggingFaceTrendingFetcher(BaseFetcher):
    """Fetcher for Hugging Face trending models, codebases, and spaces."""

    BASE_URL = "https://huggingface.co/api/trending"

    def __init__(
        self, source: Source, timeout: int | None = None, max_retries: int | None = None
    ):
        super().__init__(source, timeout=timeout or 30, max_retries=max_retries)

    @property
    def fetcher_type(self) -> str:
        return "huggingface_trending"

    async def _fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch trending items from Hugging Face public trending API."""
        limit = int((self.source.config or {}).get("limit", 20))
        params: dict[str, Any] = {"limit": min(limit, 20)}

        headers = {
            "User-Agent": settings.fetch.user_agent,
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(
            timeout=self.timeout or 25.0,
            headers=headers,
            follow_redirects=True,
        ) as client:
            resp = await client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        items = data.get("recentlyTrending", [])
        if not items and isinstance(data, list):
            items = data

        raw_entries: list[dict[str, Any]] = []
        for it in items[:limit]:
            repo = it.get("repoData") or it
            repo_id = repo.get("id") or repo.get("name") or ""
            if not repo_id:
                continue

            author = (
                repo.get("author")
                or repo.get("authorData", {}).get("name")
                or repo_id.split("/")[0]
                if "/" in repo_id
                else ""
            )
            downloads = int(repo.get("downloads", 0) or 0)
            likes = int(repo.get("likes", 0) or 0)
            pipeline_tag = repo.get("pipeline_tag") or "ai-model"
            repo_type = repo.get("type", "model")

            url = f"https://huggingface.co/{repo_id}"
            title = f"{repo_id}: Trending {pipeline_tag.replace('-', ' ').title()} ({likes:,} likes, {downloads:,} downloads)"

            desc_parts = [
                f"**Trending Hugging Face Open-Source {repo_type.title()}**: `{repo_id}`",
                f"- **Organization / Author**: {author or 'Community'}",
                f"- **Pipeline / Task**: {pipeline_tag}",
                f"- **Metrics**: {likes:,} likes | {downloads:,} monthly downloads",
                f"- **Repository URL**: {url}",
            ]
            content = "\n".join(desc_parts)

            tags = ["huggingface", "trending", "open-source", "ai-models"]
            if pipeline_tag:
                tags.append(pipeline_tag.lower())
            if author:
                tags.append(author.lower())

            raw_entries.append(
                {
                    "repo_id": repo_id,
                    "author": author,
                    "downloads": downloads,
                    "likes": likes,
                    "pipeline_tag": pipeline_tag,
                    "repo_type": repo_type,
                    "title": title,
                    "url": url,
                    "content": content,
                    "tags": list(dict.fromkeys(tags)),
                    "published_at": datetime.now(UTC),
                }
            )

        return raw_entries

    def _parse_entry(self, raw: dict[str, Any]) -> Entry:
        """Parse raw Hugging Face trending entry into an Entry entity."""
        pub_date_str = (
            raw["published_at"].strftime("%Y-%m-%d")
            if hasattr(raw.get("published_at"), "strftime")
            else "hf_trending"
        )
        content_hash = ContentHash.from_content(
            "huggingface_trending",
            raw["repo_id"].lower().strip(),
            raw["url"].lower().strip(),
            pub_date_str,
        )

        metadata = {
            "source_name": self.source.name,
            "repo_name": raw["repo_id"],
            "author": raw["author"],
            "likes": raw["likes"],
            "downloads": raw["downloads"],
            "pipeline_tag": raw["pipeline_tag"],
            "repo_type": raw["repo_type"],
            "provenance_type": "trending_repo",
            "source_type": SourceType.HUGGINGFACE_TRENDING.value,
            "source_platform": "Hugging Face",
        }

        category = self.source.category or Category.AI_MODELS

        return Entry(
            source_id=self.source.id,
            title=raw["title"],
            url=raw["url"],
            content_hash=str(content_hash),
            summary=raw["content"][:800],
            published_at=raw["published_at"],
            category=category,
            tags=raw.get("tags", []),
            metadata=metadata,
        )


fetcher_registry.register("huggingface_trending", HuggingFaceTrendingFetcher)
