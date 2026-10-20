"""
Resilient HTTP/2 client with realistic TLS/header impersonation and retry logic.
"""

from __future__ import annotations

import asyncio
import urllib.parse
from typing import Any

import httpx

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.infrastructure.scrapers.core.rate_limiter import RateLimiter
from ai_security_monitor.infrastructure.scrapers.core.session_pool import (
    SessionPool,
    default_session_pool,
)

logger = get_logger(__name__)


class ResilientScraperClient:
    """Async HTTP/2 client equipped with automatic retries, header spoofing, and rate limiting."""

    def __init__(
        self,
        session_pool: SessionPool | None = None,
        rate_limiter: RateLimiter | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.session_pool = session_pool or default_session_pool
        self.rate_limiter = rate_limiter or RateLimiter()
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> ResilientScraperClient:
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
        try:
            import h2  # noqa: F401

            supports_http2 = True
        except ImportError:
            supports_http2 = False

        self._client = httpx.AsyncClient(
            http2=supports_http2,
            timeout=self.timeout,
            follow_redirects=True,
            limits=limits,
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def raw_client(self) -> httpx.AsyncClient:
        """Access underlying httpx AsyncClient."""
        if not self._client:
            raise RuntimeError(
                "Client not opened. Use 'async with ResilientScraperClient() as client:'"
            )
        return self._client

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> httpx.Response:
        """
        Execute HTTP request with automated rate-limiting, backoff, and retry handling.
        """
        client = self.raw_client
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc

        req_headers = dict(headers or {})
        req_cookies = dict(cookies or {})

        last_resp: httpx.Response | None = None
        for attempt in range(max_retries):
            await self.rate_limiter.throttle_domain(domain)
            try:
                resp = await client.request(
                    method=method,
                    url=url,
                    headers=req_headers,
                    cookies=req_cookies,
                    params=params,
                    json=json_body,
                )
                last_resp = resp

                if resp.status_code == 200:
                    return resp

                if resp.status_code in (429, 503):
                    retry_wait = self.rate_limiter.extract_retry_delay(resp.headers)
                    if not retry_wait:
                        retry_wait = self.rate_limiter.compute_backoff(attempt)
                    logger.warning(
                        f"Rate limit / error HTTP {resp.status_code} for {domain}. Backing off {retry_wait:.2f}s (attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(retry_wait)
                    continue

                if (
                    resp.status_code in (401, 403)
                    and "twitter.com" in domain
                    or "x.com" in domain
                ):
                    # Invalidate cached guest token and refresh credentials
                    self.session_pool.guest_token = None
                    (
                        new_headers,
                        new_cookies,
                        _,
                    ) = await self.session_pool.prepare_request(client)
                    req_headers.update(new_headers)
                    req_cookies.update(new_cookies)
                    logger.info(
                        "Refreshed Twitter credentials after 401/403, retrying..."
                    )
                    continue

                # Other HTTP errors: return response immediately
                return resp

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.NetworkError) as e:
                backoff = self.rate_limiter.compute_backoff(attempt)
                logger.warning(
                    f"Network error on {domain}: {e}. Retrying in {backoff:.2f}s..."
                )
                await asyncio.sleep(backoff)

        if last_resp is not None:
            return last_resp
        raise httpx.RequestError(
            f"Failed to fetch {url} after {max_retries} retries", request=None
        )  # type: ignore[arg-type]
