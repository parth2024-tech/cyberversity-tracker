"""Unit tests for EmailDelivery."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import Analysis, Category, Digest, Entry
from ai_security_monitor.domain.exceptions import DeliveryConfigError
from ai_security_monitor.infrastructure.delivery.email_delivery import EmailDelivery


def make_email_config(**kwargs) -> dict:
    return {
        "smtp_server": "smtp.example.com",
        "smtp_port": 587,
        "username": "sender@example.com",
        "password": "s3cr3t",
        "from_email": "sender@example.com",
        "to_email": "recipient@example.com",
        **kwargs,
    }


@pytest.fixture
def email_delivery() -> EmailDelivery:
    return EmailDelivery(make_email_config())


@pytest.fixture
def sample_entry() -> Entry:
    return Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Llama 4 Open-Source Release by Meta AI",
        url="https://ai.meta.com/llama4",
        content_hash="b" * 64,
        summary="Meta releases Llama 4 with 405B parameters.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        tags=["meta", "llama", "open-source"],
    )


@pytest.fixture
def sample_analysis(sample_entry: Entry) -> Analysis:
    return Analysis(
        id=uuid4(),
        entry_id=sample_entry.id,
        attack_vector="Open-Weights Release",
        risk_assessment="High-velocity community adoption",
        mitigation="Benchmark against current production baselines",
        threat_velocity=88,
        severity_index=80,
    )


def test_email_delivery_missing_config_raises():
    """EmailDelivery should raise DeliveryConfigError when required fields are missing."""
    with pytest.raises(DeliveryConfigError):
        EmailDelivery({"smtp_server": "smtp.example.com", "smtp_port": 587})  # missing many fields


def test_email_delivery_valid_config_instantiates():
    """EmailDelivery with full config should instantiate correctly."""
    delivery = EmailDelivery(make_email_config())
    assert delivery.channel_name == "email"


@pytest.mark.asyncio
async def test_send_alert_success(email_delivery: EmailDelivery, sample_entry: Entry, sample_analysis: Analysis):
    """send_alert should call SMTP server and return success."""
    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=None)
    mock_smtp.starttls = MagicMock()
    mock_smtp.login = MagicMock()
    mock_smtp.send_message = MagicMock()

    with patch("ai_security_monitor.infrastructure.delivery.email_delivery.smtplib.SMTP", return_value=mock_smtp):
        result = await email_delivery.send_alert(sample_entry, sample_analysis)

    assert result.success is True
    assert mock_smtp.send_message.called


@pytest.mark.asyncio
async def test_send_alert_smtp_error_returns_failure(
    email_delivery: EmailDelivery, sample_entry: Entry, sample_analysis: Analysis
):
    """send_alert should return failure result when SMTP raises an exception."""
    with patch(
        "ai_security_monitor.infrastructure.delivery.email_delivery.smtplib.SMTP",
        side_effect=Exception("Connection refused"),
    ):
        result = await email_delivery.send_alert(sample_entry, sample_analysis)

    assert result.success is False
    assert "Connection refused" in result.error


@pytest.mark.asyncio
async def test_send_newspaper_missing_pdf_returns_failure(email_delivery: EmailDelivery):
    """send_newspaper_pdf should return failure when PDF file doesn't exist."""
    result = await email_delivery.send_newspaper_pdf(
        pdf_path="/tmp/no_such_file_xyz.pdf",
        edition_number=42,
    )
    assert result.success is False


def test_build_html_body_contains_title(
    email_delivery: EmailDelivery, sample_entry: Entry, sample_analysis: Analysis
):
    """_build_html_body should include entry titles in HTML output."""
    digest = Digest(
        id=uuid4(),
        schedule="daily",
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        total_entries=1,
        entries_by_category={"ai_models": [str(sample_entry.id)]},
    )
    html = email_delivery._build_html_body(digest, [(sample_entry, sample_analysis)])
    assert "Llama 4" in html
    assert "<html>" in html.lower()
