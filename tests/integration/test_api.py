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
