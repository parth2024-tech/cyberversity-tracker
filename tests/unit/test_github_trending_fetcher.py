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
    mock_scrape_response.raise_for_status = MagicMock(
        side_effect=Exception("Scraping failed")
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[mock_scrape_response, mock_search_response]
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.github_trending_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        fetcher = GitHubTrendingFetcher(trending_source)
        raw = await fetcher._fetch_raw_api()

    # Should return AI repos from the API response (cooking-app may be included in raw but filtered later)
    ai_repos = [
        r for r in raw if "deepseek" in r["url"].lower() or "vllm" in r["url"].lower()
    ]
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
        "metadata": {
            "repo_name": "deepseek-ai/DeepSeek-V3",
            "language": "Python",
            "stars": 50000,
        },
    }
    entry = fetcher._parse_entry(raw)

    assert entry.title == raw["title"]
    assert len(entry.content_hash) == 64
    assert "github" in entry.tags


def test_github_trending_ai_filter_passes_ai_repos(trending_source: Source):
    """AI keyword filter should pass repos with AI-related names/descriptions."""
    combined = "vllm-project/vllm High-throughput and memory-efficient LLM inference engine".lower()
    ai_keywords = (
        "ai",
        "llm",
        "agent",
        "neural",
        "model",
        "transformer",
        "inference",
        "embedding",
    )
    assert any(w in combined for w in ai_keywords)


def test_github_trending_ai_filter_rejects_non_ai_repos(trending_source: Source):
    """AI keyword filter should reject repos with no AI-related content."""
    combined = "some-user/cooking-app A recipe management application".lower()
    ai_keywords = (
        "ai",
        "llm",
        "agent",
        "neural",
        "model",
        "transformer",
        "inference",
        "embedding",
    )
    assert not any(w in combined for w in ai_keywords)


def test_github_trending_chinese_ai_filter():
    """Verify Chinese AI terms pass filter and non-AI terms are rejected."""
    src = Source(
        id=uuid4(),
        name="GitHub Trending Chinese AI",
        category=Category.GITHUB_TRENDING,
        type=SourceType.GITHUB_TRENDING,
        url="https://github.com/trending",
        rate_limit_seconds=0,
        enabled=True,
        config={"spoken_language_code": "zh", "region": "china", "country": "CN"},
    )
    fetcher = GitHubTrendingFetcher(src)
    assert fetcher.spoken_language_code == "zh"
    assert fetcher.region == "china"
    assert fetcher.country == "CN"

    # AI & developer tool repo descriptions in Chinese
    assert fetcher._passes_filter("infiniflow/ragflow", "开源多模态深度文档理解与检索增强生成引擎") is True
    assert fetcher._passes_filter("labring/FastGPT", "基于大模型的企业级智能体知识库问答系统") is True
    assert fetcher._passes_filter("THUDM/ChatGLM3", "清华大学开源双语预训练对话大模型") is True
    assert fetcher._passes_filter("2noise/ChatTTS", "针对对话场景优化的语音合成工具") is True

    # Non-AI repo description in Chinese
    assert fetcher._passes_filter("some-user/cookbook", "个人常用家常菜谱大全与烹饪笔记") is False


@pytest.mark.asyncio
async def test_github_trending_chinese_scraping_params():
    """Verify spoken_language_code=zh is passed as a query param in scraping."""
    src = Source(
        id=uuid4(),
        name="GitHub Trending Chinese AI",
        category=Category.GITHUB_TRENDING,
        type=SourceType.GITHUB_TRENDING,
        url="https://github.com/trending",
        rate_limit_seconds=0,
        enabled=True,
        config={"spoken_language_code": "zh", "region": "china", "country": "CN"},
    )
    fetcher = GitHubTrendingFetcher(src)

    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = "<html><body><article class='Box-row'><h2><a href='/test-org/ai-repo'>test-org/ai-repo</a></h2><p>开源大语言模型推理加速框架</p></article></body></html>".encode()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.github_trending_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        entries = await fetcher._fetch_raw_scraping()

    assert len(entries) == 1
    entry = entries[0]
    assert entry["url"] == "https://github.com/test-org/ai-repo"
    assert entry["metadata"]["region"] == "china"
    assert entry["metadata"]["country"] == "CN"
    assert entry["metadata"]["spoken_language_code"] == "zh"
    assert "china" in entry["tags"]
    assert "chinese" in entry["tags"]

    # Verify query param passed to httpx client
    calls = mock_client.get.call_args_list
    assert len(calls) > 0
    assert calls[0].kwargs.get("params") == {"spoken_language_code": "zh"}


@pytest.mark.asyncio
async def test_github_trending_chinese_api_fallback():
    """Verify Chinese topic search is executed during API fallback for Chinese sources."""
    src = Source(
        id=uuid4(),
        name="GitHub Trending Chinese AI",
        category=Category.GITHUB_TRENDING,
        type=SourceType.GITHUB_TRENDING,
        url="https://github.com/trending",
        rate_limit_seconds=0,
        enabled=True,
        config={"spoken_language_code": "zh", "region": "china", "country": "CN"},
    )
    fetcher = GitHubTrendingFetcher(src)

    mock_api_resp = MagicMock()
    mock_api_resp.status_code = 200
    mock_api_resp.json.return_value = {
        "items": [
            {
                "full_name": "datawhalechina/self-llm",
                "html_url": "https://github.com/datawhalechina/self-llm",
                "description": "开源大模型微调与实战开发教程",
                "language": "Python",
                "stargazers_count": 18000,
                "forks_count": 2200,
                "topics": ["chinese-llm", "ai", "tutorial"],
                "pushed_at": "2026-01-01T12:00:00Z",
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_api_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.github_trending_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        raw_entries = await fetcher._fetch_raw_api()

    assert len(raw_entries) == 1
    raw = raw_entries[0]
    assert raw["metadata"]["repo_name"] == "datawhalechina/self-llm"
    assert raw["metadata"]["region"] == "china"
    assert raw["metadata"]["country"] == "CN"
    assert raw["metadata"]["spoken_language_code"] == "zh"
    assert "china" in raw["tags"]

    parsed = fetcher._parse_entry(raw)
    assert parsed.metadata["region"] == "china"
    assert parsed.metadata["country"] == "CN"
    assert parsed.metadata["spoken_language_code"] == "zh"
    assert parsed.metadata["provenance_type"] == "trending_repo"
