"""
Test suite for Worldwide Intelligence Coverage (Tier 1 & Tier 2 countries).
Verifies source configuration, domain filtering, API query endpoints,
and sovereign newspaper editorial generation.
"""

import uuid
from datetime import UTC, datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.newspaper_service import NewspaperService
from ai_security_monitor.config.sources import load_sources
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.presentation.api.main import create_app


def test_tier1_sources_configured():
    """Verify that every single Tier 1 country has dedicated, enabled sources configured."""
    config = load_sources()
    tier1_countries = {
        "US": "United States",
        "CN": "China",
        "GB": "United Kingdom",
        "IN": "India",
        "EU": "European Union",
        "IL": "Israel",
        "JP": "Japan",
        "KR": "South Korea",
    }

    configured_countries = {s.country for s in config.sources if s.enabled}

    for code, name in tier1_countries.items():
        assert code in configured_countries, (
            f"Tier 1 country {name} ({code}) is missing enabled sources in config/sources.yaml"
        )
        country_sources = [s for s in config.sources if s.country == code and s.enabled]
        assert len(country_sources) >= 1, (
            f"Expected at least 1 active source for {name} ({code})"
        )


def test_tier2_sources_configured():
    """Verify that every single Tier 2 country has dedicated sources configured."""
    config = load_sources()
    tier2_countries = {
        "CA": "Canada",
        "DE": "Germany",
        "FR": "France",
        "SG": "Singapore",
        "TW": "Taiwan",
        "AE": "United Arab Emirates",
        "AU": "Australia",
        "NL": "Netherlands",
        "FI": "Finland",
        "SE": "Sweden",
        "CH": "Switzerland",
    }

    configured_countries = {s.country for s in config.sources}

    for code, name in tier2_countries.items():
        assert code in configured_countries, (
            f"Tier 2 country {name} ({code}) is missing sources in config/sources.yaml"
        )
        country_sources = [s for s in config.sources if s.country == code]
        assert len(country_sources) >= 1, (
            f"Expected at least 1 source for {name} ({code})"
        )


def test_worldwide_sources_taxonomy_and_balance():
    """Verify that worldwide feeds cover AI technology, models, research, and infrastructure."""
    config = load_sources()
    all_categories = {s.category for s in config.sources}
    enabled_categories = {s.category for s in config.sources if s.enabled}

    # Verify all major pillars are configured in taxonomy
    assert "ai_tech" in enabled_categories
    assert "ai_research" in enabled_categories
    assert "ai_models" in enabled_categories
    assert "cyber_tools" in enabled_categories
    assert "github_trending" in enabled_categories
    assert "cybersecurity" in all_categories
    assert "vulnerabilities" in all_categories

    # Verify total source count expanded
    assert len(config.sources) >= 100, (
        f"Expected 100+ configured sources, got {len(config.sources)}"
    )


@pytest.mark.asyncio
async def test_api_entries_country_filter():
    """Verify querying /api/entries with country parameter."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Query with country filter (e.g. US)
        resp_us = await client.get("/api/entries?country=US&limit=10")
        assert resp_us.status_code == 200
        data_us = resp_us.json()
        assert "entries" in data_us
        assert "total" in data_us

        # Query with another country (e.g. CN)
        resp_cn = await client.get("/api/entries?country=CN&limit=10")
        assert resp_cn.status_code == 200
        data_cn = resp_cn.json()
        assert "entries" in data_cn
        assert "total" in data_cn


@pytest.mark.asyncio
async def test_api_entries_regional_theatre_clusters():
    """Verify querying /api/entries with new regional theatre clusters."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for reg in (
            "south_asia",
            "middle_east",
            "nordic",
            "apac",
            "europe",
            "north_america",
            "china",
        ):
            resp = await client.get(f"/api/entries?region={reg}&limit=5")
            assert resp.status_code == 200
            data = resp.json()
            assert "entries" in data
            assert "total" in data


@pytest.mark.asyncio
async def test_newspaper_worldwide_sovereign_radar_integration():
    """Verify newspaper service categorizes worldwide sovereign entries and compiles all formats."""
    # Create sample entries representing Tier 1 & Tier 2 sovereign nodes
    sample_entries = [
        Entry(
            id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            title="CERT-In Advisory: Critical Remote Execution in Government Cloud Infrastructure",
            url="https://cert-in.org.in/advisory-01",
            content_hash="test_in_01",
            summary="Indian Computer Emergency Response Team flags high-severity flaws in public perimeter gateways.",
            published_at=datetime.now(UTC),
            category=Category.CYBERSECURITY,
            tags=["India", "CERT-In", "RCE"],
            metadata={"region": "south_asia", "country": "IN"},
        ),
        Entry(
            id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            title="TII Abu Dhabi Unveils Falcon 3: 40B Open Foundation Model with Reasoning Kernels",
            url="https://tii.ae/falcon-3",
            content_hash="test_ae_01",
            summary="Technology Innovation Institute releases Falcon 3 with high-throughput inference weights.",
            published_at=datetime.now(UTC),
            category=Category.AI_MODELS,
            tags=["Falcon", "TII", "UAE", "OpenWeights"],
            metadata={"region": "middle_east", "country": "AE"},
        ),
        Entry(
            id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            title="TSMC & ITRI Demonstrate 2nm High-Efficiency AI Accelerator Foundry",
            url="https://digitimes.com/tsmc-2nm",
            content_hash="test_tw_01",
            summary="Taiwan semiconductor ecosystem advances next-generation lithography for edge AI clusters.",
            published_at=datetime.now(UTC),
            category=Category.AI_TECH,
            tags=["TSMC", "Hardware", "Taiwan", "Semiconductor"],
            metadata={"region": "apac", "country": "TW"},
        ),
        Entry(
            id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            title="Check Point Research: Evasive Zero-Day Exploitation in Managed Perimeter Firewalls",
            url="https://research.checkpoint.com/0day-01",
            content_hash="test_il_01",
            summary="Israeli threat intelligence researchers detect active campaign bypassing authentication.",
            published_at=datetime.now(UTC),
            category=Category.CYBERSECURITY,
            tags=["Israel", "CheckPoint", "0day", "ThreatIntel"],
            metadata={"region": "middle_east", "country": "IL"},
        ),
    ]

    service = NewspaperService()
    categorized = await service._categorize_entries(sample_entries)

    # Sovereign / Regional radar should capture these entries
    assert "sovereign_ai" in categorized
    sov_radar = categorized["sovereign_ai"]
    assert len(sov_radar) >= 1

    # Verify Markdown generation includes Section VII / Page 7 with sovereign items
    md = service._render_markdown(
        sample_entries, categorized, 101, datetime.now(UTC), 24
    )
    assert "[PAGE 7] SOVEREIGN AI" in md
