"""
Tests for Hugging Face Daily Papers Fetcher and Research Intelligence.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from ai_security_monitor.config.sources import load_sources
from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.huggingface_daily_papers_fetcher import (
    HuggingFaceDailyPapersFetcher,
)


def test_huggingface_daily_papers_source_configured():
    """Verify that Hugging Face Curated Daily Papers is configured in sources.yaml."""
    config = load_sources()
    hf_sources = [s for s in config.sources if s.type == "huggingface_daily_papers"]
    assert len(hf_sources) >= 1
    src = hf_sources[0]
    assert src.category == "ai_research"
    assert "daily_papers" in src.url


@pytest.mark.asyncio
async def test_huggingface_daily_papers_parser_success():
    """Verify parsing of valid Hugging Face daily paper payloads."""
    src = Source(
        id=uuid.uuid4(),
        name="Hugging Face Daily Papers Test",
        category=Category.AI_RESEARCH,
        type=SourceType.HUGGINGFACE_DAILY_PAPERS,
        url="https://huggingface.co/api/daily_papers",
        rate_limit_seconds=1800,
        enabled=True,
    )
    fetcher = HuggingFaceDailyPapersFetcher(src)

    raw_paper = {
        "paper": {
            "id": "2410.99999",
            "title": "DeepScale: Test-Time Compute Scaling for Autonomous Reasoning Agents",
            "summary": "We present DeepScale, an architecture that scales test-time compute to achieve state-of-the-art results.",
            "publishedAt": datetime.now(UTC).isoformat(),
            "authors": [{"name": "Alice Chen"}, {"name": "Bob Smith"}],
            "upvotes": 142,
        }
    }

    entry = fetcher._parse_entry(raw_paper)
    assert entry is not None
    assert (
        entry.title
        == "DeepScale: Test-Time Compute Scaling for Autonomous Reasoning Agents"
    )
    assert entry.url == "https://huggingface.co/papers/2410.99999"
    assert entry.category == Category.AI_RESEARCH
    assert entry.metadata["arxiv_id"] == "2410.99999"
    assert entry.metadata["upvotes"] == 142
    assert "Alice Chen" in entry.metadata["authors"]
    assert entry.metadata["pdf_url"] == "https://arxiv.org/pdf/2410.99999.pdf"


@pytest.mark.asyncio
async def test_huggingface_daily_papers_freshness_guard():
    """Verify that stale papers older than 14 days are discarded at the ingestion boundary."""
    src = Source(
        id=uuid.uuid4(),
        name="Hugging Face Daily Papers Stale Test",
        category=Category.AI_RESEARCH,
        type=SourceType.HUGGINGFACE_DAILY_PAPERS,
        url="https://huggingface.co/api/daily_papers",
        rate_limit_seconds=1800,
        enabled=True,
    )
    fetcher = HuggingFaceDailyPapersFetcher(src)

    stale_date = datetime.now(UTC) - timedelta(days=20)
    raw_stale_paper = {
        "paper": {
            "id": "2401.00001",
            "title": "Historical 2024 Ancient Architecture Preprint",
            "summary": "An old paper published 20 days ago that should be ignored.",
            "publishedAt": stale_date.isoformat(),
            "authors": [{"name": "Ancient Author"}],
            "upvotes": 5,
        }
    }

    with pytest.raises(ValueError) as excinfo:
        fetcher._parse_entry(raw_stale_paper)
    assert "Discarding stale research paper" in str(excinfo.value)


@pytest.mark.asyncio
async def test_huggingface_daily_papers_malformed_payloads():
    """Brutally test missing fields, malformed dates, oversized summaries, and varied author formats."""
    src = Source(
        id=uuid.uuid4(),
        name="Hugging Face Daily Papers Edge Cases",
        category=Category.AI_RESEARCH,
        type=SourceType.HUGGINGFACE_DAILY_PAPERS,
        url="https://huggingface.co/api/daily_papers",
        rate_limit_seconds=1800,
        enabled=True,
    )
    fetcher = HuggingFaceDailyPapersFetcher(src)

    # 1. Missing title or paper ID must raise ValueError
    for bad_paper in (
        {},
        {"paper": {"id": "2410.1234"}},
        {"paper": {"title": "Paper Without ID"}},
    ):
        with pytest.raises(ValueError) as excinfo:
            fetcher._parse_entry(bad_paper)
        assert "Missing title or paper_id" in str(excinfo.value)

    # 2. Malformed date format should fall back to now(UTC) gracefully without crashing
    bad_date_paper = {
        "paper": {
            "id": "2410.55555",
            "title": "Robustness Under Malformed Timestamps",
            "summary": "Testing parser resilience.",
            "publishedAt": "NOT_A_VALID_DATE_FORMAT",
            "upvotes": 10,
        }
    }
    entry_bad_date = fetcher._parse_entry(bad_date_paper)
    assert entry_bad_date.title == "Robustness Under Malformed Timestamps"
    assert entry_bad_date.published_at is not None

    # 3. Oversized summary (>800 chars) must be truncated with ellipsis
    long_summary = "A" * 1200
    long_paper = {
        "paper": {
            "id": "2410.66666",
            "title": "Long Context Reasoning Summary",
            "summary": long_summary,
            "publishedAt": datetime.now(UTC).isoformat(),
        }
    }
    entry_long = fetcher._parse_entry(long_paper)
    assert len(entry_long.summary) <= 800
    assert entry_long.summary.endswith("...")

    # 4. Authors as string list instead of dict list
    string_authors_paper = {
        "paper": {
            "id": "2410.77777",
            "title": "Author List Format Permutations",
            "summary": "Testing author normalization.",
            "publishedAt": datetime.now(UTC).isoformat(),
            "authors": ["Alice Chen", "Bob Smith"],
        }
    }
    entry_authors = fetcher._parse_entry(string_authors_paper)
    assert "Alice Chen" in entry_authors.metadata["authors"]
    assert "Bob Smith" in entry_authors.metadata["authors"]
