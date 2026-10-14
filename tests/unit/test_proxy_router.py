"""Unit tests for the SSRF-protected CORS Proxy router."""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_security_monitor.presentation.api.routers.proxy import proxy_router

app = FastAPI()
app.include_router(proxy_router, prefix="/api")
client = TestClient(app)


def test_proxy_blocks_private_ip_loopback():
    response = client.get("/api/proxy?url=http://127.0.0.1:8000/api/health")
    assert response.status_code == 400
    assert "blocked" in response.json()["detail"].lower()


def test_proxy_blocks_localhost():
    response = client.get("/api/proxy?url=http://localhost:3000/feed")
    assert response.status_code == 400
    assert "blocked" in response.json()["detail"].lower()


def test_proxy_blocks_internal_rfc1918_network():
    response = client.get("/api/proxy?url=http://192.168.1.1/admin")
    assert response.status_code == 400
    assert "blocked" in response.json()["detail"].lower()


def test_proxy_blocks_invalid_scheme():
    response = client.get("/api/proxy?url=file:///etc/passwd")
    assert response.status_code == 400
    assert "http and https" in response.json()["detail"].lower()


def test_proxy_blocks_internal_tld():
    response = client.get("/api/proxy?url=http://service.internal/feed.xml")
    assert response.status_code == 400
    assert "internal hosts" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_proxy_success_mock(monkeypatch):
    class MockResponse:
        status_code = 200
        content = b"<rss><channel><title>AI Breakthroughs</title></channel></rss>"
        headers = {"content-type": "application/xml; charset=utf-8"}

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, headers=None):
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    # Use a dummy public domain (e.g., example.com)
    # Monkeypatch DNS check to pass for example.com
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda h, p: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )

    response = client.get("/api/proxy?url=https://example.com/feed.xml")
    assert response.status_code == 200
    assert "<title>AI Breakthroughs</title>" in response.text
    assert "X-Proxy-Response-Size" in response.headers
