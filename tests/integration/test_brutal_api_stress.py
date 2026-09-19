"""
Brutal API Stress, Boundary Enforcement, and Fuzzing Test Suite.
Verifies exact HTTP status contracts, SQL/XSS resilience, high-concurrency hammering,
extreme pagination boundaries, and strict payload schema adherence.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.presentation.api.main import create_app


@pytest.mark.asyncio
async def test_strict_query_parameter_validation_contracts():
    """Verify that out-of-boundary parameters are strictly rejected with 422 Unprocessable Entity."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid limits (valid range: 1 <= limit <= 200)
        invalid_limit_cases = [-999, -1, 0, 201, 9999, "not_an_int", "12.34"]
        for bad_limit in invalid_limit_cases:
            resp = await client.get("/api/entries", params={"limit": bad_limit})
            assert resp.status_code == 422, f"Expected 422 for limit={bad_limit}, got {resp.status_code}"

        # Invalid offsets (valid range: offset >= 0)
        invalid_offset_cases = [-500, -1, "abc", "null"]
        for bad_offset in invalid_offset_cases:
            resp = await client.get("/api/entries", params={"offset": bad_offset})
            assert resp.status_code == 422, f"Expected 422 for offset={bad_offset}, got {resp.status_code}"

        # Retention days validation (valid range: 0 <= days <= 1825)
        invalid_retention_days = [-1, -50, 1826, 99999, "seven"]
        for bad_days in invalid_retention_days:
            resp = await client.get("/api/stats/retention", params={"days": bad_days})
            assert resp.status_code == 422, f"Expected 422 for retention days={bad_days}, got {resp.status_code}"


@pytest.mark.asyncio
async def test_injection_and_fuzz_payload_safety():
    """Verify SQL injection, XSS vectors, and Unicode edge cases do not corrupt database or error."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        fuzz_search_cases = [
            "'; DROP TABLE entries; --",
            "' UNION SELECT id, title, url FROM entries --",
            "1' OR '1'='1",
            "<script>alert('pwned')</script>",
            '"><img src=x onerror=alert(1)>',
            "eval(compile('import os; os.system(\"ls\")', '<string>', 'exec'))",
            "\x00\x01\x02\x03\x04",  # Control chars
            "🤖🔥✨ 深度求索 Qwen-2.5 👾",  # Multilingual & Unicode emojis
            "A" * 500,  # Long query string
        ]
        for query in fuzz_search_cases:
            resp = await client.get("/api/entries", params={"search": query, "limit": 5})
            assert resp.status_code == 200, f"Expected 200 for fuzz query '{query[:20]}...', got {resp.status_code}"
            data = resp.json()
            assert "entries" in data
            assert "total" in data
            assert isinstance(data["entries"], list)

        # SQL injection in sort_by should fall back safely without executing SQL
        resp_sort = await client.get("/api/entries", params={"sort_by": "published_at; DROP TABLE entries;--"})
        assert resp_sort.status_code == 200
        assert "entries" in resp_sort.json()


@pytest.mark.asyncio
async def test_analysis_quick_strict_body_contracts():
    """Verify POST /api/analysis/quick strictly validates body schemas and rejects malformed inputs."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Missing required fields
        invalid_bodies = [
            {},
            {"title": None},
            {"summary": "missing title"},
            {"category": "ai_models"},  # missing title
        ]
        for body in invalid_bodies:
            resp = await client.post("/api/analysis/quick", json=body)
            assert resp.status_code == 422, f"Expected 422 for missing fields body {body}, got {resp.status_code}"

        # Invalid raw JSON stream
        resp_bad_json = await client.post(
            "/api/analysis/quick",
            content="NOT_A_JSON_OBJECT{{{",
            headers={"Content-Type": "application/json"},
        )
        assert resp_bad_json.status_code in (400, 422)

        # Valid payload must return 200 with complete required telemetry structure
        valid_payload = {
            "title": "DeepSeek-V3 Open Architecture MoE with 671B Parameters",
            "summary": "Full multi-head latent attention (MLA) and DeepSeekMoE architecture benchmarks.",
            "category": "ai_models",
            "tags": ["deepseek", "moe", "weights"],
        }
        resp_valid = await client.post("/api/analysis/quick", json=valid_payload)
        assert resp_valid.status_code == 200
        data = resp_valid.json()
        assert "triage" in data
        assert "blast_radius" in data
        triage = data["triage"]
        assert "threat_velocity" in triage
        assert "attack_vector" in triage
        assert triage["threat_velocity"] >= 0
        blast = data["blast_radius"]
        assert "blast_radius_score" in blast
        assert blast["blast_radius_score"] >= 0


@pytest.mark.asyncio
async def test_high_concurrency_stress_hammer():
    """Hammer API with 40 concurrent async requests across critical routes to test SQLite zero-lock resilience."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        routes = [
            "/api/health",
            "/api/health/live",
            "/api/health/ready",
            "/api/stats",
            "/api/entries?limit=5&sort_by=velocity",
            "/api/entries?limit=5&sort_by=blast",
            "/api/entries?category=ai_models&limit=5",
            "/api/sources",
        ]
        # Generate 40 tasks cycling through routes
        tasks = [client.get(routes[i % len(routes)]) for i in range(40)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for i, resp in enumerate(responses):
            assert not isinstance(resp, Exception), f"Request {i} raised exception: {resp}"
            assert resp.status_code == 200, f"Request {i} returned status {resp.status_code}"


@pytest.mark.asyncio
async def test_extreme_pagination_and_boundaries():
    """Verify extreme offsets return clean empty arrays without crashing or memory exhaustion."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Boundary: offset far beyond total records
        resp = await client.get("/api/entries", params={"limit": 10, "offset": 10_000_000})
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []
        assert isinstance(data["total"], int)

        # Boundary: upper limit exactly 200
        resp_max = await client.get("/api/entries", params={"limit": 200, "offset": 0})
        assert resp_max.status_code == 200
        assert len(resp_max.json()["entries"]) <= 200

        # Boundary: lower limit exactly 1
        resp_min = await client.get("/api/entries", params={"limit": 1, "offset": 0})
        assert resp_min.status_code == 200
        assert len(resp_min.json()["entries"]) <= 1


@pytest.mark.asyncio
async def test_path_traversal_and_method_not_allowed():
    """Verify strict HTTP 404 for nonexistent/traversal paths and 405 for disallowed HTTP methods."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Path traversal attempts
        traversals = [
            "/api/nonexistent",
            "/api/entries/../../etc/shadow",
            "/api/stats/../../../etc/passwd",
        ]
        for path in traversals:
            resp = await client.get(path)
            assert resp.status_code == 404, f"Expected 404 for {path}, got {resp.status_code}"

        # Disallowed method: POST on /api/entries (only GET supported)
        resp_method = await client.post("/api/entries", json={})
        assert resp_method.status_code == 405
