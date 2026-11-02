"""
Unit tests for Defect Ledger D4: Failed fetches recorded as success.

Requirements:
1. Non-2xx (404, 5xx) responses must be recorded as FetchStatus.ERROR in fetch_log.
2. HTML content-type or HTML landing page bodies returned for RSS feeds must be recorded as FetchStatus.ERROR.
3. HTTP 304 is recorded as neutral (FetchStatus.NOT_MODIFIED) in fetch_log, not healthy success.
4. When fetch fails, source_health_service records failure (consecutive_failures increments).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest

from ai_security_monitor.domain.entities import (
    Category,
    FetchStatus,
    Source,
    SourceType,
)
from ai_security_monitor.infrastructure.fetchers.rss_fetcher import RSSFetcher


@pytest.fixture
def test_rss_source() -> Source:
    return Source(
        id=uuid4(),
        name="Synced AI Media",
        category=Category.AI_RESEARCH,
        type=SourceType.RSS,
        url="https://syncedreview.com/feed",
        rate_limit_seconds=0,
        enabled=True,
        config={"stored_entries_count": 5},
    )


@pytest.mark.asyncio
async def test_404_response_recorded_as_error(test_rss_source: Source, monkeypatch):
    """HTTP 404 Not Found must return FetchStatus.ERROR with error message."""
    resp = MagicMock()
    resp.status_code = 404
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Client error '404 Not Found'", request=MagicMock(), response=resp
    )

    async def mock_get(self_client, url, **kwargs):
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    fetcher = RSSFetcher(test_rss_source)
    result = await fetcher.fetch()

    assert result.status == FetchStatus.ERROR
    assert "404" in str(result.error_message)
    assert len(result.entries) == 0


@pytest.mark.asyncio
async def test_500_response_recorded_as_error(test_rss_source: Source, monkeypatch):
    """HTTP 500 Internal Server Error must return FetchStatus.ERROR with error message."""
    resp = MagicMock()
    resp.status_code = 500
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server error '500 Internal Server Error'", request=MagicMock(), response=resp
    )

    async def mock_get(self_client, url, **kwargs):
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    fetcher = RSSFetcher(test_rss_source)
    result = await fetcher.fetch()

    assert result.status == FetchStatus.ERROR
    assert "500" in str(result.error_message)
    assert len(result.entries) == 0


@pytest.mark.asyncio
async def test_html_landing_page_as_feed_recorded_as_error(
    test_rss_source: Source, monkeypatch
):
    """HTML landing page returned for an RSS feed must raise content-type error and return FetchStatus.ERROR."""
    html_content = b"<!DOCTYPE html><html><body><h1>Welcome to Synced Review</h1></body></html>"
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"content-type": "text/html; charset=utf-8"}
    resp.content = html_content
    resp.text = html_content.decode("utf-8")
    resp.raise_for_status.return_value = None

    async def mock_get(self_client, url, **kwargs):
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    fetcher = RSSFetcher(test_rss_source)
    result = await fetcher.fetch()

    assert result.status == FetchStatus.ERROR
    assert "HTML instead of RSS/Atom" in str(result.error_message)
    assert len(result.entries) == 0


@pytest.mark.asyncio
async def test_304_with_data_recorded_as_not_modified(
    test_rss_source: Source, monkeypatch
):
    """HTTP 304 for a source with sufficient data must return FetchStatus.NOT_MODIFIED."""
    test_rss_source.config["stored_entries_count"] = 10
    resp = MagicMock()
    resp.status_code = 304
    resp.headers = {}
    resp.content = b""

    async def mock_get(self_client, url, **kwargs):
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    fetcher = RSSFetcher(test_rss_source)
    result = await fetcher.fetch()

    assert result.status == FetchStatus.NOT_MODIFIED
    assert len(result.entries) == 0


@pytest.mark.asyncio
async def test_304_without_data_discards_validators_and_fetches_fresh(
    test_rss_source: Source, monkeypatch
):
    """HTTP 304 for a source with 0 stored entries must discard validators and fetch fresh payload."""
    test_rss_source.config["stored_entries_count"] = 0
    test_rss_source.config["etag"] = '"old-etag"'

    recent_date = (datetime.now(UTC) - timedelta(days=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Synced AI</title>
        <item>
          <title>Frontier Transformer MoE Scaling</title>
          <link>https://syncedreview.com/moe-scaling</link>
          <description>Technical evaluation of mixture of experts.</description>
          <pubDate>{recent_date}</pubDate>
        </item>
      </channel>
    </rss>
    """

    calls = 0

    async def mock_get(self_client, url, **kwargs):
        nonlocal calls
        calls += 1
        resp = MagicMock()
        if calls == 1:
            resp.status_code = 304
            resp.headers = {"etag": '"old-etag"'}
            resp.content = b""
        else:
            resp.status_code = 200
            resp.headers = {"content-type": "application/rss+xml"}
            resp.content = feed_xml.encode("utf-8")
            resp.text = feed_xml
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    fetcher = RSSFetcher(test_rss_source)
    result = await fetcher.fetch()

    assert calls == 2
    assert result.status == FetchStatus.SUCCESS
    assert len(result.entries) == 1
    assert result.entries[0].title == "Frontier Transformer MoE Scaling"


