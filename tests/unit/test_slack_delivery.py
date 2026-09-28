"""
Unit tests for Slack delivery adapter.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import (
    Analysis,
    AnalysisModel,
    Category,
    Digest,
    Entry,
)
from ai_security_monitor.domain.exceptions import DeliveryConfigError
from ai_security_monitor.infrastructure.delivery.slack_delivery import SlackDelivery


@pytest.fixture
def slack_delivery():
    return SlackDelivery(
        config={"webhook_url": "https://hooks.slack.com/services/T00/B00/X00"}
    )


@pytest.fixture
def sample_entry():
    return Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Breakthrough Reasoning Engine",
        url="https://github.com/example/reasoning",
        content_hash="hash456",
        summary="Sovereign AI reasoning runtime using quantized weights.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        metadata={"source_name": "ArXiv AI"},
    )


@pytest.fixture
def sample_analysis(sample_entry):
    return Analysis(
        id=uuid4(),
        entry_id=sample_entry.id,
        attack_vector="Model weight tampering",
        risk_assessment="Integrity violation",
        mitigation="Cryptographic checksums",
        threat_velocity=95,
        severity_index=88,
        blast_radius_score=80,
        affected_ecosystem=["Ollama", "llama.cpp"],
        is_pre_cve_warning=True,
        attack_archetype="Supply Chain",
        weaponization_potential="Active Weaponization",
        model=AnalysisModel.HEURISTIC,
    )


def test_slack_config_validation():
    with pytest.raises(DeliveryConfigError):
        SlackDelivery(config={})

    delivery = SlackDelivery(config={"webhook_url": "https://hooks.slack.com/valid"})
    assert delivery.channel_name == "slack"


@pytest.mark.asyncio
async def test_slack_send_digest_success(slack_delivery, sample_entry, sample_analysis):
    digest = Digest(
        id=uuid4(),
        schedule="daily",
        entries_by_category={"ai_models": [sample_entry]},
        total_entries=1,
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        delivery_channels=["slack"],
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", return_value=mock_response):
        result = await slack_delivery.send_digest(
            digest=digest,
            entries_with_analysis=[(sample_entry, sample_analysis)],
        )

    assert result.success is True
    assert result.channel == "slack"


@pytest.mark.asyncio
async def test_slack_send_digest_failure(slack_delivery, sample_entry):
    digest = Digest(
        id=uuid4(),
        schedule="daily",
        entries_by_category={"ai_models": [sample_entry]},
        total_entries=1,
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        delivery_channels=["slack"],
    )

    with patch(
        "httpx.AsyncClient.post", side_effect=Exception("Webhook network error")
    ):
        result = await slack_delivery.send_digest(
            digest=digest,
            entries_with_analysis=[(sample_entry, None)],
        )

    assert result.success is False
    assert "Webhook network error" in result.error


@pytest.mark.asyncio
async def test_slack_send_alert(slack_delivery, sample_entry, sample_analysis):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", return_value=mock_response):
        result = await slack_delivery.send_alert(
            entry=sample_entry,
            analysis=sample_analysis,
        )

    assert result.success is True
    assert result.channel == "slack"
