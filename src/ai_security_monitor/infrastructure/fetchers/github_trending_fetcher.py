"""GitHub Trending fetcher — top-tier, configurable filter modes.

Architecture notes:
- Supports filter_mode config key: "ai" (default), "security", "infra", "any"
  This fixes GitHub Trending Security sources that returned 0 entries because
  the strict AI keyword filter excluded all security repos (nuclei, zaproxy, etc.)
- Weekly API fallback uses the correct time window (7 days for weekly, 2 for daily)
  and an expanded topic set to avoid 0-result API responses.
- GitHub Trending Security sources are repurposed as AI Infrastructure Tools
  (vLLM, llama.cpp, inference runtimes) per project directive.
"""

from datetime import UTC, datetime, timedelta

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

_AI_KEYWORDS = frozenset({
    "ai", "llm", "agent", "agents", "machine-learning", "deep-learning",
    "neural", "model", "models", "gpt", "transformer", "transformers",
    "diffusion", "rag", "vision", "deepseek", "qwen", "claude", "llama",
    "mistral", "vllm", "ollama", "sglang", "embedding", "embeddings",
    "inference", "fine-tuning", "lora", "rlhf", "langchain", "llamaindex",
    "gemini", "pytorch", "huggingface", "whisper", "vision-language",
    "multimodal", "openai", "anthropic", "reasoning", "benchmark",
})

_INFRA_KEYWORDS = frozenset({
    "inference", "serving", "runtime", "engine", "framework", "deploy",
    "quantization", "optimization", "accelerator", "cuda", "triton",
    "vllm", "sglang", "ollama", "llamacpp", "onnx", "trt", "tensorrt",
    "mlops", "vector", "embedding", "rag", "retrieval", "monitoring",
    "training", "fine-tuning", "lora", "qlora", "peft", "accelerate",
})

_SECURITY_KEYWORDS = frozenset({
    "security", "pentest", "exploit", "vulnerability", "scanner", "fuzzer",
    "red-team", "blue-team", "cve", "ctf", "malware", "forensics", "siem",
    "ids", "ips", "waf", "recon", "osint", "threat", "detection", "edr",
})


