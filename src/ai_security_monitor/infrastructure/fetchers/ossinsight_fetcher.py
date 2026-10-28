"""
OSS Insight trending repositories fetcher.
Fetches high-velocity star-gain repositories from api.ossinsight.io public API.
Inspired by Horizon's OSS Insight scraper.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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

DEFAULT_AI_KEYWORDS = [
    "ai",
    "llm",
    "agent",
    "model",
    "inference",
    "vllm",
    "sglang",
    "ollama",
    "transformer",
    "diffusion",
    "rag",
    "vector",
    "deep learning",
    "machine learning",
    "reasoning",
    "eval",
]


class OSSInsightFetcher(BaseFetcher):
    """Fetcher for OSS Insight trending GitHub repositories endpoint."""

    BASE_URL = "https://api.ossinsight.io/v1/trends/repos"

    @property
    def fetcher_type(self) -> str:
        return "oss_insight"

    async def _fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch trending repos across configured languages."""
        configured_languages = (
            self.source.config.get("languages")
            if self.source and self.source.config
            else None
        )
        languages: list[str] = (
            list(configured_languages)
            if configured_languages and isinstance(configured_languages, list)
            else ["Python", "TypeScript", "All"]
        )
        period = str(
            self.source.config.get("period", "past_24_hours")
            if self.source and self.source.config
            else "past_24_hours"
        )
        min_stars = int(
            self.source.config.get("min_stars", 10)
            if self.source and self.source.config
            else 10
        )
        max_items = int(
            self.source.config.get("max_items", 25)
            if self.source and self.source.config
            else 25
        )

        all_rows: list[dict[str, Any]] = []
        seen_repos: set[str] = set()

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={
                "User-Agent": settings.fetch.user_agent,
                "Accept": "application/json",
            },
            follow_redirects=True,
        ) as client:
            for lang in languages:
                try:
                    params = {"period": period, "language": lang}
                    resp = await client.get(self.BASE_URL, params=params)
                    if resp.status_code != 200:
                        logger.warning(
                            f"OSS Insight API returned status {resp.status_code} for {lang}"
                        )
                        continue

                    payload = resp.json()
                    data = payload.get("data", {})
                    rows = data.get("rows", [])
                    for row in rows:
                        repo_name = row.get("repo_name", "")
                        if not repo_name or repo_name in seen_repos:
                            continue

                        # Star filter
                        stars = int(row.get("stars", 0) or row.get("star_gain", 0) or 0)
                        if min_stars and stars < min_stars:
                            continue

                        # AI Relevance Filter
                        desc = (row.get("description") or "").lower()
                        name_low = repo_name.lower()
                        is_ai = any(
                            kw in desc or kw in name_low for kw in DEFAULT_AI_KEYWORDS
                        )
                        if not is_ai and lang != "Python":
                            continue

                        seen_repos.add(repo_name)
                        row["_language"] = lang
                        row["_period"] = period
                        all_rows.append(row)

                except Exception as e:
                    logger.warning(f"Error fetching OSS Insight for {lang}: {e}")

        # Sort by star gain descending
        all_rows.sort(
            key=lambda r: int(r.get("stars", 0) or r.get("star_gain", 0) or 0),
            reverse=True,
        )
        return all_rows[:max_items]

    def _parse_entry(self, raw: dict[str, Any]) -> Entry:
        """Parse raw OSS Insight row into a domain Entry."""
        repo_name = raw.get("repo_name", "unknown/repo")

        def _to_int(val: Any) -> int:
            try:
                return int(val)
            except (ValueError, TypeError):
                return 0

        stars = _to_int(raw.get("stars")) or _to_int(raw.get("star_gain"))
        forks = _to_int(raw.get("forks"))
        pushes = _to_int(raw.get("pushes"))
        description = (raw.get("description") or "").strip()
        period = raw.get("_period", "past_24_hours")
        lang = raw.get("primary_language") or raw.get("_language", "Python")

        title = f"{repo_name} (+{stars}⭐ {period.replace('_', ' ')})"
        url = f"https://github.com/{repo_name}"

        summary_lines = [
            f"Trending GitHub Repository: {repo_name}",
            f"Stars gained ({period}): +{stars} | Forks: {forks} | Pushes: {pushes} | Language: {lang}",
        ]
        if description:
            summary_lines.append(f"Description: {description}")

        full_content = "\n\n".join(summary_lines)

        metadata = {
            "source_name": "OSS Insight Trending",
            "repo_name": repo_name,
            "stars_gained": stars,
            "forks": forks,
            "pushes": pushes,
            "language": lang,
            "period": period,
            "source_type": SourceType.OSS_INSIGHT.value,
        }

        pub_at = raw.get("published_at") or datetime.now(UTC)

        return Entry(
            source_id=self.source.id,
            title=title,
            url=url,
            summary=full_content[:1000],
            content_hash=str(ContentHash.from_content(f"{repo_name}\n{url}")),
            category=Category.GITHUB_TRENDING,
            published_at=pub_at,
            metadata=metadata,
        )


fetcher_registry.register("oss_insight", OSSInsightFetcher)
