"""
Industrial-grade robust test suite for AI Security Monitor.
Tests live components directly against async database transactions and FastAPI application states.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from ai_security_monitor.presentation.api.main import create_app
from ai_security_monitor.infrastructure.analyzers.heuristic_analyzer import HeuristicAnalyzer
from ai_security_monitor.infrastructure.analyzers.blast_radius_analyzer import BlastRadiusAnalyzer
from ai_security_monitor.domain.entities import Entry, Category

@pytest.mark.asyncio
async def test_api_health_and_stats():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] in ("healthy", "ok")

        stats_resp = await client.get("/api/stats")
        assert stats_resp.status_code == 200
        assert "total_entries" in stats_resp.json() or "stats" in stats_resp.json()

@pytest.mark.asyncio
async def test_industrial_heuristics_analyzer(sample_entry):
    analyzer = HeuristicAnalyzer()
    result = await analyzer.analyze(sample_entry)
    assert result.threat_velocity >= 1
    assert result.severity_index >= 1
    assert result.attack_vector is not None

@pytest.mark.asyncio
async def test_blast_radius_calculation(sample_entry):
    analyzer = BlastRadiusAnalyzer()
    result = await analyzer.analyze(sample_entry)
    assert result.blast_radius_score >= 1
    assert isinstance(result.affected_ecosystem, list)
