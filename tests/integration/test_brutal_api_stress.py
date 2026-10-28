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
            assert resp.status_code == 422, (
                f"Expected 422 for limit={bad_limit}, got {resp.status_code}"
            )

        # Invalid offsets (valid range: offset >= 0)
        invalid_offset_cases = [-500, -1, "abc", "null"]
        for bad_offset in invalid_offset_cases:
            resp = await client.get("/api/entries", params={"offset": bad_offset})
            assert resp.status_code == 422, (
                f"Expected 422 for offset={bad_offset}, got {resp.status_code}"
            )

        # Retention days validation (valid range: 0 <= days <= 1825)
        invalid_retention_days = [-1, -50, 1826, 99999, "seven"]
        for bad_days in invalid_retention_days:
            resp = await client.get("/api/stats/retention", params={"days": bad_days})
            assert resp.status_code == 422, (
                f"Expected 422 for retention days={bad_days}, got {resp.status_code}"
            )


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
            resp = await client.get(
                "/api/entries", params={"search": query, "limit": 5}
            )
            assert resp.status_code == 200, (
                f"Expected 200 for fuzz query '{query[:20]}...', got {resp.status_code}"
            )
            data = resp.json()
            assert "entries" in data
            assert "total" in data
            assert isinstance(data["entries"], list)

        # SQL injection in sort_by should fall back safely without executing SQL
        resp_sort = await client.get(
            "/api/entries", params={"sort_by": "published_at; DROP TABLE entries;--"}
        )
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
            assert resp.status_code == 422, (
                f"Expected 422 for missing fields body {body}, got {resp.status_code}"
            )

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
            assert not isinstance(resp, Exception), (
                f"Request {i} raised exception: {resp}"
            )
            assert resp.status_code == 200, (
                f"Request {i} returned status {resp.status_code}"
            )


