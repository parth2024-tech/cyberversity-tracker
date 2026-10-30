"""Unit tests for RSSFetcher."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.rss_fetcher import RSSFetcher


@pytest.fixture
def rss_source() -> Source:
    return Source(
        id=uuid4(),
        name="Test RSS Feed",
        category=Category.AI_RESEARCH,
        type=SourceType.RSS,
        url="https://example.com/feed.rss",
        query=None,
        rate_limit_seconds=0,
        enabled=True,
    )


RSS_FEED_XML = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <item>
      <title>DeepSeek R3: New Reasoning Architecture Released</title>
      <link>https://example.com/deepseek-r3</link>
      <description>A new 70B parameter model with extended chain-of-thought reasoning.</description>
      <pubDate>Fri, 01 Jan 2026 12:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Llama 4 Open-Source Weights Published by Meta AI</title>
      <link>https://example.com/llama4</link>
      <description>Meta releases Llama 4 with 405B parameters under permissive license.</description>
    </item>
  </channel>
</rss>"""


@pytest.mark.asyncio
async def test_rss_fetcher_parses_entries(rss_source: Source):
    """RSSFetcher should parse feed items into dicts with expected keys."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = RSS_FEED_XML
    mock_response.encoding = "utf-8"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.rss_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        fetcher = RSSFetcher(rss_source)
        raw = await fetcher._fetch_raw()

    assert len(raw) == 2
    assert raw[0]["title"] == "DeepSeek R3: New Reasoning Architecture Released"
    assert raw[0]["url"] == "https://example.com/deepseek-r3"
    assert "published_at" in raw[0]
    assert "tags" in raw[0]


@pytest.mark.asyncio
async def test_rss_fetcher_parse_entry_creates_valid_entity(rss_source: Source):
    """_parse_entry should produce a valid Entry with correct fields."""
    fetcher = RSSFetcher(rss_source)
    raw = {
        "title": "vLLM 0.8.0 Released with PagedAttention V2",
        "url": "https://example.com/vllm-0.8.0",
        "content": "vLLM 0.8.0 introduces PagedAttention V2 with 40% memory reduction.",
        "published_at": datetime.now(UTC),
        "tags": ["vllm", "inference"],
        "metadata": {"feed_title": "Test Feed"},
    }
    entry = fetcher._parse_entry(raw)

    assert entry.title == raw["title"]
    assert entry.url == raw["url"]
    assert entry.category == Category.AI_RESEARCH
    assert len(entry.content_hash) == 64
    assert "vllm" in entry.tags


@pytest.mark.asyncio
async def test_rss_fetcher_fallback_mirror_on_primary_failure(rss_source: Source):
    """When primary URL fails, fetcher should try mirror URLs."""
    rss_source.config = {"mirrors": ["https://mirror.example.com/feed.rss"]}

    error_response = MagicMock()
    error_response.raise_for_status = MagicMock(
        side_effect=Exception("Connection refused")
    )

    success_response = MagicMock()
    success_response.status_code = 200
    success_response.content = RSS_FEED_XML
    success_response.encoding = "utf-8"
    success_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[error_response, success_response])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.rss_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        fetcher = RSSFetcher(rss_source)
        raw = await fetcher._fetch_raw()

    assert len(raw) > 0


def test_clean_html_strips_script_tags(rss_source: Source):
    """_clean_html should remove script/style and return plain text."""
    fetcher = RSSFetcher(rss_source)
    dirty = "<p>Hello <script>alert('xss')</script><b>world</b></p>"
    clean = fetcher._clean_html(dirty)
    assert "script" not in clean
    assert "alert" not in clean
    assert "Hello" in clean
    assert "world" in clean


def test_clean_html_empty_string(rss_source: Source):
    """_clean_html on empty string should return empty string."""
    fetcher = RSSFetcher(rss_source)
    assert fetcher._clean_html("") == ""
    assert fetcher._clean_html(None) == ""


@pytest.mark.asyncio
async def test_rss_fetcher_fuzzy_date_parsing(rss_source: Source):
    """Non-standard date formats (e.g. VTT 'Wed, 21.10.2026 - 08:30') should be parsed correctly using dateutil fuzzy parser."""
    nonstandard_xml = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Nonstandard Date Feed</title>
    <link>https://example.com</link>
    <item>
      <title>Autonomous AI Agent Infrastructure Tested</title>
      <link>https://example.com/ai-tested</link>
      <description>Research test on agent reasoning pipelines.</description>
      <pubDate>Wed, 21.10.2026 - 08:30</pubDate>
    </item>
  </channel>
</rss>"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = nonstandard_xml
    mock_response.encoding = "utf-8"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.rss_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        fetcher = RSSFetcher(rss_source)
        raw = await fetcher._fetch_raw()

    assert len(raw) == 1
    # Verify it parsed the nonstandard date to 2026-10-21
    pub = raw[0]["published_at"]
    assert pub.year == 2026
    assert pub.month == 10
    assert pub.day == 21


@pytest.mark.asyncio
async def test_rss_fetcher_require_ai_filtering(rss_source: Source):
    """When require_ai=True, generic non-AI topics should be dropped."""
    rss_source.config = {"require_ai": True}
    mixed_xml = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Mixed Research Feed</title>
    <link>https://example.com</link>
    <item>
      <title>Clean Water Filtration Breakthrough in Bio-membranes</title>
      <link>https://example.com/water</link>
      <description>Purification of municipal groundwater reservoirs using osmosis.</description>
    </item>
    <item>
      <title>DeepSeek R3: New Reasoning LLM Architecture Released</title>
      <link>https://example.com/deepseek-r3</link>
      <description>A new open-weights model with chain-of-thought inference.</description>
    </item>
  </channel>
</rss>"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = mixed_xml
    mock_response.encoding = "utf-8"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.rss_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        fetcher = RSSFetcher(rss_source)
        raw = await fetcher._fetch_raw()

    assert len(raw) == 1
    assert "DeepSeek" in raw[0]["title"]


@pytest.mark.asyncio
async def test_rss_fetcher_detects_html_redirect_and_raises(rss_source: Source):
    """When an RSS feed redirects to an HTML landing page (e.g. Synced), it must raise RuntimeError."""
    html_page = b"<!DOCTYPE html><html lang='en'><head><title>Data Service</title></head><body>Redirected</body></html>"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = html_page
    mock_response.headers = {"content-type": "text/html; charset=utf-8"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.rss_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        fetcher = RSSFetcher(rss_source)
        with pytest.raises(RuntimeError, match="returned HTML instead of RSS/Atom"):
            await fetcher._fetch_raw()


@pytest.mark.asyncio
async def test_rss_fetcher_stamps_region_from_source_property():
    """RSSFetcher extracts region and country from source properties/config."""
    source = Source(
        id=uuid4(),
        name="Mistral News",
        category=Category.AI_TECH,
        type=SourceType.RSS,
        url="https://mistral.ai/news/index.xml",
        rate_limit_seconds=0,
        enabled=True,
        config={"region": "europe", "country": "FR"},
    )
    xml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Mistral News</title>
        <item>
          <title>Mistral Large 2 Released</title>
          <link>https://mistral.ai/news/large-2</link>
          <description>New frontier reasoning model</description>
        </item>
      </channel>
    </rss>"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = xml_content
    mock_response.headers = {"content-type": "application/rss+xml"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.rss_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        fetcher = RSSFetcher(source)
        raw = await fetcher._fetch_raw()

    assert len(raw) == 1
    assert raw[0]["metadata"]["region"] == "europe"
    assert raw[0]["metadata"]["country"] == "FR"


@pytest.mark.asyncio
async def test_rss_fetcher_records_304_not_modified():
    """RSSFetcher flags 304 status and returns empty list without raising."""
    source = Source(
        id=uuid4(),
        name="AWS ML Blog",
        category=Category.AI_TECH,
        type=SourceType.RSS,
        url="https://aws.amazon.com/blogs/machine-learning/feed/",
        rate_limit_seconds=0,
        enabled=True,
        config={"etag": "abc-123"},
    )
    mock_response = MagicMock()
    mock_response.status_code = 304

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.fetchers.rss_fetcher.httpx.AsyncClient",
        return_value=mock_client,
    ):
        fetcher = RSSFetcher(source)
        res = await fetcher.fetch()

    assert res.entries == []
    assert res.http_status == 304
    assert fetcher._last_http_status == 304
    assert "last_http_status" not in (source.config or {})

