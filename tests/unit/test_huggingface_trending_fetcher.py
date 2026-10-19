"""Unit tests for HuggingFaceTrendingFetcher and curated repo link extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.huggingface_trending_fetcher import (
    HuggingFaceTrendingFetcher,
)
from ai_security_monitor.infrastructure.fetchers.rss_fetcher import RSSFetcher

HF_TRENDING_RESPONSE = {
    "recentlyTrending": [
        {
            "repoData": {
                "id": "deepseek-ai/DeepSeek-V3",
                "author": "deepseek-ai",
                "downloads": 125000,
                "likes": 8400,
                "pipeline_tag": "text-generation",
                "type": "model",
            }
        },
        {
            "repoData": {
                "id": "vllm-project/vllm",
                "author": "vllm-project",
                "downloads": 540000,
                "likes": 12000,
                "pipeline_tag": "feature-extraction",
                "type": "model",
            }
        },
    ]
}


@pytest.fixture
def hf_source() -> Source:
    return Source(
        id=uuid4(),
        name="Hugging Face Trending AI Models & Repos",
        category=Category.GITHUB_TRENDING,
        type=SourceType.HUGGINGFACE_TRENDING,
        url="https://huggingface.co/api/trending",
        rate_limit_seconds=0,
        config={"limit": 10},
    )


@pytest.mark.asyncio
async def test_hf_trending_fetch(hf_source: Source):
    fetcher = HuggingFaceTrendingFetcher(hf_source)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = HF_TRENDING_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        res = await fetcher.fetch()

    assert res.status.value == "success"
    assert len(res.entries) == 2
    entry = res.entries[0]
    assert "deepseek-ai/DeepSeek-V3" in entry.title
    assert entry.url == "https://huggingface.co/deepseek-ai/DeepSeek-V3"
    assert entry.metadata["downloads"] == 125000
    assert entry.metadata["provenance_type"] == "trending_repo"


@pytest.mark.asyncio
async def test_rss_curated_repo_link_extraction():
    source = Source(
        id=uuid4(),
        name="Reddit r/BestGitHubRepos (Trending Open-Source Projects)",
        category=Category.GITHUB_TRENDING,
        type=SourceType.RSS,
        url="https://www.reddit.com/r/BestGitHubRepos/.rss",
        rate_limit_seconds=0,
    )
    fetcher = RSSFetcher(source)

    # Mock XML containing a reddit post that links to a github repo
    mock_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>BestGitHubRepos</title>
      <entry>
        <title>OpenUI: The Open Standard for Generative UI (12k stars)</title>
        <link href="https://www.reddit.com/r/BestGitHubRepos/comments/12345/openui/"/>
        <updated>2026-10-18T10:00:00Z</updated>
        <content type="html">&lt;p&gt;Check out &lt;a href="https://github.com/thesysdev/openui"&gt;https://github.com/thesysdev/openui&lt;/a&gt; for generative UI.&lt;/p&gt;</content>
      </entry>
      <entry>
        <title>Never miss the best GitHub repos from this community</title>
        <link href="https://www.reddit.com/r/BestGitHubRepos/comments/99999/meta/"/>
        <updated>2026-10-18T11:00:00Z</updated>
        <content type="html">&lt;p&gt;Sign up for our newsletter.&lt;/p&gt;</content>
      </entry>
    </feed>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = mock_xml
    mock_resp.encoding = "utf-8"
    mock_resp.headers = {"content-type": "application/atom+xml"}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.rss_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        raw = await fetcher._fetch_raw()

    assert len(raw) == 1
    assert raw[0]["url"] == "https://github.com/thesysdev/openui"
    assert raw[0]["metadata"]["provenance_type"] == "trending_repo"
    assert raw[0]["metadata"]["curated_via"] == source.name
