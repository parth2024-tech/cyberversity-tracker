"""
Unit tests for Console delivery adapter.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_security_monitor.domain.entities import (
    Analysis,
    AnalysisModel,
    Category,
    Digest,
    Entry,
)
from ai_security_monitor.infrastructure.delivery.console_delivery import ConsoleDelivery


@pytest.fixture
def console_delivery():
    return ConsoleDelivery(config={})


@pytest.fixture
def sample_entry():
    return Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Test Emerging AI Architecture",
        url="https://github.com/example/ai-agent",
        content_hash="hash123",
        summary="A breakthrough test-time reasoning open-weight framework.",
        published_at=datetime.now(UTC),
        category=Category.AI_TECH,
        metadata={"source_name": "GitHub Trending"},
    )


@pytest.fixture
def sample_analysis(sample_entry):
    return Analysis(
        id=uuid4(),
        entry_id=sample_entry.id,
        attack_vector="API parameter injection",
        risk_assessment="High risk of unauthorized state mutation",
        mitigation="Enforce input schema validation and rate limiting",
        threat_velocity=85,
        severity_index=90,
        blast_radius_score=75,
        affected_ecosystem=["LangChain", "vLLM"],
        is_pre_cve_warning=True,
        attack_archetype="Prompt Injection",
        weaponization_potential="PoC Verified",
        model=AnalysisModel.HEURISTIC,
    )


@pytest.mark.asyncio
async def test_console_channel_name(console_delivery):
    assert console_delivery.channel_name == "console"
    console_delivery.validate_config()


@pytest.mark.asyncio
async def test_console_send_digest_success(
    console_delivery, sample_entry, sample_analysis, capsys
):
    digest = Digest(
        id=uuid4(),
        schedule="daily",
        entries_by_category={"ai_tech": [sample_entry]},
        total_entries=1,
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        delivery_channels=["console"],
    )

    result = await console_delivery.send_digest(
        digest=digest,
        entries_with_analysis=[(sample_entry, sample_analysis)],
    )

    assert result.success is True
    assert result.channel == "console"
    captured = capsys.readouterr()
    assert "DAILY DIGEST" in captured.out
    assert "Test Emerging AI Architecture" in captured.out
    assert "PRE-CVE WARNING" in captured.out
    assert "LangChain, vLLM" in captured.out


@pytest.mark.asyncio
async def test_console_send_digest_no_analysis(console_delivery, sample_entry, capsys):
    digest = Digest(
        id=uuid4(),
        schedule="weekly",
        entries_by_category={"ai_tech": [sample_entry]},
        total_entries=1,
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        delivery_channels=["console"],
    )

    result = await console_delivery.send_digest(
        digest=digest,
        entries_with_analysis=[(sample_entry, None)],
    )

    assert result.success is True
    captured = capsys.readouterr()
    assert "Not yet analyzed" in captured.out


@pytest.mark.asyncio
async def test_console_send_alert(
    console_delivery, sample_entry, sample_analysis, capsys
):
    result = await console_delivery.send_alert(
        entry=sample_entry,
        analysis=sample_analysis,
    )

    assert result.success is True
    assert result.channel == "console"
    captured = capsys.readouterr()
    assert "ALERT: High-velocity threat detected!" in captured.out
    assert "Prompt Injection" in captured.out
    assert "Enforce input schema validation" in captured.out
