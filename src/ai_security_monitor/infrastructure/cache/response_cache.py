"""
Lightweight in-process TTL response cache.

Prevents redundant DB round-trips for data that rarely changes:
  - Sources map  (TTL: 60s)
  - Watchlist rules (TTL: 30s)
  - Stats totals  (TTL: 30s)

Thread-safe for asyncio usage (single-threaded event loop).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Awaitable

_CACHE: dict[str, tuple[float, Any]] = {}


def _now() -> float:
    return time.monotonic()


async def get_or_set(
    key: str,
    ttl_seconds: float,
    factory: Callable[[], Awaitable[Any]],
) -> Any:
    """
    Return cached value if fresh, otherwise call factory coroutine,
    store the result, and return it.
    """
    entry = _CACHE.get(key)
    if entry is not None:
        expires_at, value = entry
        if _now() < expires_at:
            return value

    value = await factory()
    _CACHE[key] = (_now() + ttl_seconds, value)
    return value


def invalidate(key: str) -> None:
    """Manually invalidate a cache key (e.g. after a write operation)."""
    _CACHE.pop(key, None)


def invalidate_prefix(prefix: str) -> None:
    """Invalidate all keys starting with prefix."""
    to_remove = [k for k in _CACHE if k.startswith(prefix)]
    for k in to_remove:
        del _CACHE[k]


def clear() -> None:
    """Clear all cached entries."""
    _CACHE.clear()


def stats() -> dict[str, float]:
    """Return remaining TTLs for all cached keys (for debugging)."""
    now = _now()
    return {k: max(0.0, expires_at - now) for k, (expires_at, _) in _CACHE.items()}
