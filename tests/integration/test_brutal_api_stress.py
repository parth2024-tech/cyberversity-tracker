"""
Brutal API Stress and Fuzzing Test Suite for AI Security Monitor.
Attacks every endpoint with malformed payloads, SQL/XSS injections, rapid concurrent requests,
invalid query parameters, missing fields, and boundary-pushing inputs to test resilience.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from ai_security_monitor.presentation.api.main import create_app

@pytest.mark.asyncio
async def test_brutal_fuzz_api_endpoints():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        
        # 1. Fuzzing GET /api/entries with garbage parameters
        garbage_params = [
            {"limit": -999, "offset": -1},
            {"limit": "NOT_AN_INT", "offset": "abc"},
            {"sort_by": "DROP TABLE entries;--"},
            {"region": "<script>alert(1)</script>"},
            {"category": "INVALID_CAT_ENUM"},
            {"search": "'; EXEC xp_cmdshell('calc'); --"}
        ]
        for params in garbage_params:
            resp = await client.get("/api/entries", params=params)
            # FastAPI validation should reject bad types with 422 or handle safely with 200/400
            assert resp.status_code in (200, 400, 422)

        # 2. Fuzzing POST /api/analysis/quick with malformed payloads
        malformed_payloads = [
            {},
            {"title": ""},
            {"title": "A" * 10000, "summary": "Overflow test"},
            {"title": None, "summary": None},
            {"title": "<script>fetch('http://evil.com')</script>", "summary": "XSS vector"},
            {"title": "SQL Injection", "summary": "' OR 1=1; --"}
        ]
        for payload in malformed_payloads:
            resp = await client.post("/api/analysis/quick", json=payload)
            assert resp.status_code in (200, 400, 422)

        # 3. Hammering rate limits / concurrent requests on health and stats
        for _ in range(50):
            r = await client.get("/api/health")
            assert r.status_code == 200

        # 4. Non-existent routes / path traversal fuzzing
        bad_routes = [
            "/api/nonexistent",
            "/api/entries/../../etc/passwd",
            "/api/analysis/quick/../../admin",
            "/metrics/../../../"
        ]
        for route in bad_routes:
            resp = await client.get(route)
            assert resp.status_code in (200, 404, 405, 422, 400)

        # 5. Invalid JSON body structure
        resp = await client.post("/api/analysis/quick", content="INVALID_JSON_STREAM")
        assert resp.status_code in (400, 422)
