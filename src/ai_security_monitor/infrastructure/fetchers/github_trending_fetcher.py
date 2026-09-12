# GitHub Trending Security repos fetcher.

from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry, Source
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)

logger = get_logger(__name__)


class GitHubTrendingFetcher(BaseFetcher):
    """Fetcher for GitHub Trending security repositories."""

    @property
    def fetcher_type(self) -> str:
        return "github_trending"

    def __init__(self, source: Source, timeout: int | None = None, max_retries: int | None = None):
        super().__init__(source, timeout, max_retries)
        # Parse frequency from config (daily/weekly)
        self.frequency = source.config.get("frequency", "daily")

    async def _fetch_raw(self) -> list[dict]:
        entries = []
        try:
            entries = await self._fetch_raw_scraping()
        except Exception:
            entries = []

        # If scraping returned few/no AI entries or failed, fetch from official GitHub Search API
        if len(entries) < 5:
            try:
                api_entries = await self._fetch_raw_api()
                existing_urls = {e["url"].lower() for e in entries}
                for ae in api_entries:
                    if ae["url"].lower() not in existing_urls:
                        entries.append(ae)
            except Exception:
                pass

        return entries

    async def _fetch_raw_scraping(self) -> list[dict]:
        since = self.frequency  # daily, weekly, monthly
        url = f"https://github.com/trending?since={since}"
        params = {"spoken_language_code": "en"}
        headers = {"User-Agent": settings.fetch.user_agent}

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
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

                # Enforce strict AI filter to guarantee feed quality
                combined_info = f"{repo_name} {description}".lower()
                ai_keywords = (
                    "ai", "llm", "agent", "agents", "machine-learning", "deep-learning",
                    "neural", "model", "models", "gpt", "transformer", "transformers",
                    "diffusion", "rag", "vision", "deepseek", "qwen", "claude", "llama",
                    "mistral", "vllm", "ollama", "sglang", "embedding", "embeddings",
                    "inference", "fine-tuning", "lora", "rlhf", "langchain", "llamaindex",
                    "gemini", "pytorch", "huggingface", "whisper", "vision-language", "multimodal"
                )
                if not any(w in combined_info for w in ai_keywords):
                    continue

                clean_title = f"{repo_name}: {description[:80]}..." if description and len(description) > 10 else f"Trending Repo: {repo_name}"
                tags = ["github", "trending", "open-source", "ai", self.frequency]
                if language:
                    tags.append(language.lower())

                entries.append({
                    "title": clean_title,
                    "url": repo_url,
                    "content": content,
                    "published_at": datetime.now(UTC),
                    "tags": tags,
                    "metadata": {
                        "repo_name": repo_name,
                        "language": language,
                        "stars_period": stars_text,
                        "frequency": self.frequency,
                    }
                })
            except Exception as e:
                logger.warning(f"Failed to parse GitHub trending repo: {e}")
                continue

        return entries

    async def _fetch_raw_api(self) -> list[dict]:
        """Fetch trending AI repositories using GitHub REST Search API."""
        from datetime import timedelta
        now = datetime.now(UTC)
        days = 2 if self.frequency == "daily" else 8
        since_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")

        url = "https://api.github.com/search/repositories"
        headers = {
            "User-Agent": "AetherGuard-AI-Monitor/1.0",
            "Accept": "application/vnd.github.v3+json",
        }
        params = {
            "q": f"stars:>100 pushed:>={since_date} topic:ai",
            "sort": "stars",
            "order": "desc",
            "per_page": 30,
        }

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                params["q"] = "stars:>500 topic:llm OR topic:ai-agents OR topic:inference"
                params["sort"] = "updated"
                response = await client.get(url, params=params)
                response.raise_for_status()

        data = response.json()
        items = data.get("items", [])
        entries = []

        for repo in items[:30]:
            try:
                repo_name = repo.get("full_name", "")
                repo_url = repo.get("html_url", "")
                description = (repo.get("description") or "").strip()
                language = repo.get("language") or ""
                stars = repo.get("stargazers_count", 0)
                forks = repo.get("forks_count", 0)
                topics = repo.get("topics", [])

                content_parts = []
                if description:
                    content_parts.append(description)
                if language:
                    content_parts.append(f"Language: {language}")
                content_parts.append(f"Stars: {stars:,} | Forks: {forks:,}")
                if topics:
                    content_parts.append(f"Topics: {', '.join(topics[:8])}")
                content = "\n".join(content_parts)

                clean_title = f"{repo_name}: {description[:80]}..." if description and len(description) > 10 else f"Trending Repo: {repo_name}"
                tags = ["github", "trending", "open-source", "ai", self.frequency]
                if language:
                    tags.append(language.lower())
                tags.extend([t.lower() for t in topics[:5]])

                published_at = datetime.now(UTC)
                if repo.get("pushed_at"):
                    try:
                        published_at = datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        pass

                entries.append({
                    "title": clean_title,
                    "url": repo_url,
                    "content": content,
                    "published_at": published_at,
                    "tags": list(dict.fromkeys(tags)),
                    "metadata": {
                        "repo_name": repo_name,
                        "language": language,
                        "stars": stars,
                        "forks": forks,
                        "frequency": self.frequency,
                    }
                })
            except Exception:
                continue

        return entries

    def _parse_entry(self, raw: dict) -> Entry:
        repo_ident = raw.get("metadata", {}).get("repo_name") or raw["url"]
        content_hash = ContentHash.from_content(
            "github_repo",
            repo_ident.lower().strip(),
            raw["url"].lower().strip(),
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
