"""
Production-grade SSRF-protected CORS proxy router for external AI feeds and articles.
Enables web clients and desktop readers to preview full articles without browser CORS blocks.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query, Response

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)

proxy_router = APIRouter(prefix="/proxy", tags=["Proxy"])

MAX_PROXY_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB max response size
REQUEST_TIMEOUT_SECONDS = 10.0

# Blocked IP networks for SSRF protection
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("10.0.0.0/8"),  # RFC1918 Private
    ipaddress.ip_network("172.16.0.0/12"),  # RFC1918 Private
    ipaddress.ip_network("192.168.0.0/16"),  # RFC1918 Private
    ipaddress.ip_network("169.254.0.0/16"),  # Link-Local
    ipaddress.ip_network("0.0.0.0/8"),  # Current network
    ipaddress.ip_network("::1/128"),  # IPv6 Loopback
    ipaddress.ip_network("fe80::/10"),  # IPv6 Link-Local
    ipaddress.ip_network("fc00::/7"),  # IPv6 Unique Local
]


def _validate_url_ssrf(url: str) -> None:
    """Validate that URL is http/https and does not resolve to private/internal IPs."""
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid URL structure: {e}")

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail="Only HTTP and HTTPS protocols are permitted through the proxy.",
        )

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise HTTPException(status_code=400, detail="Missing hostname in URL.")

    # Reject localhost & suspicious internal TLDs
    if hostname in ("localhost", "0.0.0.0") or hostname.endswith(
        (".local", ".internal", ".lan")
    ):
        raise HTTPException(
            status_code=400,
            detail="Access to internal hosts and domains is strictly blocked.",
        )

    # Check if hostname is an IP literal
    try:
        ip = ipaddress.ip_address(hostname)
        for net in _BLOCKED_NETWORKS:
            if ip in net:
                raise HTTPException(
                    status_code=400,
                    detail="Access to private or link-local IP addresses is strictly blocked.",
                )
    except ValueError:
        # Not an IP literal, resolve DNS to verify target IP
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for item in addr_info:
                sockaddr = item[4]
                ip_str = sockaddr[0]
                ip = ipaddress.ip_address(ip_str)
                for net in _BLOCKED_NETWORKS:
                    if ip in net:
                        raise HTTPException(
                            status_code=400,
                            detail="Target domain resolves to a blocked private IP address.",
                        )
        except socket.gaierror:
            # Cannot resolve domain
            raise HTTPException(status_code=400, detail="Domain could not be resolved.")


@proxy_router.get("")
@proxy_router.get("/")
async def proxy_feed_or_article(
    url: str = Query(..., description="Target feed or article URL to fetch"),
) -> Response:
    """Safely fetch and proxy external RSS feeds or article text, preventing CORS and SSRF issues."""
    _validate_url_ssrf(url)

    start_time = time.monotonic()
    headers = {
        "User-Agent": "AetherGuard-EcosystemRadar/2.0 (Mozilla/5.0 compatible; AI Intelligence Collector)",
        "Accept": "text/html,application/xhtml+xml,application/xml,text/xml,application/json;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        ) as client:
            response = await client.get(url, headers=headers)

            # Enforce max response size bounds
            content = response.content
            if len(content) > MAX_PROXY_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Response payload exceeds maximum allowed size ({MAX_PROXY_SIZE_BYTES // (1024 * 1024)} MB).",
                )

            duration_ms = int((time.monotonic() - start_time) * 1000)

            content_type = response.headers.get(
                "content-type", "application/xml; charset=utf-8"
            )
            response_headers = {
                "X-Proxy-Response-Size": str(len(content)),
                "X-Proxy-Duration-Ms": str(duration_ms),
                "Cache-Control": "public, max-age=300",
            }

            return Response(
                content=content,
                status_code=response.status_code,
                headers=response_headers,
                media_type=content_type,
            )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Upstream feed or article server timed out.",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch upstream content: {exc}",
        )
