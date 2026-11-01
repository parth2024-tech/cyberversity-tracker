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

import re
from datetime import UTC, datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry, Source
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)

logger = get_logger(__name__)

_AI_KEYWORDS = frozenset(
    {
        # Core AI/ML
        "ai",
        "llm",
        "agent",
        "agents",
        "machine-learning",
        "deep-learning",
        "neural",
        "model",
        "models",
        "transformer",
        "transformers",
        "diffusion",
        "rag",
        "vision",
        "multimodal",
        "reasoning",
        "benchmark",
        "embedding",
        "embeddings",
        "inference",
        "fine-tuning",
        "lora",
        "rlhf",
        # Major labs / brands
        "openai",
        "anthropic",
        "deepseek",
        "qwen",
        "claude",
        "llama",
        "mistral",
        "gemini",
        "gemma",
        "grok",
        "kimi",
        "moonshot",
        "internlm",
        "phi",
        "falcon",
        "huggingface",
        "pytorch",
        # Frontier model keywords
        "o1",
        "o3",
        "gpt-4",
        "gpt-5",
        "llama3",
        "deepseek-r1",
        "deepseek-v3",
        # Inference runtimes
        "vllm",
        "ollama",
        "sglang",
        "llamacpp",
        "llama.cpp",
        "tensorrt",
        "tensorrt-llm",
        "nim",
        "triton",
        "flashattention",
        "flash-attn",
        "mlx",
        "rocm",
        # Training / fine-tuning
        "dpo",
        "grpo",
        "sft",
        "qlora",
        "peft",
        "alignment",
        "unsloth",
        "axolotl",
        "finetuning",
        "pretraining",
        # Frameworks and libraries
        "langchain",
        "llamaindex",
        "langgraph",
        "autogen",
        "crewai",
        "litellm",
        "openrouter",
        "haystack",
        "dspy",
        # Vector stores / RAG infra
        "chroma",
        "chromadb",
        "qdrant",
        "weaviate",
        "milvus",
        "pinecone",
        "faiss",
        # Media generation
        "whisper",
        "stable-diffusion",
        "sdxl",
        "flux",
        "comfyui",
        "tts",
        "stt",
        "text-to-image",
        "text-to-video",
        "vision-language",
        # Agentic / automation
        "agentic",
        "tool-calling",
        "function-calling",
        "workflow",
        "autonomous",
        "swarm",
        "orchestration",
        # Hardware / acceleration
        "cuda",
        "gpu",
        "npu",
        "accelerator",
        "quantization",
        "gguf",
        "ggml",
        "awq",
        "gptq",
        "fp8",
        "fp4",
        "fp16",
        "int8",
        "int4",
        # Modalities / domains
        "robotics",
        "embodied",
        "humanoid",
        "speech",
        # Evaluation / research
        "arxiv",
        "preprint",
        "dataset",
        "evaluate",
        "leaderboard",
        # Chinese AI & open-source developer terms
        "大模型",
        "大语言模型",
        "开源",
        "模型",
        "深度学习",
        "机器学习",
        "智能体",
        "推理",
        "知识库",
        "多模态",
        "微调",
        "量化",
        "算力",
        "提示词",
        "嵌入",
        "向量",
        "代码助手",
        "计算机视觉",
        "生成式",
        "自然语言",
        "神经网络",
        "预训练",
        "对齐",
        "语料",
        "检索增强",
        "测试时计算",
        "架构",
        "通义千问",
        "深度求索",
        "智谱",
        "月之暗面",
        "百川",
        "阶跃星辰",
        "零一万物",
        "商汤",
        "百度",
        "飞桨",
        "字节跳动",
        "腾讯",
        "清华",
        # Chinese Labs & Repos
        "chatglm",
        "glm",
        "baichuan",
        "minimax",
        "stepfun",
        "sensenova",
        "ernie",
        "paddlepaddle",
        "fastgpt",
        "ragflow",
        "huixiangdou",
        "chatchat",
        "db-gpt",
        "bisheng",
        "chattts",
        "cosyvoice",
        "fish-speech",
        "sherpa-onnx",
    }
)

_INFRA_KEYWORDS = frozenset(
    {
        "inference",
        "serving",
        "runtime",
        "engine",
        "framework",
        "deploy",
        "quantization",
        "optimization",
        "accelerator",
        "cuda",
        "triton",
        "vllm",
        "sglang",
        "ollama",
        "llamacpp",
        "onnx",
        "trt",
        "tensorrt",
        "mlops",
        "vector",
        "embedding",
        "rag",
        "retrieval",
        "monitoring",
        "training",
        "fine-tuning",
        "lora",
        "qlora",
        "peft",
        "accelerate",
    }
)

_SECURITY_KEYWORDS = frozenset(
    {
        "security",
        "pentest",
        "exploit",
        "vulnerability",
        "scanner",
        "fuzzer",
        "red-team",
        "blue-team",
        "cve",
        "ctf",
        "malware",
        "forensics",
        "siem",
        "ids",
        "ips",
        "waf",
        "recon",
        "osint",
        "threat",
        "detection",
        "edr",
    }
)


