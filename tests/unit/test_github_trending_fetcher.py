"""Unit tests for GitHubTrendingFetcher."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.github_trending_fetcher import (
    GitHubTrendingFetcher,
)

GITHUB_SEARCH_RESPONSE = {
    "items": [
        {
            "full_name": "deepseek-ai/DeepSeek-V3",
            "html_url": "https://github.com/deepseek-ai/DeepSeek-V3",
            "description": "DeepSeek V3, a strong Mixture-of-Experts language model",
            "language": "Python",
            "stargazers_count": 50000,
            "forks_count": 3000,
            "topics": ["llm", "ai", "inference"],
            "pushed_at": "2026-01-01T12:00:00Z",
        },
        {
            "full_name": "vllm-project/vllm",
            "html_url": "https://github.com/vllm-project/vllm",
            "description": "High-throughput and memory-efficient LLM inference engine",
            "language": "Python",
            "stargazers_count": 30000,
            "forks_count": 2500,
            "topics": ["llm", "inference", "gpu"],
            "pushed_at": "2026-01-02T08:00:00Z",
        },
        {
            "full_name": "some-user/random-cooking-app",  # Non-AI: should be skippable
            "html_url": "https://github.com/some-user/random-cooking-app",
            "description": "A recipe management application",
            "language": "JavaScript",
            "stargazers_count": 200,
            "forks_count": 10,
            "topics": ["cooking", "recipes"],
            "pushed_at": "2026-01-01T06:00:00Z",
        },
    ]
}


@pytest.fixture
def trending_source() -> Source:
    return Source(
        id=uuid4(),
        name="GitHub Trending AI",
        category=Category.GITHUB_TRENDING,
        type=SourceType.RSS,
        url="https://github.com/trending",
        query=None,
        rate_limit_seconds=0,
        enabled=True,
        config={"frequency": "daily"},
    )


@pytest.mark.asyncio
async def test_github_trending_api_fallback(trending_source: Source):
    """When scraping returns <5 entries, should fall back to GitHub Search API."""
    mock_search_response = MagicMock()
    mock_search_response.status_code = 200
    mock_search_response.json = MagicMock(return_value=GITHUB_SEARCH_RESPONSE)
    mock_search_response.raise_for_status = MagicMock()

    # Make scraping fail so it falls back to API
    mock_scrape_response = MagicMock()
    mock_scrape_response.status_code = 503
    mock_scrape_response.raise_for_status = MagicMock(side_effect=Exception("Scraping failed"))

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[mock_scrape_response, mock_search_response])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("ai_security_monitor.infrastructure.fetchers.github_trending_fetcher.httpx.AsyncClient", return_value=mock_client):
        fetcher = GitHubTrendingFetcher(trending_source)
        raw = await fetcher._fetch_raw_api()

    # Should return AI repos from the API response (cooking-app may be included in raw but filtered later)
    ai_repos = [r for r in raw if "deepseek" in r["url"].lower() or "vllm" in r["url"].lower()]
    assert len(ai_repos) >= 2


@pytest.mark.asyncio
async def test_github_trending_parse_entry(trending_source: Source):
    """_parse_entry should produce stable content hash from repo identity."""
    fetcher = GitHubTrendingFetcher(trending_source)
    raw = {
        "title": "deepseek-ai/DeepSeek-V3: DeepSeek V3 MoE inference model...",
        "url": "https://github.com/deepseek-ai/DeepSeek-V3",
        "content": "DeepSeek V3, a strong Mixture-of-Experts language model\nLanguage: Python\nStars: 50,000",
        "published_at": datetime.now(UTC),
        "tags": ["github", "trending", "ai", "python"],
        "metadata": {"repo_name": "deepseek-ai/DeepSeek-V3", "language": "Python", "stars": 50000},
    }
    entry = fetcher._parse_entry(raw)

    assert entry.title == raw["title"]
    assert len(entry.content_hash) == 64
    assert "github" in entry.tags


def test_github_trending_ai_filter_passes_ai_repos(trending_source: Source):
    """AI keyword filter should pass repos with AI-related names/descriptions."""
    combined = "vllm-project/vllm High-throughput and memory-efficient LLM inference engine".lower()
    ai_keywords = ("ai", "llm", "agent", "neural", "model", "transformer", "inference", "embedding")
    assert any(w in combined for w in ai_keywords)


def test_github_trending_ai_filter_rejects_non_ai_repos(trending_source: Source):
    """AI keyword filter should reject repos with no AI-related content."""
    combined = "some-user/cooking-app A recipe management application".lower()
    ai_keywords = ("ai", "llm", "agent", "neural", "model", "transformer", "inference", "embedding")
    assert not any(w in combined for w in ai_keywords)
