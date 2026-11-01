"""Unit tests for TwitterXFetcher."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.twitter_x_fetcher import (
    TwitterXFetcher,
)


@pytest.fixture
def twitter_source() -> Source:
    return Source(
        id=uuid4(),
        name="Twitter/X Frontier AI Drops",
        category=Category.AI_MODELS,
        type=SourceType.TWITTER_X,
        url="https://x.com",
        rate_limit_seconds=0,
        enabled=True,
        config={
            "queries": [
                'site:x.com ("DeepSeek" OR "Claude") model when:14d',
            ],
            "fetch_limit": 10,
        },
    )


@pytest.mark.asyncio
async def test_twitter_x_fetcher_parses_tweets(twitter_source: Source):
    """TwitterXFetcher should fetch and parse live tweets, cleaning ' - X' and extracting handles."""
    recent_date = (datetime.now(UTC) - timedelta(days=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    mock_rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>X / Twitter AI Updates</title>
        <item>
          <title>🚀 DeepSeek-V4.1-Flash-1017 is here! Faster task completion by @deepseek_ai - X</title>
          <link>https://news.google.com/rss/articles/CBMi_test_link</link>
          <description>&lt;a href="https://x.com/deepseek_ai/status/123"&gt;DeepSeek-V4.1-Flash-1017 is here&lt;/a&gt;</description>
          <pubDate>{recent_date}</pubDate>
        </item>
      </channel>
    </rss>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_rss_xml

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        fetcher = TwitterXFetcher(twitter_source)
        result = await fetcher.fetch()

        assert result.status.value == "success"
        assert len(result.entries) == 1
        entry = result.entries[0]

        # Verify title cleaned of trailing ' - X'
        assert not entry.title.endswith("- X")
        assert "DeepSeek-V4.1" in entry.title

        # Verify handle extraction
        assert entry.metadata["author"] == "@deepseek_ai"
        assert entry.metadata["source_type"] == "twitter_x"
        assert entry.metadata["provenance_type"] == "tweet"
        assert entry.category == Category.AI_MODELS


@pytest.mark.asyncio
async def test_twitter_x_fetcher_filters_stale_tweets(twitter_source: Source):
    """TwitterXFetcher must reject tweets older than 14 days."""
    mock_stale_rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>X / Twitter AI Updates</title>
        <item>
          <title>Old GPT-4 release from 2023 - X</title>
          <link>https://news.google.com/rss/articles/CBMi_old_link</link>
          <description>Old news</description>
          <pubDate>Sun, 01 Jan 2023 12:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_stale_rss

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        fetcher = TwitterXFetcher(twitter_source)
        result = await fetcher.fetch()

        assert result.status.value == "success"
        assert len(result.entries) == 0
