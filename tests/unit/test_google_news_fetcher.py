"""Unit tests for GoogleNewsFetcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.google_news_fetcher import (
    GoogleNewsFetcher,
)


@pytest.fixture
def google_news_source() -> Source:
    return Source(
        id=uuid4(),
        name="Google News AI",
        category=Category.AI_TECH,
        type=SourceType.GOOGLE_NEWS,
        query="vLLM OR Ollama",
        rate_limit_seconds=0,
        enabled=True,
    )


@pytest.mark.asyncio
async def test_google_news_fetcher_parses_feed(google_news_source: Source):
    """GoogleNewsFetcher should parse RSS search output and clean publisher suffix."""
    mock_rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Google News</title>
        <item>
          <title>vLLM 0.7.0 Released with SGLang Kernel Acceleration - TechWire</title>
          <link>https://news.google.com/rss/articles/CBMiZGh0dHBz...</link>
          <description>&lt;p&gt;High-throughput inference runtime updates.&lt;/p&gt;</description>
          <pubDate>Mon, 13 Oct 2026 12:00:00 GMT</pubDate>
          <source url="https://techwire.com">TechWire</source>
        </item>
      </channel>
    </rss>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_rss_xml

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        fetcher = GoogleNewsFetcher(google_news_source)
        result = await fetcher.fetch()

        assert result.status.value == "success"
        assert len(result.entries) == 1
        entry = result.entries[0]
        # Publisher stripped from clean title
        assert entry.title == "vLLM 0.7.0 Released with SGLang Kernel Acceleration"
        assert entry.metadata["publisher"] == "TechWire"
        assert entry.metadata["source_type"] == "google_news"
