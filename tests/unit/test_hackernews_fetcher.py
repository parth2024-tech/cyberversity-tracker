"""Unit tests for HackerNewsFetcher."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.hackernews_fetcher import (
    HackerNewsFetcher,
)

HN_API_RESPONSE = {
    "hits": [
        {
            "objectID": "12345",
            "title": "DeepSeek V3 achieves state-of-the-art results",
            "url": "https://deepseek.com/v3",
            "points": 500,
            "author": "hacker_jane",
            "num_comments": 120,
            "created_at": "2026-01-01T12:00:00Z",
            "story_text": None,
        },
        {
            "objectID": "67890",
            "title": "Show HN: llama.cpp now runs Llama 4 on CPU",
            "url": None,  # No URL — should fallback to HN item URL
            "points": 300,
            "author": "dev_bob",
            "num_comments": 80,
            "created_at": "2026-01-02T09:00:00Z",
            "story_text": "I built a tool that...",
        },
    ]
}


@pytest.fixture
def hn_source() -> Source:
    return Source(
        id=uuid4(),
        name="Hacker News AI",
        category=Category.AI_TECH,
        type=SourceType.RSS,  # HN uses hackernews type but inherits from Source
        url="https://hn.algolia.com/api/v1/search",
        query=None,
        rate_limit_seconds=0,
        enabled=True,
    )


@pytest.mark.asyncio
async def test_hackernews_fetcher_parses_hits(hn_source: Source):
    """HackerNewsFetcher should parse Algolia API hits into raw entries."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value=HN_API_RESPONSE)
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.hackernews_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        fetcher = HackerNewsFetcher(hn_source)
        raw = await fetcher._fetch_raw()

    assert len(raw) == 2
    assert raw[0]["title"] == "DeepSeek V3 achieves state-of-the-art results"
    assert raw[0]["url"] == "https://deepseek.com/v3"
    assert raw[0]["metadata"]["points"] == 500


@pytest.mark.asyncio
async def test_hackernews_fetcher_url_fallback(hn_source: Source):
    """When story URL is None, fetcher should use HN item URL as fallback."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value=HN_API_RESPONSE)
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.hackernews_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        fetcher = HackerNewsFetcher(hn_source)
        raw = await fetcher._fetch_raw()

    # Second entry has no URL, should fall back to HN item URL
    assert "67890" in raw[1]["url"]
    assert "news.ycombinator.com" in raw[1]["url"]


@pytest.mark.asyncio
async def test_hackernews_parse_entry(hn_source: Source):
    """_parse_entry should create valid Entry from raw dict."""
    fetcher = HackerNewsFetcher(hn_source)
    raw = {
        "title": "Claude 4 Released by Anthropic",
        "url": "https://anthropic.com/claude4",
        "content": "Points: 400 | Comments: 90 | Author: ai_fan",
        "published_at": datetime.now(UTC),
        "tags": ["hackernews", "ai", "llm"],
        "metadata": {
            "hn_id": "11111",
            "points": 400,
            "author": "ai_fan",
            "num_comments": 90,
        },
    }
    entry = fetcher._parse_entry(raw)
    assert entry.title == raw["title"]
    assert len(entry.content_hash) == 64
    assert "hackernews" in entry.tags
