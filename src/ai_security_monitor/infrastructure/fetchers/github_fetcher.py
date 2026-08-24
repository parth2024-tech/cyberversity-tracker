# GitHub Security Advisories fetcher.

import httpx
from datetime import datetime
from typing import Optional
from uuid import UUID

from ai_security_monitor.domain.entities import Entry, Source, Category
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import BaseFetcher, fetcher_registry
from ai_security_monitor.config.settings import settings


class GitHubAdvisoriesFetcher(BaseFetcher):
    """Fetcher for GitHub Security Advisories."""

    @property
    def fetcher_type(self) -> str:
        return "github_advisories"

    async def _fetch_raw(self) -> list[dict]:
        url = "https://api.github.com/advisories"
        params = {
            "per_page": 100,
            "direction": "desc",
            "sort": "published",
        }
        headers = {"User-Agent": settings.fetch.user_agent}

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

        data = response.json()
        entries = []

        for item in data:
            summary = item.get("summary", "")
            description = item.get("description", "")
            content = description or summary

            ghsa_id = item.get("ghsa_id", "")
            severity = item.get("severity", "unknown").upper()

            entries.append({
                "title": f"GHSA: {ghsa_id} - {summary[:200]}",
                "url": item.get("html_url", f"https://github.com/advisories/{ghsa_id}"),
                "content": content,
                "published_at": datetime.fromisoformat(item.get("published_at", "").replace("Z", "+00:00")) if item.get("published_at") else datetime.utcnow(),
                "tags": ["github", "advisory", severity.lower()],
                "metadata": {
                    "ghsa_id": ghsa_id,
                    "cve_ids": item.get("cve_ids", []),
                    "severity": severity,
                    "vulnerabilities": item.get("vulnerabilities", []),
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


fetcher_registry.register("github_advisories", GitHubAdvisoriesFetcher)
