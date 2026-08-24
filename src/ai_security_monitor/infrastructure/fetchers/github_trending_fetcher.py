# GitHub Trending Security repos fetcher.

import httpx
from datetime import datetime
from typing import Optional
from uuid import UUID
from bs4 import BeautifulSoup

from ai_security_monitor.domain.entities import Entry, Source, Category
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import BaseFetcher, fetcher_registry
from ai_security_monitor.config.settings import settings


class GitHubTrendingFetcher(BaseFetcher):
    """Fetcher for GitHub Trending security repositories."""

    @property
    def fetcher_type(self) -> str:
        return "github_trending"

    def __init__(self, source: Source, timeout: Optional[int] = None, max_retries: Optional[int] = None):
        super().__init__(source, timeout, max_retries)
        # Parse frequency from config (daily/weekly)
        self.frequency = source.config.get("frequency", "daily")

    async def _fetch_raw(self) -> list[dict]:
        since = self.frequency  # daily, weekly, monthly
        url = f"https://github.com/trending?since={since}"
        params = {"spoken_language_code": "en"}
        headers = {"User-Agent": settings.fetch.user_agent}

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

        soup = BeautifulSoup(response.content, "html.parser")
        repos = soup.find_all("article", class_="Box-row")
        entries = []

        for repo in repos[:30]:
            try:
                # Repo name and link
                h2 = repo.find("h2", class_="h3")
                if not h2:
                    continue
                a_tag = h2.find("a")
                if not a_tag:
                    continue

                repo_name = a_tag.get_text(strip=True).replace(" ", "")
                repo_url = "https://github.com" + a_tag["href"]

                # Description
                desc_tag = repo.find("p", class_="col-9")
                description = desc_tag.get_text(strip=True) if desc_tag else ""

                # Language
                lang_tag = repo.find("span", itemprop="programmingLanguage")
                language = lang_tag.get_text(strip=True) if lang_tag else ""

                # Stars today/this period
                stars_tag = repo.find("span", class_="d-inline-block float-sm-right")
                stars_text = stars_tag.get_text(strip=True) if stars_tag else ""

                # Build content
                content_parts = []
                if description:
                    content_parts.append(description)
                if language:
                    content_parts.append(f"Language: {language}")
                if stars_text:
                    content_parts.append(f"Stars: {stars_text}")

                content = "\n".join(content_parts)

                entries.append({
                    "title": f"Trending: {repo_name}",
                    "url": repo_url,
                    "content": content,
                    "published_at": datetime.utcnow(),
                    "tags": ["github", "trending", "security", self.frequency, language.lower() if language else ""],
                    "metadata": {
                        "repo_name": repo_name,
                        "language": language,
                        "stars_period": stars_text,
                        "frequency": self.frequency,
                    }
                })
            except Exception as e:
                print(f"Failed to parse GitHub trending repo: {e}")
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
            tags=[t for t in raw.get("tags", []) if t],
            metadata=raw.get("metadata", {}),
        )


fetcher_registry.register("github_trending", GitHubTrendingFetcher)
