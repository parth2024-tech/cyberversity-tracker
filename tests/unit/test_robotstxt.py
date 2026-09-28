"""Unit tests for RobotsTxtManager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_security_monitor.infrastructure.fetchers.robotstxt import (
    RobotsTxtManager,
    robots_manager,
)


def test_extract_domain():
    assert RobotsTxtManager.extract_domain("https://huggingface.co/models") == "huggingface.co"
    assert RobotsTxtManager.extract_domain("http://arxiv.org:80/abs/2501.12948") == "arxiv.org"
    assert RobotsTxtManager.extract_domain(None) == "default"


@pytest.mark.asyncio
async def test_robots_manager_can_fetch_allowed():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "User-agent: *\nDisallow: /private/\nCrawl-delay: 2\n"

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    manager = RobotsTxtManager()

    with patch("ai_security_monitor.infrastructure.fetchers.robotstxt.httpx.AsyncClient", return_value=mock_client):
        allowed = await manager.can_fetch("https://example.com/public/ai-news")
        disallowed = await manager.can_fetch("https://example.com/private/secret")
        delay = await manager.get_crawl_delay("https://example.com/public/ai-news")

    assert allowed is True
    assert disallowed is False
    assert delay == 2.0


@pytest.mark.asyncio
async def test_robots_manager_resilience_on_404():
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    manager = RobotsTxtManager()

    with patch("ai_security_monitor.infrastructure.fetchers.robotstxt.httpx.AsyncClient", return_value=mock_client):
        allowed = await manager.can_fetch("https://example.com/anything")

    # Missing robots.txt should permit crawling
    assert allowed is True
