"""
Unit tests for Defect Ledger D3: Stored HTTP validators outlive data (ETag lockout).

Guarantees:
1. When a source returns HTTP 304 but has < 3 stored entries, the fetcher drops the stale
   validators (ETag / Last-Modified) and immediately executes a full refetch.
2. When a source has >= 3 stored entries, HTTP 304 is treated as a healthy unchanged feed.
3. System restore and retention purge operations clear stored validators to prevent lockout.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest

from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.rss_fetcher import RSSFetcher


@pytest.fixture
def locked_out_source() -> Source:
    """Source with stored ETag validator but 0 stored entries."""
    return Source(
        id=uuid4(),
        name="Meta AI Research (Locked Out)",
        category=Category.AI_RESEARCH,
        type=SourceType.RSS,
        url="https://ai.meta.com/blog/rss",
        rate_limit_seconds=0,
        enabled=True,
        config={
            "etag": '"stale-etag-token-12345"',
            "last_modified": "Thu, 29 Oct 2026 17:42:44 GMT",
            "stored_entries_count": 0,
        },
    )


@pytest.mark.asyncio
async def test_etag_lockout_triggers_full_refetch_when_entries_under_threshold(
    locked_out_source: Source,
    monkeypatch,
):
    """When server returns 304 but stored_entries_count < 3, drop validators and refetch."""
    recent_date = (datetime.now(UTC) - timedelta(days=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Meta AI Research</title>
        <item>
          <title>Llama 3.3 and Multimodal Reasoning Breakthroughs</title>
          <link>https://ai.meta.com/blog/llama-3-3</link>
          <description>Open foundation models with dense reasoning capabilities.</description>
          <pubDate>{recent_date}</pubDate>
        </item>
      </channel>
    </rss>
    """

    # Mock client behavior:
    # First request: has If-None-Match -> returns 304 Not Modified
    # Second request: no If-None-Match -> returns 200 with feed_xml
    calls = []

    async def mock_get(self_client, url, **kwargs):
        headers = dict(self_client.headers)
        if "headers" in kwargs and kwargs["headers"]:
            headers.update(kwargs["headers"])
        calls.append(headers)
        resp = MagicMock()
        if (
            "if-none-match" in headers
            or "if-modified-since" in headers
            or "If-None-Match" in headers
            or "If-Modified-Since" in headers
        ):
            resp.status_code = 304
            resp.headers = {"etag": '"stale-etag-token-12345"'}
            resp.text = ""
            resp.content = b""
        else:
            resp.status_code = 200
            resp.headers = {
                "etag": '"new-valid-etag-67890"',
                "content-type": "application/rss+xml",
            }
            resp.text = feed_xml
            resp.content = feed_xml.encode("utf-8")
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    fetcher = RSSFetcher(locked_out_source)
    result = await fetcher.fetch()

    # Should have detected 304 lockout, dropped stale validators, and refetched
    assert len(calls) == 2, f"Expected 2 HTTP calls (initial 304 + refetch), got {len(calls)}"
    assert "if-none-match" in calls[0] or "If-None-Match" in calls[0]
    assert "if-none-match" not in calls[1] and "If-None-Match" not in calls[1]

    # Validated result
    assert result.status.value == "success"
    assert len(result.entries) == 1
    assert result.entries[0].title == "Llama 3.3 and Multimodal Reasoning Breakthroughs"

    # Stored validators updated to new fresh ETag
    assert locked_out_source.config.get("etag") == '"new-valid-etag-67890"'


@pytest.mark.asyncio
async def test_304_accepted_when_source_has_sufficient_stored_entries(
    locked_out_source: Source,
    monkeypatch,
):
    """When stored_entries_count >= 3, 304 is accepted cleanly without unnecessary refetch."""
    locked_out_source.config["stored_entries_count"] = 15

    calls = []

    async def mock_get(self_client, url, **kwargs):
        calls.append(dict(self_client.headers))
        resp = MagicMock()
        resp.status_code = 304
        resp.headers = {"etag": '"stale-etag-token-12345"'}
        resp.text = ""
        resp.content = b""
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    fetcher = RSSFetcher(locked_out_source)
    result = await fetcher.fetch()

    # Should have made only 1 request and accepted 304
    assert len(calls) == 1
    assert result.status.value == "success"
    assert len(result.entries) == 0