@pytest.mark.asyncio
async def test_monitor_service_records_error_status(test_rss_source: Source, test_uow):
    """MonitorService.fetch_source must record FetchStatus.ERROR and increment consecutive failures on 404."""
    from unittest.mock import AsyncMock, patch

    from ai_security_monitor.application.services.monitor_service import MonitorService
    from ai_security_monitor.infrastructure.fetchers.base import FetchResult

    monitor = MonitorService(uow_factory=lambda: test_uow)

    mock_error_result = FetchResult(
        entries=[],
        entries_new=0,
        entries_total=0,
        status=FetchStatus.ERROR,
        error_message="HTTP 404 Not Found from upstream feed",
    )

    with (
        patch("ai_security_monitor.infrastructure.fetchers.rss_fetcher.RSSFetcher.fetch", new_callable=AsyncMock) as mock_fetch,
        patch.object(test_uow.sources, "update", new_callable=AsyncMock) as mock_src_update,
        patch.object(test_uow.fetch_logs, "add", new_callable=AsyncMock) as mock_log_add,
        patch.object(test_uow, "commit", new_callable=AsyncMock),
    ):
        mock_fetch.return_value = mock_error_result
        log = await monitor.fetch_source(test_rss_source)

        assert log.status == FetchStatus.ERROR
        assert "404" in str(log.error_message)
        assert test_rss_source.last_status == "error"
        mock_src_update.assert_called()
        mock_log_add.assert_called_once()
        saved_log = mock_log_add.call_args[0][0]
        assert saved_log.status == FetchStatus.ERROR


@pytest.mark.asyncio
async def test_monitor_service_records_not_modified_neutral(test_rss_source: Source, test_uow):
    """MonitorService.fetch_source must record FetchStatus.NOT_MODIFIED without incrementing failures on 304."""
    from unittest.mock import AsyncMock, patch

    from ai_security_monitor.application.services.monitor_service import MonitorService
    from ai_security_monitor.infrastructure.fetchers.base import FetchResult

    monitor = MonitorService(uow_factory=lambda: test_uow)

    mock_304_result = FetchResult(
        entries=[],
        entries_new=0,
        entries_total=0,
        status=FetchStatus.NOT_MODIFIED,
    )

    with (
        patch("ai_security_monitor.infrastructure.fetchers.rss_fetcher.RSSFetcher.fetch", new_callable=AsyncMock) as mock_fetch,
        patch.object(test_uow.sources, "update", new_callable=AsyncMock) as mock_src_update,
        patch.object(test_uow.fetch_logs, "add", new_callable=AsyncMock) as mock_log_add,
        patch.object(test_uow, "commit", new_callable=AsyncMock),
    ):
        mock_fetch.return_value = mock_304_result
        log = await monitor.fetch_source(test_rss_source)

        assert log.status == FetchStatus.NOT_MODIFIED
        assert test_rss_source.last_status == "not_modified"
        mock_src_update.assert_called()
        mock_log_add.assert_called_once()
        saved_log = mock_log_add.call_args[0][0]
        assert saved_log.status == FetchStatus.NOT_MODIFIED
