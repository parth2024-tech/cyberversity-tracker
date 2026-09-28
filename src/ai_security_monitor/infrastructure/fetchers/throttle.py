"""
Adaptive per-domain throttle engine inspired by Scrapling's AutoThrottle.

Dynamically tunes fetch delays according to server latency, honors
`Retry-After` headers, and automatically doubles delays upon detection
of rate limits or anti-bot blocks.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)

BLOCK_BACKOFF_FACTOR = 2.0


def parse_retry_after(headers: Mapping[str, str] | None) -> float | None:
    """Parse `Retry-After` header value into seconds."""
    if not headers:
        return None

    # Case-insensitive header lookup
    val = next(
        (v for k, v in headers.items() if k.lower() == "retry-after"),
        None,
    )
    if not val:
        return None

    clean_val = val.strip()

    # Try numeric seconds
    try:
        return max(float(clean_val), 0.0)
    except ValueError:
        pass

    # Try HTTP date format
    try:
        dt = parsedate_to_datetime(clean_val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        diff = (dt - datetime.now(UTC)).total_seconds()
        return max(diff, 0.0)
    except Exception as e:
        logger.debug(f"Could not parse Retry-After header {clean_val!r}: {e}")
        return None


class DomainAutoThrottle:
    """Adaptive per-domain throttle that learns optimal crawl speeds from latency and response codes."""

    def __init__(
        self,
        start_delay: float = 1.0,
        max_delay: float = 60.0,
        min_delay: float = 0.2,
        target_concurrency: float = 1.0,
        block_backoff: bool = True,
    ):
        self.start_delay = start_delay
        self.max_delay = max_delay
        self.min_delay = min_delay
        self.target_concurrency = max(target_concurrency, 0.1)
        self.block_backoff = block_backoff

        self._delays: dict[str, float] = {}
        self._last_fetch_times: dict[str, datetime] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, domain: str) -> asyncio.Lock:
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        return self._locks[domain]

    @staticmethod
    def extract_domain(url: str | None) -> str:
        """Extract network domain name from URL."""
        if not url:
            return "default"
        try:
            parsed = urlparse(url)
            return (parsed.netloc or parsed.path).lower().split(":")[0] or "default"
        except Exception:
            return "default"

    def delay_for(self, domain: str, floor: float = 0.0) -> float:
        """Return the current computed delay for a given domain."""
        if domain not in self._delays:
            self._delays[domain] = min(
                max(floor, self.start_delay, self.min_delay), self.max_delay
            )
        return self._delays[domain]

    def record(
        self,
        domain: str,
        latency: float,
        ok: bool,
        floor: float = 0.0,
        retry_after: float | None = None,
    ) -> float:
        """
        Record the outcome of a finished request and adjust the domain delay.

        Uses Exponential Moving Average (EMA) to speed up on fast servers
        and doubles the delay or honors `Retry-After` on blocks.
        """
        current_delay = self.delay_for(domain, floor)
        target_delay = latency / self.target_concurrency
        new_delay = max((current_delay + target_delay) / 2.0, target_delay)

        if not ok:
            # Server blocked or rate limited us
            penalty = current_delay
            if self.block_backoff:
                penalty = (
                    retry_after
                    if retry_after is not None
                    else current_delay * BLOCK_BACKOFF_FACTOR
                )
            new_delay = max(new_delay, penalty, current_delay)

        # Enforce boundary bounds
        new_delay = min(max(new_delay, floor, self.min_delay), self.max_delay)
        self._delays[domain] = new_delay

        logger.debug(
            f"AutoThrottle ({domain}): latency={latency:.2f}s, ok={ok}, "
            f"delay {current_delay:.2f}s -> {new_delay:.2f}s"
        )
        return new_delay

    async def wait_for_domain(self, domain: str, floor: float = 0.0) -> float:
        """Asynchronously pause until the domain's computed throttle window has elapsed."""
        lock = self._get_lock(domain)
        async with lock:
            now = datetime.now(UTC)
            last_time = self._last_fetch_times.get(domain)
            computed_delay = self.delay_for(domain, floor)

            if last_time:
                elapsed = (now - last_time).total_seconds()
                if elapsed < computed_delay:
                    sleep_time = computed_delay - elapsed
                    logger.debug(
                        f"AutoThrottle waiting {sleep_time:.2f}s for domain {domain!r}"
                    )
                    await asyncio.sleep(sleep_time)

            self._last_fetch_times[domain] = datetime.now(UTC)
            return computed_delay

    def get_stats(self) -> dict[str, dict[str, float]]:
        """Return current throttle telemetry across all tracked domains."""
        return {
            domain: {
                "delay_seconds": round(delay, 2),
                "is_active": domain in self._last_fetch_times,
            }
            for domain, delay in self._delays.items()
        }

    def reset(self) -> None:
        """Clear all domain delays and history."""
        self._delays.clear()
        self._last_fetch_times.clear()


# Global singleton instance
domain_throttle = DomainAutoThrottle()
