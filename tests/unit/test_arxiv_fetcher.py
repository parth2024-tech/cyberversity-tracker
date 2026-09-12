"""Unit tests for ArxivFetcher."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.arxiv_fetcher import ArxivFetcher

ARXIV_ATOM_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Scaling Reasoning in Large Language Models</title>
    <summary>We present a novel approach to test-time compute scaling...</summary>
    <link href="https://arxiv.org/abs/2401.00001" rel="alternate"/>
    <published>2026-01-01T12:00:00Z</published>
    <author><name>Jane Doe</name></author>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <title>Efficient Attention Mechanisms for Long-Context Models</title>
    <summary>This paper introduces a linear attention mechanism...</summary>
    <link href="https://arxiv.org/abs/2401.00002" rel="alternate"/>
    <published>2026-01-02T10:00:00Z</published>
    <author><name>John Smith</name></author>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>"""


@pytest.fixture
def arxiv_source() -> Source:
    return Source(
        id=uuid4(),
        name="arXiv AI Feed",
        category=Category.AI_RESEARCH,
        type=SourceType.ARXIV,
        url="https://export.arxiv.org/api/query",
        query="cat:cs.AI OR cat:cs.LG",
        rate_limit_seconds=0,
        enabled=True,
    )


@pytest.mark.asyncio
async def test_arxiv_fetcher_parses_papers(arxiv_source: Source):
    """ArxivFetcher should parse arXiv Atom feed into raw entry dicts."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = ARXIV_ATOM_XML
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("ai_security_monitor.infrastructure.fetchers.arxiv_fetcher.httpx.AsyncClient", return_value=mock_client):
        fetcher = ArxivFetcher(arxiv_source)
        raw = await fetcher._fetch_raw()

    assert len(raw) == 2
    assert "Scaling Reasoning" in raw[0]["title"]
    assert "arxiv" in raw[0]["tags"]
    assert raw[0]["metadata"]["authors"] == ["Jane Doe"]


@pytest.mark.asyncio
async def test_arxiv_fetcher_parse_entry_entity(arxiv_source: Source):
    """_parse_entry returns valid Entry with correct hash and category."""
    fetcher = ArxivFetcher(arxiv_source)
    raw = {
        "title": "Test Paper on Multimodal LLMs",
        "url": "https://arxiv.org/abs/2401.99999",
        "content": "Abstract: We study multimodal large language models.",
        "published_at": datetime.now(UTC),
        "tags": ["cs.AI", "arxiv"],
        "metadata": {"authors": ["Alice"], "arxiv_id": "2401.99999", "categories": ["cs.AI"]},
    }
    entry = fetcher._parse_entry(raw)

    assert entry.title == raw["title"]
    assert entry.category == Category.AI_RESEARCH
    assert len(entry.content_hash) == 64


def test_arxiv_clean_html(arxiv_source: Source):
    """_clean_html should strip all HTML tags from arXiv abstract."""
    fetcher = ArxivFetcher(arxiv_source)
    html_text = "<p>We study <b>LLMs</b> and <i>attention</i> mechanisms. <script>bad()</script></p>"
    clean = fetcher._clean_html(html_text)
    assert "<" not in clean
    assert "LLMs" in clean
    assert "attention" in clean
    assert "bad" not in clean
