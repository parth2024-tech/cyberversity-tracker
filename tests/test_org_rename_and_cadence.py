"""
Tests for Defect D5: Org-level polling, declared cadence, and org rename alert handling.
Verifies that:
1. Org rename (THUDM -> zai-org) raises an alert and does NOT return empty.
2. Every source has a declared expected cadence.
3. GitHub Org polling ingests active repos and respects 14-day freshness.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.config.sources import load_sources
from ai_security_monitor.domain.entities import (
    Category,
    FetchStatus,
    Source,
    SourceType,
)
from ai_security_monitor.infrastructure.fetchers.github_org_fetcher import (
    GitHubOrgFetcher,
)
from ai_security_monitor.infrastructure.fetchers.huggingface_china_fetcher import (
    HuggingFaceChinaFetcher,
)


@pytest.fixture
def hf_thudm_source() -> Source:
    return Source(
        id=uuid4(),
        name="Tsinghua Zhipu AI",
        category=Category.AI_MODELS,
        type=SourceType.HUGGINGFACE_CHINA,
        url="https://huggingface.co/api/models",
        config={"author": "THUDM", "expected_cadence_days": 2},
    )


@pytest.fixture
def github_thudm_source() -> Source:
    return Source(
        id=uuid4(),
        name="THUDM GitHub Org",
        category=Category.GITHUB_TRENDING,
        type=SourceType.GITHUB_ORG,
        url="https://api.github.com/orgs/THUDM/repos",
        config={"org": "THUDM", "expected_cadence_days": 2},
    )


@pytest.mark.asyncio
async def test_hf_org_rename_raises_alert_and_does_not_return_empty(
    hf_thudm_source: Source, caplog
):
    """When an org is renamed (e.g. THUDM -> zai-org), fetcher must raise an alert and return entries."""
    fetcher = HuggingFaceChinaFetcher(hf_thudm_source)

    mock_zai_models = [
        {
            "id": "zai-org/GLM-5.3-Flash",
            "modelId": "zai-org/GLM-5.3-Flash",
            "pipeline_tag": "text-generation",
            "downloads": 15000,
            "likes": 420,
            "tags": ["license:apache-2.0"],
            "createdAt": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
        }
    ]

    async def mock_get(url, params=None, **kwargs):
        author = params.get("author") if params else None
        resp = MagicMock()
        if author == "THUDM":
            # Old org returns empty list or 404
            resp.status_code = 200
            resp.json.return_value = []
        elif author == "zai-org":
            resp.status_code = 200
            resp.json.return_value = mock_zai_models
        else:
            resp.status_code = 404
            resp.json.return_value = []
        return resp

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        result = await fetcher.fetch()

    # Must raise an alert (recorded on fetcher and logged)
    alert_found = any(
        "rename" in msg.lower() and "zai-org" in msg.lower()
        for msg in fetcher.org_rename_alerts
    )
    assert alert_found, "Expected org rename alert was not recorded on fetcher!"

    # Must NOT return empty
    assert len(result.entries) > 0, "Fetcher returned empty entries despite org rename!"
    assert "zai-org/GLM-5.3-Flash" in result.entries[0].title


@pytest.mark.asyncio
async def test_github_org_rename_raises_alert_and_does_not_return_empty(
    github_thudm_source: Source,
):
    """GitHub org rename (THUDM -> zai-org) must raise an alert and return active repos from renamed org."""
    fetcher = GitHubOrgFetcher(github_thudm_source)

    mock_zai_repos = [
        {
            "name": "GLM-V",
            "html_url": "https://github.com/zai-org/GLM-V",
            "description": "Frontier Multimodal Foundation Model",
            "pushed_at": (datetime.now(UTC) - timedelta(days=1)).isoformat() + "Z",
            "stargazers_count": 8500,
            "language": "Python",
            "fork": False,
        }
    ]

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        if "THUDM" in url:
            resp.status_code = 404
            resp.json.return_value = {"message": "Not Found"}
        elif "zai-org" in url:
            resp.status_code = 200
            resp.headers = {"etag": 'W/"12345"'}
            resp.json.return_value = mock_zai_repos
        else:
            resp.status_code = 404
            resp.json.return_value = {}
        return resp

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        result = await fetcher.fetch()

    alert_found = any(
        "rename" in msg.lower() and "zai-org" in msg.lower()
        for msg in fetcher.org_rename_alerts
    )
    assert alert_found, "Expected org rename alert was not recorded on fetcher!"

    assert len(result.entries) > 0, "GitHub Org Fetcher returned empty despite rename!"
    assert "GLM-V" in result.entries[0].title


def test_every_configured_source_has_declared_cadence():
    """All sources in config/sources.yaml must have a declared expected_cadence_days > 0."""
    cfg = load_sources()
    for s in cfg.sources:
        if s.enabled:
            assert s.expected_cadence_days > 0, (
                f"Source '{s.name}' lacks declared expected_cadence_days!"
            )


@pytest.mark.asyncio
async def test_github_org_fetcher_respects_14_day_freshness(github_thudm_source: Source):
    """Repos pushed older than 14 days must be discarded by GitHubOrgFetcher."""
    fetcher = GitHubOrgFetcher(github_thudm_source)

    mock_repos = [
        {
            "name": "FreshRepo",
            "html_url": "https://github.com/zai-org/FreshRepo",
            "description": "Pushed 3 days ago",
            "pushed_at": (datetime.now(UTC) - timedelta(days=3)).isoformat() + "Z",
            "stargazers_count": 100,
        },
        {
            "name": "StaleRepo",
            "html_url": "https://github.com/zai-org/StaleRepo",
            "description": "Pushed 20 days ago (older than 14-day limit)",
            "pushed_at": (datetime.now(UTC) - timedelta(days=20)).isoformat() + "Z",
            "stargazers_count": 500,
        },
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.json.return_value = mock_repos

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await fetcher.fetch()

    assert result.status == FetchStatus.SUCCESS
    assert len(result.entries) == 1
    assert "FreshRepo" in result.entries[0].title
    assert "StaleRepo" not in [e.title for e in result.entries]
