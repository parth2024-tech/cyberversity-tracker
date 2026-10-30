"""Unit and integration tests for the China Intelligence Corridor."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.translation_service import (
    translation_service,
)
from ai_security_monitor.presentation.api.main import create_app


def test_translation_service_refines_ai_and_cyber_jargon():
    """Verify that _refine_ai_translation standardizes machine-translated text into researcher-grade terms."""
    raw_text = "Alibaba Qwen releases big model with thought chain reasoning and 40% video memory reduction."
    refined = translation_service._refine_ai_translation(raw_text, "zh-cn")
    assert "Foundation LLM" in refined or "Large Language Model" in refined
    assert "Chain-of-Thought (CoT)" in refined
    assert "VRAM" in refined

    cyber_text = "New 0day discovered with utilization code for right escalation."
    refined_cyber = translation_service._refine_ai_translation(cyber_text, "zh-cn")
    assert "Zero-Day" in refined_cyber
    assert "exploit PoC" in refined_cyber
    assert "privilege escalation" in refined_cyber


@pytest.mark.asyncio
async def test_china_overview_endpoint():
    """GET /api/china/overview should return researcher metrics, labs, and category counts."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/china/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "corridor" in data
        assert "total_entries" in data
        assert "by_category" in data
        assert "key_laboratories" in data
        assert len(data["key_laboratories"]) >= 5
        assert "coverage_pillars" in data


@pytest.mark.asyncio
async def test_china_glossary_endpoint():
    """GET /api/china/glossary should return bilingual researcher dictionary."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/china/glossary")
        assert resp.status_code == 200
        data = resp.json()
        assert "glossary" in data
        assert data["count"] > 0
        first = data["glossary"][0]
        assert "zh" in first
        assert "en" in first
        assert "category" in first


@pytest.mark.asyncio
async def test_entries_query_with_china_category_and_region():
    """GET /api/entries?category=china and region=china should return without error."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp_cat = await client.get("/api/entries?category=china&limit=5")
        assert resp_cat.status_code == 200
        data_cat = resp_cat.json()
        assert "entries" in data_cat
        assert "total" in data_cat

        resp_reg = await client.get("/api/entries?region=china&limit=5")
        assert resp_reg.status_code == 200
        data_reg = resp_reg.json()
        assert "entries" in data_reg
        assert "total" in data_reg


@pytest.mark.asyncio
async def test_china_export_endpoint():
    """GET /api/china/export should return static JSON snapshot with cache headers."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/china/export")
        assert resp.status_code == 200
        data = resp.json()
        assert "corridor" in data
        assert "total_entries" in data
        assert "key_laboratories" in data
        assert "Cache-Control" in resp.headers


@pytest.mark.asyncio
async def test_china_telemetry_endpoint():
    """GET /api/china/telemetry should return per-source yield, health, and signal-to-noise metrics."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/china/telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert "corridor" in data
        assert "total_sources" in data
        assert data["total_sources"] >= 10
        assert "sources" in data
        assert len(data["sources"]) == data["total_sources"]
        first_src = data["sources"][0]
        assert "source_name" in first_src
        assert "health_status" in first_src
        assert "signal_to_noise_ratio_pct" in first_src
        assert "diagnosis" in first_src
