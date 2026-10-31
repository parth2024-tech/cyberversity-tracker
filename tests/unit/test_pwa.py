"""
Unit tests for PWA Web Manifest and Offline Service Worker routes.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.presentation.api.main import create_app


@pytest.mark.asyncio
async def test_pwa_manifest_and_sw_routes():
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Test /manifest.json
        resp_manifest = await client.get("/manifest.json")
        assert resp_manifest.status_code == 200
        assert "application/manifest+json" in resp_manifest.headers.get(
            "content-type", ""
        )
        data = resp_manifest.json()
        assert data["name"] == "AETHERGUARD // Global AI Intelligence Radar"
        assert data["display"] == "standalone"

        # Test /sw.js
        resp_sw = await client.get("/sw.js")
        assert resp_sw.status_code == 200
        assert "application/javascript" in resp_sw.headers.get("content-type", "")
        assert resp_sw.headers.get("service-worker-allowed") == "/"
        assert "aetherguard-pwa-v1" in resp_sw.text