class GitHubTrendingFetcher(BaseFetcher):
    """Fetcher for GitHub Trending repositories with per-source filter modes."""

    @property
    def fetcher_type(self) -> str:
        return "github_trending"

    def __init__(self, source: Source, timeout: int | None = None, max_retries: int | None = None):
        super().__init__(source, timeout, max_retries)
        self.frequency: str = source.config.get("frequency", "daily")
        # filter_mode: "ai" | "infra" | "security" | "any"
        self.filter_mode: str = source.config.get("filter_mode", "ai")

    async def _fetch_raw(self) -> list[dict]:
        entries: list[dict] = []
        scrape_failed = False

        try:
            entries = await self._fetch_raw_scraping()
        except Exception as scrape_err:
            logger.warning(f"GitHub Trending scraping exception for {self.source.name!r}: {scrape_err}")
            scrape_failed = True

        # Trigger API fallback if scraping returned too few results
        if len(entries) < 5:
            reason = "scraping exception" if scrape_failed else f"low yield ({len(entries)} repos found)"
            logger.warning(
                f"GitHub Trending scrape health alert for {self.source.name!r}: {reason}. "
                "Activating GitHub Search API fallback."
            )
            try:
                api_entries = await self._fetch_raw_api()
                existing_urls = {e["url"].lower() for e in entries}
                added = 0
                for ae in api_entries:
                    if ae["url"].lower() not in existing_urls:
                        entries.append(ae)
                        added += 1
                logger.info(
                    f"GitHub Search API fallback enriched {self.source.name!r} "
                    f"with {added} additional repos"
                )
            except Exception as api_err:
                logger.error(f"GitHub Search API fallback failed for {self.source.name!r}: {api_err}")

        return entries

    def _passes_filter(self, repo_name: str, description: str) -> bool:
        """Apply per-source keyword filter based on filter_mode config."""
        if self.filter_mode == "any":
            return True

        combined = f"{repo_name} {description}".lower()

        if self.filter_mode == "security":
            return any(w in combined for w in _SECURITY_KEYWORDS)
        elif self.filter_mode == "infra":
            return any(w in combined for w in _INFRA_KEYWORDS) or any(w in combined for w in _AI_KEYWORDS)
        else:  # "ai" (default)
            return any(w in combined for w in _AI_KEYWORDS)

    async def _fetch_raw_scraping(self) -> list[dict]:
        since = self.frequency  # daily, weekly, monthly
        url = f"https://github.com/trending?since={since}"
        params = {"spoken_language_code": "en"}
        headers = {"User-Agent": settings.fetch.user_agent}

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=headers, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

        soup = BeautifulSoup(response.content, "html.parser")
        repos = soup.find_all("article", class_="Box-row")

        if not repos:
            logger.warning(
                f"GitHub Trending DOM health check failed for {self.source.name!r}: "
                "no 'article.Box-row' elements matched. GitHub layout may have updated."
            )
        elif len(repos) < 5:
            logger.info(
                f"GitHub Trending DOM health check: only {len(repos)} "
                "'article.Box-row' elements parsed."
            )

        entries: list[dict] = []

        for repo in repos[:30]:
            try:
                h2 = repo.find("h2", class_="h3")
                if not h2:
                    continue
                a_tag = h2.find("a")
                if not a_tag:
                    continue

                repo_name = a_tag.get_text(strip=True).replace(" ", "")
                repo_url = "https://github.com" + a_tag["href"]

                desc_tag = repo.find("p", class_="col-9")
                description = desc_tag.get_text(strip=True) if desc_tag else ""

                lang_tag = repo.find("span", itemprop="programmingLanguage")
                language = lang_tag.get_text(strip=True) if lang_tag else ""

                stars_tag = repo.find("span", class_="d-inline-block float-sm-right")
                stars_text = stars_tag.get_text(strip=True) if stars_tag else ""

                if not self._passes_filter(repo_name, description):
                    continue

                content_parts = []
                if description:
                    content_parts.append(description)
                if language:
                    content_parts.append(f"Language: {language}")
                if stars_text:
                    content_parts.append(f"Stars: {stars_text}")
                content = "\n".join(content_parts)

                clean_title = (
                    f"{repo_name}: {description[:80]}..."
                    if description and len(description) > 10
                    else f"Trending Repo: {repo_name}"
                )
                tags = ["github", "trending", "open-source", self.frequency]
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
                        "filter_mode": self.filter_mode,
                    },
                })
            except Exception as e:
                logger.warning(f"Failed to parse GitHub trending repo: {e}")
                continue

        return entries

    async def _fetch_raw_api(self) -> list[dict]:
        """Fetch trending repositories using GitHub REST Search API.

        Uses frequency-aligned time windows:
        - daily  → pushed in last 2 days
        - weekly → pushed in last 8 days  (7 + 1 buffer)
        - monthly → pushed in last 32 days

        Topic filter is expanded per filter_mode to avoid 0-result API responses.
        """
        now = datetime.now(UTC)
        days_map = {"daily": 2, "weekly": 8, "monthly": 32}
        days = days_map.get(self.frequency, 2)
        since_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")

        # Build topic filter per mode
        if self.filter_mode == "security":
            topic_filter = "topic:security OR topic:pentest OR topic:red-team OR topic:osint"
            stars_floor = "stars:>50"
        elif self.filter_mode == "infra":
            topic_filter = (
                "topic:inference OR topic:llm OR topic:mlops OR "
                "topic:machine-learning OR topic:deep-learning"
            )
            stars_floor = "stars:>100"
        else:  # "ai" or "any"
            topic_filter = (
                "topic:ai OR topic:llm OR topic:ai-agents OR "
                "topic:machine-learning OR topic:deep-learning"
            )
            stars_floor = "stars:>100"

        url = "https://api.github.com/search/repositories"
        headers = {
            "User-Agent": "AetherGuard-AI-Monitor/2.0",
            "Accept": "application/vnd.github.v3+json",
        }

        # Primary query: frequency-aligned recency + topic
        params = {
            "q": f"{stars_floor} pushed:>={since_date} {topic_filter.split(' OR ')[0]}",
            "sort": "stars",
            "order": "desc",
            "per_page": 30,
        }

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                # Fallback query: relax to just topic + high stars
                params["q"] = f"stars:>500 {topic_filter}"
                params["sort"] = "updated"
                response = await client.get(url, params=params)
                if response.status_code != 200:
                    response.raise_for_status()

        data = response.json()
        items = data.get("items", [])
        entries: list[dict] = []

        for repo in items[:30]:
            try:
                repo_name = repo.get("full_name", "")
                repo_url = repo.get("html_url", "")
                description = (repo.get("description") or "").strip()
                language = repo.get("language") or ""
                stars = repo.get("stargazers_count", 0)
                forks = repo.get("forks_count", 0)
                topics = repo.get("topics", [])

                if not self._passes_filter(repo_name, description):
                    continue

                content_parts = []
                if description:
                    content_parts.append(description)
                if language:
                    content_parts.append(f"Language: {language}")
                content_parts.append(f"Stars: {stars:,} | Forks: {forks:,}")
                if topics:
                    content_parts.append(f"Topics: {', '.join(topics[:8])}")
                content = "\n".join(content_parts)

                clean_title = (
                    f"{repo_name}: {description[:80]}..."
                    if description and len(description) > 10
                    else f"Trending Repo: {repo_name}"
                )
                tags = ["github", "trending", "open-source", self.frequency]
                if language:
                    tags.append(language.lower())
                tags.extend(t.lower() for t in topics[:5])

                published_at = datetime.now(UTC)
                if repo.get("pushed_at"):
                    try:
                        published_at = datetime.fromisoformat(
                            repo["pushed_at"].replace("Z", "+00:00")
                        ).replace(tzinfo=None)
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
                        "filter_mode": self.filter_mode,
                    },
                })
            except Exception:
                continue

        return entries

    def _parse_entry(self, raw: dict) -> Entry:
        repo_ident = raw.get("metadata", {}).get("repo_name") or raw["url"]
        pub_date_str = (
            raw["published_at"].strftime("%Y-%m-%d")
            if hasattr(raw.get("published_at"), "strftime")
            else "trending"
        )
        content_hash = ContentHash.from_content(
            "github_trending",
            repo_ident.lower().strip(),
            raw["url"].lower().strip(),
            pub_date_str,
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
