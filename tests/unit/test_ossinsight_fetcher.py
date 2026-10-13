"""Unit tests for OSSInsightFetcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.ossinsight_fetcher import (
    OSSInsightFetcher,
)


@pytest.fixture
def ossinsight_source() -> Source:
    return Source(
        id=uuid4(),
        name="OSS Insight Trending",
        category=Category.GITHUB_TRENDING,
        type=SourceType.OSS_INSIGHT,
        rate_limit_seconds=0,
        enabled=True,
        config={"languages": ["Python"], "min_stars": 50},
    )


@pytest.mark.asyncio
async def test_ossinsight_fetcher_parses_trending_repos(ossinsight_source: Source):
    """OSSInsightFetcher should parse trending repository rows and extract star gains."""
    mock_json = {
        "data": {
            "rows": [
                {
                    "repo_name": "vllm-project/vllm",
                    "repo_id": 123456,
                    "stars": 420,
                    "forks": 85,
                    "pushes": 30,
                    "description": "A high-throughput and memory-efficient LLM serving engine",
                    "primary_language": "Python",
                },
                {
                    "repo_name": "boring/unrelated-repo",
                    "repo_id": 999999,
                    "stars": 2,  # Should be filtered out by min_stars
                    "forks": 0,
                    "pushes": 0,
                    "description": "random utility",
                    "primary_language": "Python",
                },
            ]
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_json

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        fetcher = OSSInsightFetcher(ossinsight_source)
        result = await fetcher.fetch()

        assert result.status.value == "success"
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert "vllm-project/vllm" in entry.title
        assert "+420⭐" in entry.title
        assert entry.url == "https://github.com/vllm-project/vllm"
        assert entry.category == Category.GITHUB_TRENDING
        assert entry.metadata["source_type"] == "oss_insight"
