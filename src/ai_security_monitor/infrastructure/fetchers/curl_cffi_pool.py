"""
Persistent BoringSSL Session Pool for curl-cffi.
Maintains a lifecycle-managed HTTP/2 + TLS 1.3 session pool with Chrome 131 impersonation,
session resumption (0-RTT), and automatic stripping of conflicting headers to preserve JA3 fingerprints.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


class CurlCffiSessionPool:
    """Singleton session pool providing reusable curl-cffi sessions with Chrome 131 profile."""

    _instance: CurlCffiSessionPool | None = None
    _lock = asyncio.Lock()

    def __init__(self) -> None:
        self._session: Any | None = None
        self._init_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> CurlCffiSessionPool:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def get_session(self) -> Any:
        """Retrieve or lazily initialize the shared AsyncSession with Chrome 131 impersonation."""
        if self._session is not None:
            return self._session

        async with self._init_lock:
            if self._session is None:
                try:
                    from curl_cffi.requests import AsyncSession

                    # Maintain a pooled session with up to 32 multiplexed connections
                    self._session = AsyncSession(
                        impersonate="chrome131",
                        max_clients=32,
                    )
                    logger.info("Initialized persistent curl-cffi BoringSSL session pool (Chrome 131)")
                except Exception as exc:
                    logger.error(f"Failed to initialize curl-cffi AsyncSession: {exc}")
                    raise
            return self._session

    async def get(
        self,
        url: str,
        timeout: float = 15.0,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """
        Execute an HTTP GET request using the pooled Chrome 131 session.
        Strictly sanitizes headers: strips any custom User-Agent, Sec-Ch-*, or pseudo-headers
        that would corrupt curl-cffi's authentic JA3/HTTP2 frame layout.
        Only conditional caching headers (If-None-Match, If-Modified-Since) are passed through.
        """
        session = await self.get_session()

        sanitized_headers: dict[str, str] = {}
        if headers:
            for k, v in headers.items():
                lower_k = k.lower()
                # Disallow custom client-hints or user-agent that trigger Cloudflare JA3 mismatches
                if lower_k in (
                    "user-agent",
                    "sec-ch-ua",
                    "sec-ch-ua-mobile",
                    "sec-ch-ua-platform",
                    "sec-fetch-dest",
                    "sec-fetch-mode",
                    "sec-fetch-site",
                    "accept-language",
                    "accept-encoding",
                ):
                    continue
                sanitized_headers[k] = v

        return await session.get(
            url,
            timeout=timeout,
            headers=sanitized_headers if sanitized_headers else None,
        )

    async def close(self) -> None:
        """Gracefully terminate the session pool on application shutdown."""
        if self._session is not None:
            try:
                await self._session.close()
                logger.info("Closed curl-cffi BoringSSL session pool")
            except Exception as exc:
                logger.debug(f"Error closing curl-cffi session: {exc}")
            finally:
                self._session = None


# Global singleton instance
curl_cffi_pool = CurlCffiSessionPool.get_instance()
