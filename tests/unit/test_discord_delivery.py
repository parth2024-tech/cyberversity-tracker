"""Unit tests for Discord delivery adapter."""

from __future__ import annotations

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
from ai_security_monitor.infrastructure.delivery.discord_delivery import DiscordDelivery


@pytest.fixture
def discord_delivery():
    return DiscordDelivery(
        config={"webhook_url": "https://discord.com/api/webhooks/123/xyz"}
    )


@pytest.fixture
def sample_entry():
    return Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="DeepSeek R1 Released with Test-Time Scaling",
        url="https://github.com/deepseek-ai/DeepSeek-R1",
        content_hash="hash123",
        summary="Next generation reasoning foundation model.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        metadata={"source_name": "GitHub Trending"},
    )


@pytest.fixture
def sample_analysis(sample_entry):
    return Analysis(
        id=uuid4(),
        entry_id=sample_entry.id,
        attack_vector="N/A (Model Architecture)",
        risk_assessment="Frontier model benchmark advancement",
        mitigation="Evaluate inference memory and quantization",
        threat_velocity=95,
        severity_index=80,
        blast_radius_score=85,
        affected_ecosystem=["vLLM", "Ollama", "SGLang"],
        is_pre_cve_warning=False,
        attack_archetype="Reasoning Paradigm",
        weaponization_potential="Open Weights Release",
        model=AnalysisModel.HEURISTIC,
    )


@pytest.mark.asyncio
async def test_discord_delivery_validation():
    """Missing webhook_url should raise DeliveryConfigError."""
    with pytest.raises(DeliveryConfigError):
        DiscordDelivery(config={})


@pytest.mark.asyncio
async def test_discord_send_alert(discord_delivery, sample_entry, sample_analysis):
    """DiscordDelivery should send alert embed to webhook."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
        result = await discord_delivery.send_alert(sample_entry, sample_analysis)
        assert result.success is True
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        assert "embeds" in payload
        embed = payload["embeds"][0]
        assert "DeepSeek R1" in embed["title"]


@pytest.mark.asyncio
async def test_discord_send_digest(discord_delivery, sample_entry, sample_analysis):
    """DiscordDelivery should format and send multi-embed digest."""
    digest = Digest(
        id=uuid4(),
        schedule="daily",
        entries_by_category={"ai_models": [sample_entry]},
        total_entries=1,
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        delivery_channels=["discord"],
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
        result = await discord_delivery.send_digest(
            digest, [(sample_entry, sample_analysis)]
        )
        assert result.success is True
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        assert len(payload["embeds"]) >= 2
        assert "AETHERGUARD" in payload["embeds"][0]["footer"]["text"]