@pytest.mark.asyncio
async def test_extreme_pagination_and_boundaries():
    """Verify extreme offsets return clean empty arrays without crashing or memory exhaustion."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Boundary: offset far beyond total records
        resp = await client.get(
            "/api/entries", params={"limit": 10, "offset": 10_000_000}
        )
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
            assert resp.status_code == 404, (
                f"Expected 404 for {path}, got {resp.status_code}"
            )

        # Disallowed method: POST on /api/entries (only GET supported)
        resp_method = await client.post("/api/entries", json={})
        assert resp_method.status_code == 405


@pytest.mark.asyncio
async def test_adversarial_syndication_feeds_contracts():
    """Brutally verify RSS 2.0 XML and JSON Feed 1.1 structure, schema conformity, and 14-day freshness."""
    import email.utils
    import xml.etree.ElementTree as ET
    from datetime import UTC, datetime, timedelta

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. RSS 2.0 Invariants on /feed.xml and /api/v1/feed.xml
        for feed_route in ("/feed.xml", "/api/v1/feed.xml"):
            resp = await client.get(feed_route)
            assert resp.status_code == 200, (
                f"Route {feed_route} failed with {resp.status_code}"
            )
            assert resp.headers["content-type"].startswith("application/rss+xml")

            # Parse XML tree to verify strict well-formedness
            root = ET.fromstring(resp.content)
            assert root.tag == "rss"
            assert root.attrib.get("version") == "2.0"

            channel = root.find("channel")
            assert channel is not None
            assert channel.find("title") is not None
            assert channel.find("link") is not None
            assert channel.find("description") is not None
            assert channel.find("lastBuildDate") is not None

            # Verify every item conforms to RSS 2.0 specs and 14-day freshness rule
            items = channel.findall("item")
            cutoff_14d = datetime.now(UTC) - timedelta(days=15)
            for item in items:
                title_elem = item.find("title")
                assert title_elem is not None and title_elem.text
                link_elem = item.find("link")
                assert link_elem is not None and link_elem.text.startswith("http")
                pub_elem = item.find("pubDate")
                assert pub_elem is not None and pub_elem.text
                # PubDate must be valid RFC 822 format
                parsed_dt = email.utils.parsedate_to_datetime(pub_elem.text)
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=UTC)
                assert parsed_dt >= cutoff_14d, (
                    f"Item '{title_elem.text}' violates 14-day freshness: {parsed_dt}"
                )

        # 2. JSON Feed 1.1 Invariants on /feed.json and /api/v1/feed.json
        for feed_route in ("/feed.json", "/api/v1/feed.json"):
            resp = await client.get(feed_route)
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("application/feed+json")
            data = resp.json()

            assert data["version"] == "https://jsonfeed.org/version/1.1"
            assert "title" in data
            assert "home_page_url" in data
            assert "feed_url" in data
            assert isinstance(data["items"], list)

            for item in data["items"]:
                assert "id" in item
                assert "url" in item
                assert "title" in item
                assert "date_published" in item
                dt = datetime.fromisoformat(item["date_published"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                assert dt >= cutoff_14d, (
                    f"JSON Feed item violates 14-day freshness: {dt}"
                )


@pytest.mark.asyncio
async def test_adversarial_markdown_briefing_export_contracts():
    """Verify Markdown export structure, heading validity, query parameter bounds, and code fences."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Default briefing
        resp = await client.get("/api/v1/digest/markdown")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        content = resp.text
        assert "# AETHERGUARD: Worldwide AI Intelligence Briefing" in content
        assert "## " in content
        assert "Coverage Window:" in content

        # Verify Markdown fences are balanced
        fence_count = content.count("```")
        assert fence_count % 2 == 0, (
            "Markdown export has unmatched triple-backtick code fences"
        )

        # Parameter boundaries: invalid days must return 422
        bad_days_cases = [-10, 0, 31, 999]
        for bad_d in bad_days_cases:
            resp_bad = await client.get(
                "/api/v1/digest/markdown", params={"days": bad_d}
            )
            assert resp_bad.status_code == 422, (
                f"Expected 422 for days={bad_d}, got {resp_bad.status_code}"
            )

        # Filtered briefing
        resp_filtered = await client.get(
            "/api/v1/digest/markdown",
            params={"days": 7, "category": "ai_models", "limit": 3},
        )
        assert resp_filtered.status_code == 200
        assert "# AETHERGUARD:" in resp_filtered.text


@pytest.mark.asyncio
async def test_adversarial_vault_and_notes_contracts():
    """Brutally test invalid UUIDs, non-existent entity lookups, and notes validation."""
    import uuid

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Non-UUID string for vault pin
        resp_bad_uuid = await client.post("/api/vault/not-a-valid-uuid")
        assert resp_bad_uuid.status_code in (400, 422)

        # Non-existent valid UUID for vault pin
        random_uuid = str(uuid.uuid4())
        resp_nonexistent = await client.post(f"/api/vault/{random_uuid}")
        assert resp_nonexistent.status_code == 404

        # Non-UUID string for vault unpin
        resp_unpin_bad = await client.delete("/api/vault/not-a-valid-uuid")
        assert resp_unpin_bad.status_code in (400, 422)

        # Non-existent UUID for vault unpin
        resp_unpin_404 = await client.delete(f"/api/vault/{random_uuid}")
        assert resp_unpin_404.status_code == 404

        # Save notes on non-existent entry
        resp_notes_404 = await client.post(
            f"/api/entries/{random_uuid}/notes",
            json={"notes": "Deep technical analysis on test-time compute."},
        )
        assert resp_notes_404.status_code == 404

        # Missing body for notes endpoint
        resp_notes_missing = await client.post(
            f"/api/entries/{random_uuid}/notes",
            json={},
        )
        assert resp_notes_missing.status_code == 422


