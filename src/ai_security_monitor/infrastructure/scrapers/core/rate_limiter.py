"""
Rate limiting, adaptive exponential backoff, and domain cooldown queues.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Manages polite delay pacing and exponential backoff with full jitter."""

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0) -> None:
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._domain_last_request: dict[str, float] = {}
        self._domain_cooldowns: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def compute_backoff(self, attempt: int) -> float:
        """Compute exponential backoff with full jitter: random(0, min(max_delay, base * 2^attempt))."""
        cap = min(self.max_delay, self.base_delay * (2**attempt))
        return random.uniform(0.5, cap)

    def extract_retry_delay(self, headers: Mapping[str, str]) -> float | None:
        """Parse Retry-After or x-rate-limit-reset headers to determine required wait seconds."""
        # 1. Standard Retry-After
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            try:
                # May be integer seconds
                return float(retry_after)
            except ValueError:
                # May be HTTP date format
                try:
                    dt = parsedate_to_datetime(retry_after)
                    now = datetime.now(UTC)
                    diff = (dt - now).total_seconds()
                    if diff > 0:
                        return min(diff, self.max_delay)
                except Exception:
                    pass

        # 2. Twitter / Reddit x-rate-limit-reset (Unix epoch timestamp)
        reset_header = headers.get("x-rate-limit-reset") or headers.get(
            "X-RateLimit-Reset"
        )
        if reset_header:
            try:
                reset_epoch = float(reset_header)
                diff = reset_epoch - time.time()
                if diff > 0:
                    return min(diff, self.max_delay)
            except ValueError:
                pass

        return None

    async def throttle_domain(self, domain: str, min_interval: float = 1.5) -> None:
        """Enforce minimal polite interval between sequential requests to the same domain."""
        async with self._lock:
            now = time.time()
            # Check domain cooldown
            cooldown_until = self._domain_cooldowns.get(domain, 0.0)
            if now < cooldown_until:
                wait_sec = cooldown_until - now
                logger.debug(f"Domain {domain} in cooldown; waiting {wait_sec:.2f}s")
                await asyncio.sleep(wait_sec)
                now = time.time()

            last_req = self._domain_last_request.get(domain, 0.0)
            elapsed = now - last_req
            if elapsed < min_interval:
                sleep_needed = min_interval - elapsed
                await asyncio.sleep(sleep_needed)

            self._domain_last_request[domain] = time.time()

    def set_domain_cooldown(self, domain: str, seconds: float) -> None:
        """Mark a domain as cooled down for a specific period."""
        self._domain_cooldowns[domain] = time.time() + seconds
        logger.warning(f"Set {seconds}s cooldown on domain {domain}")
