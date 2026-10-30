"""Unit tests for BridgeFeedFetcher (Feature 7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import (
    Category,
    FetchStatus,
    Source,
    SourceType,
)
from ai_security_monitor.infrastructure.fetchers.bridge_feed_fetcher import (
    BridgeFeedFetcher,
    is_chinese_ai_launch,
)


@pytest.fixture
def bridge_source() -> Source:
    return Source(
        id=uuid4(),
        name="WeChat AI Channels Bridge",
        category=Category.AI_MODELS,
        type=SourceType.BRIDGE_FEED,
        url="https://primary-bridge.internal/rss/wechat/deepseek",
        query=None,
        rate_limit_seconds=0,
        enabled=True,
        config={
            "fallback_url": "https://fallback-bridge.internal/rss/wechat/deepseek",
            "bridges": [
                "https://mirror-bridge.internal/rss/wechat/deepseek",
            ],
            "channel": "wechat",
        },
    )


WECHAT_FEED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>DeepSeek \xe6\xb7\xb1\xe5\xba\xa6\xe6\xb1\x82\xe7\xb4\xa2\xe5\x85\xac\xe4\xbc\x97\xe5\x8f\xb7</title>
    <link>https://mp.weixin.qq.com/s/deepseek-v3</link>
    <item>
      <title>\xe6\xb7\xb1\xe5\xba\xa6\xe6\xb1\x82\xe7\xb4\xa2 DeepSeek-V3 \xe6\xad\xa3\xe5\xbc\x8f\xe5\xbc\x80\xe6\xba\x90\xe5\x8f\x91\xe5\xb8\x83\xef\xbc\x8c671B\xe5\x8f\x82\xe6\x95\xb0MoE\xe6\x9e\xb6\xe6\x9e\x84</title>
      <link>https://mp.weixin.qq.com/s/example123</link>
      <description>\xe4\xbb\x8a\xe6\x97\xa5\xef\xbc\x8cDeepSeek\xe5\xae\xa3\xe5\xb8\x83\xe6\xad\xa3\xe5\xbc\x8f\xe5\xbc\x80\xe6\xba\x90\xe6\x97\x97\xe8\x88\xb0\xe5\xa4\xa7\xe6\xa8\xa1\xe5\x9e\x8bDeepSeek-V3\xef\xbc\x8c\xe6\x80\xbb\xe5\x8f\x82\xe6\x95\xb0671B\xef\xbc\x8c\xe6\xbf\x80\xe6\xb4\xbb37B\xef\xbc\x8c\xe6\x80\xa7\xe8\x83\xbd\xe8\xbf\xbd\xe5\xb9\xb3Claude 3.5 Sonnet\xe3\x80\x82</description>
      <pubDate>Mon, 27 Jan 2026 10:00:00 +0800</pubDate>
    </item>
  </channel>
</rss>"""

OFF_TOPIC_FEED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>General Daily News</title>
    <link>https://example.com</link>
    <item>
      <title>\xe6\x9f\x90\xe5\x9c\xb0\xe6\x88\xbf\xe5\x9c\xb0\xe4\xba\xa7\xe5\xb8\x82\xe5\x9c\xba\xe6\x9c\x80\xe6\x96\xb0\xe6\x88\x90\xe4\xba\xa4\xe6\x95\xb0\xe6\x8d\xae\xe5\x85\xac\xe5\xb8\x83</title>
      <link>https://example.com/real-estate</link>
      <description>\xe6\x9c\xac\xe5\x91\xa8\xe4\xba\x8c\xe6\x89\x8b\xe6\x88\xbf\xe6\x88\x90\xe4\xba\xa4\xe9\x87\x8f\xe7\x8e\xaf\xe6\xaf\x94\xe4\xb8\x8a\xe6\xb6\xa8\xef\xbc\x8c\xe4\xbb\xb7\xe6\xa0\xbc\xe4\xbf\x9d\xe6\x8c\x81\xe5\xb9\xb3\xe7\xa8\xb3\xe3\x80\x82</description>
      <pubDate>Mon, 27 Jan 2026 10:00:00 +0800</pubDate>
    </item>
  </channel>