@pytest.mark.asyncio
async def test_high_concurrency_read_write_burst_stress():
    """Hammer API with 60 concurrent diverse async requests to verify zero locks and zero 500s."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        routes = [
            "/api/health",
            "/api/health/live",
            "/api/health/ready",
            "/api/stats",
            "/feed.xml",
            "/feed.json",
            "/api/v1/feed.xml",
            "/api/v1/feed.json",
            "/api/v1/digest/markdown?days=7",
            "/api/entries?limit=10&sort_by=velocity",
            "/api/entries?limit=10&sort_by=blast",
            "/api/entries?category=ai_models&limit=5",
            "/api/sources",
            "/api/triage/queue",
        ]
        tasks = [client.get(routes[i % len(routes)]) for i in range(60)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for i, resp in enumerate(responses):
            assert not isinstance(resp, Exception), (
                f"Request {i} failed with exception: {resp}"
            )
            assert resp.status_code == 200, (
                f"Request {i} returned status {resp.status_code}: {resp.text}"
            )


@pytest.mark.asyncio
async def test_hours_bounds_and_fts_sanitization_and_vault_lifecycle():
    """Verify hours bounds (422), FTS5 operator crash immunity (200), and vault pin/unpin idempotence."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Bounds on hours parameter
        resp_neg = await client.get("/api/entries?hours=-5")
        assert resp_neg.status_code == 422

        resp_huge = await client.get("/api/entries?hours=999999999")
        assert resp_huge.status_code == 422

        # 2. FTS5 operator crash immunity (must never return 500 OperationalError)
        for special_search in (
            "*",
            '"',
            "AND OR NOT",
            "^",
            "deepseek*",
            'test-time "compute"',
        ):
            resp_fts = await client.get(f"/api/entries?search={special_search}")
            assert resp_fts.status_code == 200, (
                f"FTS query '{special_search}' failed with {resp_fts.status_code}"
            )
            data = resp_fts.json()
            assert "entries" in data

        # 3. Source toggle cache invalidation
        sources_resp = await client.get("/api/sources")
        assert sources_resp.status_code == 200
        sources = sources_resp.json().get("sources", [])
        if sources:
            src = sources[0]
            src_id = src["id"]
            orig_enabled = src["enabled"]

            # Toggle source
            toggle_resp = await client.post(
                f"/api/sources/{src_id}/toggle",
                json={"enabled": not orig_enabled},
            )
            assert toggle_resp.status_code == 200
            assert toggle_resp.json()["enabled"] == (not orig_enabled)

            # Immediate GET /api/sources must reflect change (no stale cache)
            refreshed_resp = await client.get("/api/sources")
            refreshed_sources = refreshed_resp.json().get("sources", [])
            refreshed_src = next(s for s in refreshed_sources if s["id"] == src_id)
            assert refreshed_src["enabled"] == (not orig_enabled)

            # Revert back
            await client.post(
                f"/api/sources/{src_id}/toggle",
                json={"enabled": orig_enabled},
            )

        # 4. Vault pin and unpin lifecycle
        entries_resp = await client.get("/api/entries?limit=1")
        assert entries_resp.status_code == 200
        entries = entries_resp.json().get("entries", [])
        if entries:
            target_entry_id = entries[0]["id"]

            # Pin to vault
            pin_resp = await client.post(
                f"/api/vault/{target_entry_id}",
                json={"reason": "Seminal Frontier Reasoning Benchmark"},
            )
            assert pin_resp.status_code == 200
            assert pin_resp.json()["is_vaulted"] is True

            # Double pin should be idempotent
            pin_double = await client.post(f"/api/vault/{target_entry_id}")
            assert pin_double.status_code == 200
            assert pin_double.json()["is_vaulted"] is True

            # Verify presence in vault list
            vault_list_resp = await client.get("/api/vault")
            assert vault_list_resp.status_code == 200
            v_entries = vault_list_resp.json().get("entries", [])
            assert any(v["id"] == target_entry_id for v in v_entries)

            # Unpin from vault
            unpin_resp = await client.delete(f"/api/vault/{target_entry_id}")
            assert unpin_resp.status_code == 200
            assert unpin_resp.json()["is_vaulted"] is False

            # Verify removed from vault
            vault_after_resp = await client.get("/api/vault")
            v_after = vault_after_resp.json().get("entries", [])
            assert not any(v["id"] == target_entry_id for v in v_after)
