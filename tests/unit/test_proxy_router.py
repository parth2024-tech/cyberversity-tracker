"""Unit tests for the SSRF-protected CORS Proxy router."""

import socket

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


def test_proxy_blocks_cgnat_network():
    """Verify that Carrier-Grade NAT (100.64.0.0/10) is blocked."""
    response = client.get("/api/proxy?url=http://100.64.1.1/data")
    assert response.status_code == 400
    assert "blocked" in response.json()["detail"].lower()


def test_proxy_blocks_ipv4_mapped_ipv6():
    """Verify that IPv4-mapped IPv6 (::ffff:127.0.0.1) is blocked."""
    response = client.get("/api/proxy?url=http://[::ffff:127.0.0.1]:8080/metrics")
    assert response.status_code == 400
    assert "blocked" in response.json()["detail"].lower()


def test_proxy_blocks_zero_network():
    """Verify that 0.0.0.0/8 current network is blocked."""
    response = client.get("/api/proxy?url=http://0.0.0.1/status")
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


@pytest.mark.parametrize(
    ("obfuscated_url", "expected_fragment"),
    [
        ("http://2130706433/data", "blocked"),  # Decimal IP notation for 127.0.0.1
        ("http://0177.0.0.1/data", "blocked"),  # Octal IP notation for 127.0.0.1
        ("http://0x7f.0.0.1/data", "blocked"),  # Hex IP notation for 127.0.0.1
        ("http://[::1]/data", "blocked"),  # IPv6 loopback
        ("http://[::]/data", "blocked"),  # IPv6 unspecified
        (
            "http://169.254.169.254/latest/meta-data",
            "blocked",
        ),  # Link-Local Cloud Metadata
        ("http://172.16.0.1/data", "blocked"),  # RFC 1918 Class B
        ("http://10.0.0.1/data", "blocked"),  # RFC 1918 Class A
        ("http://metadata.google.internal/test", "internal hosts"),  # GCP metadata
        ("gopher://127.0.0.1:11211/", "http and https"),  # Gopher injection
        ("ftp://example.com/file", "http and https"),  # FTP scheme
        ("http:///path", "missing hostname"),  # Missing hostname
    ],
)
def test_proxy_blocks_adversarial_ssrf_and_schemes(
    obfuscated_url: str, expected_fragment: str
):
    """Brutally test adversarial IP encodings, cloud metadata endpoints, and dangerous schemes."""
    response = client.get(f"/api/proxy?url={obfuscated_url}")
    assert response.status_code == 400
    assert expected_fragment in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_ssrf_protected_backend_blocks_dns_rebinding(monkeypatch):
    """Verify SSRFProtectedBackend intercepts and terminates DNS rebinding at socket connection level."""
    import httpcore

    from ai_security_monitor.presentation.api.routers.proxy import SSRFProtectedBackend

    # Simulate DNS resolving to 127.0.0.1 at connection time (after passing initial domain check)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda h, p, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ],
    )

    backend = SSRFProtectedBackend()
    with pytest.raises(httpcore.ConnectError) as excinfo:
        await backend.connect_tcp("rebound.example.com", 80)
    assert "dns rebinding protection" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_proxy_success_mock(monkeypatch):
    class MockStreamResponse:
        status_code = 200
        headers = {"content-type": "application/xml; charset=utf-8"}

        async def aiter_bytes(self):
            yield b"<rss><channel><title>AI Breakthroughs</title></channel></rss>"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, headers=None):
            return MockStreamResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda h, p, **kw: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )

    response = client.get("/api/proxy?url=https://example.com/feed.xml")
    assert response.status_code == 200
    assert "<title>AI Breakthroughs</title>" in response.text
    assert "X-Proxy-Response-Size" in response.headers
    # Verify strict sandbox CSP prevents stored XSS
    assert "sandbox" in response.headers.get("Content-Security-Policy", "")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


@pytest.mark.asyncio
async def test_proxy_enforces_5mb_limit_during_stream(monkeypatch):
    class MockOversizedStreamResponse:
        status_code = 200
        headers = {"content-type": "text/html"}

        async def aiter_bytes(self):
            # Yield 6MB in chunks
            for _ in range(6):
                yield b"X" * (1024 * 1024)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, headers=None):
            return MockOversizedStreamResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda h, p, **kw: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )

    response = client.get("/api/proxy?url=https://example.com/large-article.html")
    assert response.status_code == 413
    assert "exceeds maximum allowed size" in response.json()["detail"].lower()
