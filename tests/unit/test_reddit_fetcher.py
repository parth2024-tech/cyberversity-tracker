"""Unit tests for RedditFetcher."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.reddit_fetcher import RedditFetcher


@pytest.fixture
def reddit_source() -> Source:
    return Source(
        id=uuid4(),
        name="Reddit AI Subreddits",
        category=Category.AI_TECH,
        type=SourceType.REDDIT,
        url="https://www.reddit.com/r/LocalLLaMA",
        rate_limit_seconds=0,
        enabled=True,
        config={
            "subreddits": ["LocalLLaMA"],
            "fetch_limit": 5,
            "include_comments": True,
        },
    )


@pytest.mark.asyncio
async def test_reddit_fetcher_parses_posts_and_comments(reddit_source: Source):
    """RedditFetcher should correctly parse Reddit JSON posts and attach top comments."""
    mock_post_json = {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "abc1234",
                        "title": "DeepSeek R1 full weights running on Ollama and vLLM",
                        "permalink": "/r/LocalLLaMA/comments/abc1234/deepseek_r1/",
                        "url": "https://github.com/deepseek-ai/DeepSeek-R1",
                        "selftext": "Here is our benchmark on local hardware.",
                        "score": 450,
                        "num_comments": 85,
                        "author": "local_dev",
                        "created_utc": datetime.now(UTC).timestamp(),
                        "stickied": False,
                    }
                }
            ]
        }
    }

    mock_comment_json = [
        {},
        {
            "data": {
                "children": [
                    {
                        "data": {
                            "author": "eval_expert",
                            "body": "Tested with 4-bit quant, inference throughput is impressive.",
                        }
                    }
                ]
            }
        },
    ]

    mock_resp_posts = MagicMock()
    mock_resp_posts.status_code = 200
    mock_resp_posts.json.return_value = mock_post_json

    mock_resp_comments = MagicMock()
    mock_resp_comments.status_code = 200
    mock_resp_comments.json.return_value = mock_comment_json

    async def fake_get(url, *args, **kwargs):
        if "comments" in url:
            return mock_resp_comments
        return mock_resp_posts

    with patch("httpx.AsyncClient.get", side_effect=fake_get):
        fetcher = RedditFetcher(reddit_source)
        result = await fetcher.fetch()

        assert result.status.value == "success"
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert "DeepSeek R1" in entry.title
        assert "eval_expert" in entry.summary
        assert entry.metadata["score"] == 450
        assert entry.metadata["source_type"] == "reddit"


@pytest.mark.asyncio
async def test_reddit_fetcher_fallback_on_429(reddit_source: Source):
    """When direct Reddit is throttled (429), fetcher should invoke search fallback."""
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429

    mock_resp_rss = MagicMock()
    mock_resp_rss.status_code = 200
    mock_resp_rss.text = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Reddit Search</title>
        <item>
          <title>Llama 4 preview benchmarks on 8x H100 - Reddit</title>
          <link>https://www.reddit.com/r/LocalLLaMA/comments/xyz123/llama_4/</link>
          <description>Throughput tests on local clusters.</description>
          <pubDate>Mon, 19 Oct 2026 12:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """

    async def fake_get(url, *args, **kwargs):
        if "google.com" in url:
            return mock_resp_rss
        return mock_resp_429

    with patch("httpx.AsyncClient.get", side_effect=fake_get):
        fetcher = RedditFetcher(reddit_source)
        result = await fetcher.fetch()

        assert result.status.value == "success"
        assert len(result.entries) >= 1
        entry = result.entries[0]
        assert "Llama 4" in entry.title
        assert "Throughput tests" in entry.summary
        assert entry.metadata["source_type"] == "reddit"


def test_reddit_fetcher_handles_none_and_malformed_scores(reddit_source: Source):
    """RedditFetcher._parse_entry should gracefully handle null or string scores without throwing TypeError or ValueError."""
    fetcher = RedditFetcher(reddit_source)
    raw_with_nulls = {
        "id": "null_post",
        "title": None,
        "permalink": "/r/LocalLLaMA/comments/null_post/",
        "score": None,
        "num_comments": None,
        "author": None,
        "created_utc": None,
    }
    entry = fetcher._parse_entry(raw_with_nulls)
    assert entry.metadata["score"] == 0
    assert entry.metadata["num_comments"] == 0
    assert entry.metadata["author"] == "redditor"
    assert entry.published_at is not None
    assert entry.title == "Untitled Reddit Post"

    raw_with_strings = {
        "id": "str_post",
        "title": "Post with string metrics",
        "permalink": "/r/LocalLLaMA/comments/str_post/",
        "score": "not_an_int",
        "num_comments": "invalid",
        "author": "tester",
    }
    entry_str = fetcher._parse_entry(raw_with_strings)
    assert entry_str.metadata["score"] == 0
    assert entry_str.metadata["num_comments"] == 0
