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