</rss>"""

EMPTY_FEED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Empty Feed</title>
    <link>https://example.com</link>
  </channel>
</rss>"""

HTML_CAPTCHA_PAGE = (
    b"<html><head><title>\xe5\xae\x89\xe5\x85\xa8\xe9\xaa\x8c\xe8\xaf\x81</title></head>"
    b"<body><h1>\xe8\xaf\xb7\xe5\xae\x8c\xe6\x88\x90\xe9\xaa\x8c\xe8\xaf\x81\xe7\xa0\x81\xe6\xa0\xa1\xe9\xaa\x8c</h1>"
    b"<p>weixin.qq.com/verify</p></body></html>"
)


def test_candidate_bridges_parsing(bridge_source: Source):
    """BridgeFeedFetcher should correctly assemble primary and fallback bridges in order."""
    fetcher = BridgeFeedFetcher(bridge_source)
    bridges = fetcher.get_candidate_bridges()
    assert bridges == [
        "https://primary-bridge.internal/rss/wechat/deepseek",
        "https://fallback-bridge.internal/rss/wechat/deepseek",
        "https://mirror-bridge.internal/rss/wechat/deepseek",
    ]


def test_chinese_ai_launch_triage():
    """is_chinese_ai_launch should correctly distinguish AI launches from off-topic content."""
    # Positive: DeepSeek + 开源
    assert is_chinese_ai_launch("深度求索推出DeepSeek-V3", "正式开源，671B参数") is True

    # Positive: Qwen + 发布
    assert is_chinese_ai_launch("阿里千问发布Qwen2.5-Coder", "代码能力大幅提升") is True

    # Positive: Moonshot / Kimi + 推理
    assert (
        is_chinese_ai_launch("月之暗面 Kimi k1.5", "长上下文与数学推理能力突破") is True
    )

    # Positive: 2+ technical keywords without specific lab name
    assert (
        is_chinese_ai_launch("国内最新开源大模型评测", "参数规模与算力表现优异") is True
    )

    # Negative: Real estate
    assert (
        is_chinese_ai_launch("某地房地产市场最新成交数据公布", "二手房成交量环比上涨")
        is False
    )

    # Negative: Sports
    assert (
        is_chinese_ai_launch("全国足球锦标赛决赛今日开打", "主队3比1获胜夺冠") is False
    )


