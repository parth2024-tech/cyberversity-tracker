"""
Integration tests for FastAPI REST API.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.presentation.api.main import create_app


@pytest.mark.asyncio
async def test_health_endpoints():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "ok")


@pytest.mark.asyncio
async def test_quick_analyze_endpoint():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "title": "Critical RCE vulnerability in LangChain and PyTorch worker nodes",
            "summary": "Attacker can supply malicious pickle payload to execute arbitrary code.",
            "category": "vulnerabilities",
            "tags": ["pytorch", "langchain", "rce"]
        }
        resp = await client.post("/api/analysis/quick", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "triage" in data
        assert "blast_radius" in data
        assert data["blast_radius"]["blast_radius_score"] >= 1


@pytest.mark.asyncio
async def test_entries_sorting():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test sorting by velocity
        resp = await client.get("/api/entries?sort_by=velocity&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "total" in data
        assert isinstance(data["entries"], list)

        # Test sorting by blast radius
        resp_blast = await client.get("/api/entries?sort_by=blast&limit=5")
        assert resp_blast.status_code == 200
        data_blast = resp_blast.json()
        assert "entries" in data_blast

        # Test triage queue status endpoint
        resp_q = await client.get("/api/triage/queue")
        assert resp_q.status_code == 200
        q_data = resp_q.json()
        assert "queue_size" in q_data
        assert "is_processing" in q_data


@pytest.mark.asyncio
async def test_entries_regional_filtering():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Query Europe region
        resp_eu = await client.get("/api/entries?region=europe&limit=5")
        assert resp_eu.status_code == 200
        data_eu = resp_eu.json()
        assert "entries" in data_eu
        for e in data_eu["entries"]:
            assert e.get("region") == "europe"

        # Query North America region
        resp_na = await client.get("/api/entries?region=north_america&limit=5")
        assert resp_na.status_code == 200
        data_na = resp_na.json()
        assert "entries" in data_na
        for e in data_na["entries"]:
            assert e.get("region") == "north_america"


@pytest.mark.asyncio
async def test_sources_worldwide_coverage():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert "sources" in data
        sources = data["sources"]
        regions = {s.get("config", {}).get("region") for s in sources}
        assert "europe" in regions
        assert "north_america" in regions
        assert "apac" in regions
        assert "global" in regions


@pytest.mark.asyncio
async def test_omni_domain_categories():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Verify that all new categories are recognized without 422 or 500
        for cat in ("ai_models", "cyber_tools", "exploits_tricks"):
            resp = await client.get(f"/api/entries?category={cat}&limit=5")
            assert resp.status_code == 200
            data = resp.json()
            assert "entries" in data
            assert "total" in data


@pytest.mark.asyncio
async def test_stats_endpoint_returns_structure():
    """GET /api/stats should return required keys for the dashboard."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        # Required top-level fields
        assert "total_entries" in data
        assert "by_category" in data
        assert "total_sources" in data
        assert isinstance(data["total_entries"], int)
        assert isinstance(data["by_category"], dict)


@pytest.mark.asyncio
async def test_entries_pagination():
    """GET /api/entries with limit and offset should respect pagination."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp_page1 = await client.get("/api/entries?limit=5&offset=0")
        assert resp_page1.status_code == 200

        resp_page2 = await client.get("/api/entries?limit=5&offset=5")
        assert resp_page2.status_code == 200

        data1 = resp_page1.json()
        data2 = resp_page2.json()
        assert "entries" in data1
        assert "entries" in data2

        # IDs should not overlap (or both empty when no entries in DB)
        ids1 = {e["id"] for e in data1["entries"]}
        ids2 = {e["id"] for e in data2["entries"]}
        assert ids1.isdisjoint(ids2) or (not ids1 and not ids2)


@pytest.mark.asyncio
async def test_sweep_status_endpoint():
    """GET /api/stats/sweep-status should return sweep telemetry."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/stats/sweep-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "sweep_count" in data or "last_sweep_at" in data or "sources" in data


@pytest.mark.asyncio
async def test_entries_invalid_limit_rejected():
    """GET /api/entries with limit > 200 should return 422 validation error."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/entries?limit=9999")
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_openapi_schema_not_exposed_in_test_mode():
    """OpenAPI docs endpoint should not return 500 (may be disabled in prod)."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/docs")
        # Either available (200) or not found (404) — never a server error
        assert resp.status_code in (200, 404)
