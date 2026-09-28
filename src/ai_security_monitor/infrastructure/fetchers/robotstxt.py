"""
Robots.txt parser and compliance manager inspired by Scrapling's RobotsTxtManager.

Maintains an asynchronous, per-domain in-memory cache of parsed `robots.txt`
directives (`Disallow`, `Crawl-delay`, `Request-rate`) to ensure ethical,
polite crawling across worldwide AI intelligence sources.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


class RobotsTxtManager:
    """Manages fetching, parsing, and caching of robots.txt files per domain."""

    def __init__(self, timeout: float = 6.0):
        self.timeout = timeout
        self._parsers: dict[str, RobotFileParser] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, domain: str) -> asyncio.Lock:
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        return self._locks[domain]

    @staticmethod
    def extract_domain(url: str | None) -> str:
        """Extract domain netloc from URL."""
        if not url:
            return "default"
        try:
            parsed = urlparse(url)
            return (parsed.netloc or parsed.path).lower().split(":")[0] or "default"
        except Exception:
            return "default"

    async def get_parser(self, url: str) -> RobotFileParser:
        """Fetch and return the RobotFileParser for a domain, using cache if available."""
        parsed = urlparse(url)
        domain = self.extract_domain(url)

        if domain in self._parsers:
            return self._parsers[domain]

        lock = self._get_lock(domain)
        async with lock:
            # Double-check inside lock
            if domain in self._parsers:
                return self._parsers[domain]

            scheme = parsed.scheme or "https"
            robots_url = f"{scheme}://{domain}/robots.txt"
            content = ""

            try:
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (X-UA-Compatible; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
                    )
                }
                async with httpx.AsyncClient(
                    timeout=self.timeout, follow_redirects=True, headers=headers
                ) as client:
                    resp = await client.get(robots_url)
                    if resp.status_code == 200:
                        content = resp.text
                    elif resp.status_code in (404, 410):
                        # Missing robots.txt means everything is allowed
                        content = ""
                    else:
                        logger.debug(
                            f"robots.txt for {domain} returned HTTP {resp.status_code}"
                        )
            except Exception as e:
                logger.debug(f"Failed to fetch robots.txt for {domain}: {e}")
                content = ""

            parser = RobotFileParser()
            parser.parse(content.splitlines())
            self._parsers[domain] = parser
            return parser

    async def can_fetch(self, url: str, user_agent: str = "*") -> bool:
        """Check if an individual URL is permitted to be fetched by robots.txt."""
        if not url:
            return True
        try:
            parser = await self.get_parser(url)
            return parser.can_fetch(user_agent, url)
        except Exception as e:
            logger.debug(f"Error checking robots.txt for {url}: {e}")
            return True

    async def get_crawl_delay(self, url: str, user_agent: str = "*") -> float | None:
        """Retrieve crawl-delay directive in seconds, or None if not specified."""
        try:
            parser = await self.get_parser(url)
            delay = parser.crawl_delay(user_agent)
            return float(delay) if delay is not None else None
        except Exception:
            return None

    async def prefetch(self, urls: list[str]) -> None:
        """Pre-warm robots.txt cache across multiple domains concurrently."""
        unique_domains = {self.extract_domain(u) for u in urls if u}
        tasks = [
            self.get_parser(f"https://{domain}")
            for domain in unique_domains
            if domain != "default"
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def clear(self) -> None:
        """Clear parser cache."""
        self._parsers.clear()


# Global singleton instance
robots_manager = RobotsTxtManager()