@pytest.mark.asyncio
async def test_bridge_feed_fetcher_primary_success(bridge_source: Source):
    """Primary bridge 200 XML should succeed with failover_occurred=False."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/rss+xml"}
    mock_resp.content = WECHAT_FEED_XML
    mock_resp.text = WECHAT_FEED_XML.decode("utf-8")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        fetcher = BridgeFeedFetcher(bridge_source, max_retries=1)
        res = await fetcher.fetch()

    assert res.status == FetchStatus.SUCCESS
    assert len(res.entries) == 1
    entry = res.entries[0]
    assert "DeepSeek-V3" in entry.title
    assert entry.metadata["failover_occurred"] is False
    assert (
        entry.metadata["bridge_url"]
        == "https://primary-bridge.internal/rss/wechat/deepseek"
    )
    assert entry.metadata["passed_chinese_triage"] is True
    assert "is_filtered_out" not in entry.metadata
    assert entry.metadata["original_chinese"].startswith("深度求索 DeepSeek-V3")


@pytest.mark.asyncio
async def test_bridge_feed_fetcher_failover_on_http_error(bridge_source: Source):
    """When primary bridge returns 404, fetcher should fail over to secondary bridge."""
    mock_404_resp = MagicMock()
    mock_404_resp.status_code = 404
    mock_404_resp.headers = {"content-type": "text/html"}
    mock_404_resp.text = "Not Found"

    mock_200_resp = MagicMock()
    mock_200_resp.status_code = 200
    mock_200_resp.headers = {"content-type": "application/rss+xml"}
    mock_200_resp.content = WECHAT_FEED_XML
    mock_200_resp.text = WECHAT_FEED_XML.decode("utf-8")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[mock_404_resp, mock_200_resp])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        fetcher = BridgeFeedFetcher(bridge_source, max_retries=1)
        res = await fetcher.fetch()

    assert res.status == FetchStatus.SUCCESS
    assert len(res.entries) == 1
    entry = res.entries[0]
    assert entry.metadata["failover_occurred"] is True
    assert (
        entry.metadata["bridge_url"]
        == "https://fallback-bridge.internal/rss/wechat/deepseek"
    )


@pytest.mark.asyncio
async def test_bridge_feed_fetcher_failover_on_html_captcha(bridge_source: Source):
    """When bridge returns HTML captcha/verification page, it should fail over."""
    mock_captcha_resp = MagicMock()
    mock_captcha_resp.status_code = 200
    mock_captcha_resp.headers = {"content-type": "text/html"}
    mock_captcha_resp.content = HTML_CAPTCHA_PAGE
    mock_captcha_resp.text = HTML_CAPTCHA_PAGE.decode("utf-8")

    mock_200_resp = MagicMock()
    mock_200_resp.status_code = 200
    mock_200_resp.headers = {"content-type": "application/rss+xml"}
    mock_200_resp.content = WECHAT_FEED_XML
    mock_200_resp.text = WECHAT_FEED_XML.decode("utf-8")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[mock_captcha_resp, mock_200_resp])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        fetcher = BridgeFeedFetcher(bridge_source, max_retries=1)
        res = await fetcher.fetch()

    assert res.status == FetchStatus.SUCCESS
    assert len(res.entries) == 1
    assert res.entries[0].metadata["failover_occurred"] is True


@pytest.mark.asyncio
async def test_bridge_feed_fetcher_failover_on_empty_feed(bridge_source: Source):
    """When primary bridge returns 0 entries, fetcher should fail over to mirror."""
    mock_empty_resp = MagicMock()
    mock_empty_resp.status_code = 200
    mock_empty_resp.headers = {"content-type": "application/rss+xml"}
    mock_empty_resp.content = EMPTY_FEED_XML
    mock_empty_resp.text = EMPTY_FEED_XML.decode("utf-8")

    mock_200_resp = MagicMock()
    mock_200_resp.status_code = 200
    mock_200_resp.headers = {"content-type": "application/rss+xml"}
    mock_200_resp.content = WECHAT_FEED_XML
    mock_200_resp.text = WECHAT_FEED_XML.decode("utf-8")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[mock_empty_resp, mock_200_resp])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        fetcher = BridgeFeedFetcher(bridge_source, max_retries=1)
        res = await fetcher.fetch()

    assert res.status == FetchStatus.SUCCESS
    assert len(res.entries) == 1
    assert res.entries[0].metadata["failover_occurred"] is True


@pytest.mark.asyncio
async def test_bridge_feed_fetcher_all_fail_raises_fetch_error(bridge_source: Source):
    """When all candidate bridges fail, fetcher should raise FetchError."""
    mock_500_resp = MagicMock()
    mock_500_resp.status_code = 500
    mock_500_resp.headers = {"content-type": "text/html"}
    mock_500_resp.text = "Internal Server Error"

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_500_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        fetcher = BridgeFeedFetcher(bridge_source, max_retries=1)
        res = await fetcher.fetch()

    assert res.status == FetchStatus.ERROR
    assert "All 3 candidate bridges failed" in (res.error_message or "")


@pytest.mark.asyncio
async def test_bridge_feed_fetcher_filters_off_topic_chinese_news(
    bridge_source: Source,
):
    """Off-topic Chinese news should be marked as filtered out during parsing."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/rss+xml"}
    mock_resp.content = OFF_TOPIC_FEED_XML
    mock_resp.text = OFF_TOPIC_FEED_XML.decode("utf-8")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        fetcher = BridgeFeedFetcher(bridge_source, max_retries=1)
        res = await fetcher.fetch()

    assert res.status == FetchStatus.SUCCESS
    assert len(res.entries) == 1
    entry = res.entries[0]
    assert entry.metadata["passed_chinese_triage"] is False
    assert entry.metadata["is_filtered_out"] is True
    assert entry.metadata["filter_reason"] == "off_topic_chinese_news"