class GitHubTrendingFetcher(BaseFetcher):
    """Fetcher for GitHub Trending repositories with per-source filter modes."""

    @property
    def fetcher_type(self) -> str:
        return "github_trending"

    def __init__(
        self, source: Source, timeout: int | None = None, max_retries: int | None = None
    ):
        super().__init__(source, timeout, max_retries)
        self.frequency: str = source.config.get("frequency", "daily")
        self.language: str | None = source.config.get("language")
        # filter_mode: "ai" | "infra" | "security" | "any"
        self.filter_mode: str = source.config.get("filter_mode", "ai")
        self.spoken_language_code: str | None = source.config.get(
            "spoken_language_code"
        )
        self.region: str = source.config.get("region", "global")
        self.country: str = source.config.get("country", "GLOBAL")

    async def _fetch_raw(self) -> list[dict]:
        entries: list[dict] = []
        scrape_failed = False

        try:
            entries = await self._fetch_raw_scraping()
        except Exception as scrape_err:
            logger.warning(
                f"GitHub Trending scraping exception for {self.source.name!r}: {scrape_err}"
            )
            scrape_failed = True

        # Trigger API fallback if scraping returned too few results
        if len(entries) < 8:
            reason = (
                "scraping exception"
                if scrape_failed
                else f"low yield ({len(entries)} repos found)"
            )
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
                logger.error(
                    f"GitHub Search API fallback failed for {self.source.name!r}: {api_err}"
                )

        return entries

    def _passes_filter(self, repo_name: str, description: str) -> bool:
        """Apply per-source keyword filter based on filter_mode config."""
        if self.filter_mode == "any":
            return True

        combined = f"{repo_name} {description}".lower()

        if self.filter_mode == "security":
            return any(w in combined for w in _SECURITY_KEYWORDS)
        elif self.filter_mode == "infra":
            return any(w in combined for w in _INFRA_KEYWORDS) or any(
                w in combined for w in _AI_KEYWORDS
            )
        else:  # "ai" (default)
            return any(w in combined for w in _AI_KEYWORDS)

    async def _fetch_raw_scraping(self) -> list[dict]:
        since = self.frequency  # daily, weekly, monthly
        target_urls: list[str] = []
        if self.language:
            target_urls.append(
                f"https://github.com/trending/{self.language}?since={since}"
            )
        else:
            target_urls.append(f"https://github.com/trending?since={since}")
            target_urls.append(f"https://github.com/trending/python?since={since}")

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X-UA-Compatible; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="133", "Google Chrome";v="133"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Linux"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Referer": "https://github.com/explore",
        }

        all_entries: list[dict] = []
        seen_urls: set[str] = set()

        scrape_params: dict[str, str] = {}
        if self.spoken_language_code and self.spoken_language_code not in ("any", "all"):
            scrape_params["spoken_language_code"] = self.spoken_language_code
        elif self.spoken_language_code is None:
            scrape_params["spoken_language_code"] = "en"

        async with httpx.AsyncClient(
            timeout=self.timeout or 25.0, headers=headers, follow_redirects=True
        ) as client:
            for url in target_urls:
                try:
                    response = await client.get(
                        url, params=scrape_params if scrape_params else None
                    )
                    if response.status_code != 200:
                        continue
                    soup = BeautifulSoup(response.content, "html.parser")
                    page_entries = self._parse_soup_repos(soup)
                    for pe in page_entries:
                        u = pe["url"].lower()
                        if u not in seen_urls:
                            seen_urls.add(u)
                            all_entries.append(pe)
                except Exception as page_err:
                    logger.debug(
                        f"GitHub Trending scraping notice on {url}: {page_err}"
                    )

        return all_entries

    def _parse_soup_repos(self, soup: BeautifulSoup) -> list[dict]:
        """Parse repository cards from BeautifulSoup tree."""
        # Multi-strategy adaptive element extraction (inspired by Scrapling)
        repos = soup.find_all("article", class_="Box-row")
        if not repos:
            repos = soup.find_all("article")
        if not repos:
            candidate_links = soup.find_all(
                "a", href=re.compile(r"^/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")
            )
            seen_containers: set[int] = set()
            for link in candidate_links:
                container = link.find_parent("article") or link.find_parent(
                    "div", class_=re.compile(r"row|box", re.I)
                )
                if container and id(container) not in seen_containers:
                    seen_containers.add(id(container))
                    repos.append(container)

        entries: list[dict] = []

        for repo in repos[:30]:
            try:
                # Adaptive repo link extraction
                a_tag = None
                h_tag = repo.find(["h1", "h2", "h3"])
                if h_tag:
                    a_tag = h_tag.find(
                        "a", href=re.compile(r"^/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")
                    )
                if not a_tag:
                    a_tag = repo.find(
                        "a", href=re.compile(r"^/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")
                    )
                if not a_tag:
                    continue

                repo_name = a_tag.get_text(strip=True).replace(" ", "").strip("/")
                repo_url = "https://github.com/" + str(a_tag["href"]).lstrip("/")

                desc_tag = repo.find("p", class_="col-9") or repo.find("p")
                description = desc_tag.get_text(strip=True) if desc_tag else ""

                lang_tag = repo.find(
                    "span", itemprop="programmingLanguage"
                ) or repo.find("span", class_=re.compile(r"language", re.I))
                language = lang_tag.get_text(strip=True) if lang_tag else ""

                stars_tag = repo.find(
                    "span", class_="d-inline-block float-sm-right"
                ) or repo.find("a", href=re.compile(r"/stargazers$"))
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
                if self.spoken_language_code == "zh" or self.region == "china":
                    tags.extend(["china", "chinese", "chinese-ai"])

                entries.append(
                    {
                        "title": clean_title,
                        "url": repo_url,
                        "content": content,
                        "published_at": datetime.now(UTC),
                        "tags": list(dict.fromkeys(tags)),
                        "metadata": {
                            "repo_name": repo_name,
                            "language": language,
                            "stars_period": stars_text,
                            "frequency": self.frequency,
                            "filter_mode": self.filter_mode,
                            "region": self.region,
                            "country": self.country,
                            "spoken_language_code": self.spoken_language_code
                            or ("zh" if self.region == "china" else "en"),
                            "provenance_type": "trending_repo",
                        },
                    }
                )
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
        days_map = {"daily": 2, "weekly": 7, "monthly": 14}
        days = min(days_map.get(self.frequency, 2), 14)
        since_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")

        # Build topic filter per mode
        if self.filter_mode == "security":
            topic_filter = (
                "topic:security OR topic:pentest OR topic:red-team OR topic:osint"
            )
            stars_floor = "stars:>50"
        elif self.filter_mode == "infra":
            topic_filter = (
                "topic:inference OR topic:llm OR topic:mlops OR "
                "topic:machine-learning OR topic:deep-learning"
            )
            stars_floor = "stars:>100"
        elif self.spoken_language_code == "zh" or self.region == "china":
            topic_filter = (
                "topic:chinese-llm OR topic:llm OR topic:ai OR topic:ai-agents OR "
                "topic:rag OR topic:deep-learning"
            )
            stars_floor = "stars:>50"
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

        # Primary query: frequency-aligned recency + language + topic
        lang_filter = f"language:{self.language} " if self.language else ""
        params: dict[str, str | int] = {
            "q": f"{stars_floor} pushed:>={since_date} {lang_filter}{topic_filter.split(' OR ')[0]}",
            "sort": "stars",
            "order": "desc",
            "per_page": 30,
        }

        async with httpx.AsyncClient(
            timeout=self.timeout or 25.0, headers=headers
        ) as client:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                # Fallback query: relax to just topic + language + stars
                params["q"] = f"stars:>200 {lang_filter}({topic_filter})"
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
                if self.spoken_language_code == "zh" or self.region == "china":
                    tags.extend(["china", "chinese", "chinese-ai"])
                tags.extend(t.lower() for t in topics[:5])

                published_at = datetime.now(UTC)
                if repo.get("pushed_at"):
                    try:
                        published_at = datetime.fromisoformat(
                            repo["pushed_at"].replace("Z", "+00:00")
                        )
                        if published_at.tzinfo is None:
                            published_at = published_at.replace(tzinfo=UTC)
                    except Exception:
                        pass

                entries.append(
                    {
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
                            "region": self.region,
                            "country": self.country,
                            "spoken_language_code": self.spoken_language_code
                            or ("zh" if self.region == "china" else "en"),
                            "provenance_type": "trending_repo",
                        },
                    }
                )
            except Exception:
                continue

        return entries

    def _parse_entry(self, raw: dict) -> Entry:
        url_str = raw.get("url") or "https://github.com/trending"
        title_str = raw.get("title") or "Trending GitHub Repository"
        pub_at = raw.get("published_at") or datetime.now(UTC)
        repo_ident = (
            raw.get("metadata", {}).get("repo_name")
            if isinstance(raw.get("metadata"), dict)
            else None
        ) or url_str
        pub_date_str = (
            pub_at.strftime("%Y-%m-%d") if hasattr(pub_at, "strftime") else "trending"
        )
        content_hash = ContentHash.from_content(
            "github_trending",
            str(repo_ident).lower().strip(),
            url_str.lower().strip(),
            pub_date_str,
        )
        content = raw.get("content") or ""
        metadata = (
            dict(raw.get("metadata", {}))
            if isinstance(raw.get("metadata"), dict)
            else {}
        )
        if "region" not in metadata:
            metadata["region"] = self.region
        if "country" not in metadata:
            metadata["country"] = self.country
        if "spoken_language_code" not in metadata and self.spoken_language_code:
            metadata["spoken_language_code"] = self.spoken_language_code
        if "provenance_type" not in metadata:
            metadata["provenance_type"] = "trending_repo"

        return Entry(
            source_id=self.source.id,
            title=title_str,
            url=url_str,
            content_hash=str(content_hash),
            summary=content[:500] if content else title_str,
            published_at=pub_at,
            category=self.source.category,
            tags=[t for t in raw.get("tags", []) if t],
            metadata=metadata,
        )


fetcher_registry.register("github_trending", GitHubTrendingFetcher)
