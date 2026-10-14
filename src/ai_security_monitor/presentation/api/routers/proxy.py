"""
Production-grade SSRF-protected CORS proxy router for external AI feeds and articles.
Enforces DNS pinning, manual redirect hop validation, carrier-grade NAT & IPv4-mapped IPv6 filtering,
stream-level early 5MB cutoff, and strict sandbox isolation headers to eliminate stored-XSS risks.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin, urlparse

import httpcore
import httpx
from fastapi import APIRouter, HTTPException, Query, Response
from httpcore._backends.auto import AutoBackend

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)

proxy_router = APIRouter(prefix="/proxy", tags=["Proxy"])

MAX_PROXY_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB max response size
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 5

# Blocked IP networks for comprehensive SSRF defense
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),  # Broadcast / current network
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918 Private
    ipaddress.ip_network("100.64.0.0/10"),  # RFC 6598 Carrier-Grade NAT (CGNAT)
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("169.254.0.0/16"),  # Link-Local (Cloud metadata)
    ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918 Private
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918 Private
    ipaddress.ip_network("198.18.0.0/15"),  # Network benchmark tests
    ipaddress.ip_network("224.0.0.0/4"),  # Multicast
    ipaddress.ip_network("240.0.0.0/4"),  # Reserved
    ipaddress.ip_network("::/128"),  # Unspecified
    ipaddress.ip_network("::1/128"),  # IPv6 Loopback
    ipaddress.ip_network("fe80::/10"),  # IPv6 Link-Local
    ipaddress.ip_network("fc00::/7"),  # IPv6 Unique Local
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6 prefix
]


def _is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address belongs to any blocked / internal / private ranges."""
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            return True

    # If it is an IPv4-mapped IPv6 address (e.g. ::ffff:127.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        mapped_v4 = ip.ipv4_mapped
        for net in _BLOCKED_NETWORKS:
            if net.version == 4 and mapped_v4 in net:
                return True

    return False


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
        (".local", ".internal", ".lan", ".corp", ".home")
    ):
        raise HTTPException(
            status_code=400,
            detail="Access to internal hosts and domains is strictly blocked.",
        )

    # Check if hostname is an IP literal
    try:
        ip = ipaddress.ip_address(hostname)
        if _is_ip_blocked(ip):
            raise HTTPException(
                status_code=400,
                detail="Access to private, link-local, or CGNAT IP addresses is strictly blocked.",
            )
        return
    except ValueError:
        pass

    # Resolve DNS to verify target IP addresses
    try:
        addr_info = socket.getaddrinfo(hostname, None)
        if not addr_info:
            raise HTTPException(status_code=400, detail="Domain could not be resolved.")
        for item in addr_info:
            sockaddr = item[4]
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if _is_ip_blocked(ip):
                raise HTTPException(
                    status_code=400,
                    detail="Target domain resolves to a blocked private or reserved IP address.",
                )
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="Domain could not be resolved.")


class SSRFProtectedBackend(AutoBackend):
    """
    Custom network backend for httpcore that pins the resolved IP address
    and prevents DNS rebinding attacks at the socket connection level.
    """

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            addr_info = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise httpcore.ConnectError(
                f"DNS resolution failed for {host}: {exc}"
            ) from exc

        if not addr_info:
            raise httpcore.ConnectError(f"No address returned for {host}")

        # Re-check every resolved IP to guarantee none rebinds to internal networks
        for item in addr_info:
            sockaddr = item[4]
            ip = ipaddress.ip_address(sockaddr[0])
            if _is_ip_blocked(ip):
                raise httpcore.ConnectError(
                    f"Connection to blocked internal IP address {ip} is denied (DNS rebinding protection)."
                )

        # Pin to the first validated IP address
        pinned_ip = str(addr_info[0][4][0])
        return await super().connect_tcp(
            pinned_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class SSRFProtectedTransport(httpx.AsyncHTTPTransport):
    """Transport that enforces SSRFProtectedBackend on connection pools."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if hasattr(self, "_pool"):
            self._pool._network_backend = SSRFProtectedBackend()


@proxy_router.get("")
@proxy_router.get("/")
async def proxy_feed_or_article(
    url: str = Query(..., description="Target feed or article URL to fetch"),
) -> Response:
    """Safely fetch and proxy external RSS feeds or article text, preventing CORS and SSRF issues."""
    current_url = url
    start_time = time.monotonic()
    headers = {
        "User-Agent": "AetherGuard-EcosystemRadar/2.0 (Mozilla/5.0 compatible; AI Intelligence Collector)",
        "Accept": "text/html,application/xhtml+xml,application/xml,text/xml,application/json;q=0.9,*/*;q=0.8",
    }

    transport = SSRFProtectedTransport(
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    )

    try:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            redirect_count = 0
            while True:
                _validate_url_ssrf(current_url)

                async with client.stream(
                    "GET", current_url, headers=headers
                ) as stream_resp:
                    # Validate redirects manually per hop to prevent DNS rebinding or internal redirect hops
                    if stream_resp.status_code in (301, 302, 303, 307, 308):
                        redirect_count += 1
                        if redirect_count > MAX_REDIRECTS:
                            raise HTTPException(
                                status_code=400,
                                detail="Too many redirects encountered in proxy request.",
                            )

                        location = stream_resp.headers.get("location")
                        if not location:
                            raise HTTPException(
                                status_code=502,
                                detail="Redirect response missing Location header.",
                            )

                        current_url = urljoin(current_url, location)
                        continue

                    # Stream accumulation with early 5MB cutoff
                    chunks: list[bytes] = []
                    total_bytes = 0
                    async for chunk in stream_resp.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > MAX_PROXY_SIZE_BYTES:
                            raise HTTPException(
                                status_code=413,
                                detail=f"Response payload exceeds maximum allowed size ({MAX_PROXY_SIZE_BYTES // (1024 * 1024)} MB).",
                            )
                        chunks.append(chunk)

                    content = b"".join(chunks)
                    duration_ms = int((time.monotonic() - start_time) * 1000)

                    content_type = stream_resp.headers.get(
                        "content-type", "application/xml; charset=utf-8"
                    )
                    response_headers = {
                        "X-Proxy-Response-Size": str(len(content)),
                        "X-Proxy-Duration-Ms": str(duration_ms),
                        "Cache-Control": "public, max-age=300",
                        # Strict CSP sandbox: disables scripts and isolates from parent origin (prevents stored XSS)
                        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data: https: http:; sandbox",
                        "X-Content-Type-Options": "nosniff",
                        "Referrer-Policy": "no-referrer",
                        "Cross-Origin-Resource-Policy": "cross-origin",
                    }

                    return Response(
                        content=content,
                        status_code=stream_resp.status_code,
                        headers=response_headers,
                        media_type=content_type,
                    )

    except HTTPException:
        raise
    except httpcore.ConnectError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Connection blocked or failed: {exc}",
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
