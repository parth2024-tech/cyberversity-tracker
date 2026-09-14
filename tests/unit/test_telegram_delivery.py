"""Unit tests for TelegramDelivery."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import Analysis, Category, Digest, Entry
from ai_security_monitor.domain.exceptions import DeliveryConfigError
from ai_security_monitor.infrastructure.delivery.telegram_delivery import (
    TelegramDelivery,
)


def make_config(**kwargs) -> dict:
    return {"bot_token": "test_token_123", "chat_id": "-100999888", **kwargs}


@pytest.fixture
def tg_delivery() -> TelegramDelivery:
    return TelegramDelivery(make_config())


@pytest.fixture
def sample_entry() -> Entry:
    return Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="GPT-5 Released with Multimodal Reasoning",
        url="https://openai.com/gpt5",
        content_hash="a" * 64,
        summary="OpenAI releases GPT-5 with native code execution.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        tags=["openai", "gpt", "llm"],
    )


@pytest.fixture
def sample_analysis(sample_entry: Entry) -> Analysis:
    return Analysis(
        id=uuid4(),
        entry_id=sample_entry.id,
        attack_vector="Foundation Model Release",
        risk_assessment="Major model capability jump",
        mitigation="Evaluate fine-tuning and deployment feasibility",
        threat_velocity=90,
        severity_index=85,
    )


def test_telegram_delivery_missing_config_raises():
    """TelegramDelivery should raise DeliveryConfigError if required config keys are missing."""
    with pytest.raises(DeliveryConfigError):
        TelegramDelivery({"bot_token": "tok"})  # missing chat_id


def test_telegram_delivery_valid_config_does_not_raise():
    """TelegramDelivery with valid config should instantiate without error."""
    delivery = TelegramDelivery(make_config())
    assert delivery.channel_name == "telegram"


@pytest.mark.asyncio
async def test_send_alert_success(
    tg_delivery: TelegramDelivery, sample_entry: Entry, sample_analysis: Analysis
):
    """send_alert should POST to Telegram Bot API and return success result."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.delivery.telegram_delivery.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await tg_delivery.send_alert(sample_entry, sample_analysis)

    assert result.success is True
    assert result.channel == "telegram"
    assert mock_client.post.called
    call_kwargs = mock_client.post.call_args
    assert "sendMessage" in call_kwargs[0][0]


@pytest.mark.asyncio
async def test_send_alert_http_error_returns_failure(
    tg_delivery: TelegramDelivery, sample_entry: Entry, sample_analysis: Analysis
):
    """send_alert should return failure result when HTTP error occurs."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("HTTP 403 Forbidden"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "ai_security_monitor.infrastructure.delivery.telegram_delivery.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await tg_delivery.send_alert(sample_entry, sample_analysis)

    assert result.success is False
    assert "403" in result.error


@pytest.mark.asyncio
async def test_send_newspaper_missing_file_returns_failure(
    tg_delivery: TelegramDelivery,
):
    """send_newspaper_document should return failure if PDF file doesn't exist."""
    result = await tg_delivery.send_newspaper_document(
        pdf_path="/tmp/does_not_exist_xyz.pdf",
        edition_number=42,
    )
    assert result.success is False
    assert "not found" in result.error.lower() or "PDF" in result.error


def test_escape_html_special_chars(tg_delivery: TelegramDelivery):
    """_escape_html should properly escape HTML special characters."""
    text = '<script>alert("xss")</script>'
    escaped = tg_delivery._escape_html(text)
    assert "<script>" not in escaped
    assert "&lt;" in escaped
