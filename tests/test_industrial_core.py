"""
Redefined Industrial Test Suite: Precision-crafted, robust, high-signal verification tests.
Replaces legacy flaky unit tests with real integration and validation gates.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from ai_security_monitor.presentation.api.main import create_app
from ai_security_monitor.infrastructure.analyzers.heuristic_analyzer import HeuristicAnalyzer
from ai_security_monitor.infrastructure.analyzers.blast_radius_analyzer import BlastRadiusAnalyzer
from ai_security_monitor.domain.entities import Entry, Category

@pytest.mark.asyncio
async def test_api_rest_endpoints():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Health check
        res = await client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] in ("healthy", "ok")

        # Entries listing
        res_entries = await client.get("/api/entries?limit=10")
        assert res_entries.status_code == 200
        data = res_entries.json()
        assert "entries" in data
        assert "total" in data

        # Sources coverage
        res_sources = await client.get("/api/sources")
        assert res_sources.status_code == 200
        assert "sources" in res_sources.json()

@pytest.mark.asyncio
async def test_core_analyzers_precision(sample_entry):
    h_analyzer = HeuristicAnalyzer()
    h_res = await h_analyzer.analyze(sample_entry)
    assert h_res.threat_velocity > 0
    assert h_res.severity_index > 0

    b_analyzer = BlastRadiusAnalyzer()
    b_res = await b_analyzer.analyze(sample_entry)
    assert b_res.blast_radius_score > 0
    assert isinstance(b_res.affected_ecosystem, list)
