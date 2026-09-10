"""
Unit tests for the in-process TTL response cache (response_cache.py).
Covers: get_or_set hit/miss, TTL expiry, invalidation, purge_expired, and
the periodic eviction counter.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from ai_security_monitor.infrastructure.cache import response_cache


# Helper: reset module-level cache state between every test
@pytest.fixture(autouse=True)
def reset_cache():
    response_cache.clear()
    response_cache._call_counter = 0
    yield
    response_cache.clear()
    response_cache._call_counter = 0


# ---------------------------------------------------------------------------
# get_or_set — basic
# ---------------------------------------------------------------------------

class TestGetOrSet:
    @pytest.mark.asyncio
    async def test_cache_miss_calls_factory(self):
        factory = AsyncMock(return_value=42)
        result = await response_cache.get_or_set("k", 60.0, factory)
        assert result == 42
        factory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_factory(self):
        factory = AsyncMock(return_value=99)
        await response_cache.get_or_set("k", 60.0, factory)
        factory.reset_mock()
        result = await response_cache.get_or_set("k", 60.0, factory)
        assert result == 99
        factory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_expired_entry_calls_factory_again(self):
        factory = AsyncMock(return_value="fresh")
        # Insert a stale entry manually
        response_cache._CACHE["stale_key"] = (response_cache._now() - 1.0, "old")

        result = await response_cache.get_or_set("stale_key", 60.0, factory)
        assert result == "fresh"
        factory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_different_keys_independent(self):
        f1 = AsyncMock(return_value="alpha")
        f2 = AsyncMock(return_value="beta")
        r1 = await response_cache.get_or_set("k1", 60.0, f1)
        r2 = await response_cache.get_or_set("k2", 60.0, f2)
        assert r1 == "alpha"
        assert r2 == "beta"


# ---------------------------------------------------------------------------
# invalidate / invalidate_prefix / clear
# ---------------------------------------------------------------------------

class TestInvalidation:
    @pytest.mark.asyncio
    async def test_invalidate_removes_key(self):
        await response_cache.get_or_set("to_remove", 60.0, AsyncMock(return_value=1))
        response_cache.invalidate("to_remove")
        assert "to_remove" not in response_cache._CACHE

    @pytest.mark.asyncio
    async def test_invalidate_prefix_removes_matching_keys(self):
        for i in range(3):
            response_cache._CACHE[f"feed:{i}"] = (response_cache._now() + 60, i)
        response_cache._CACHE["other:key"] = (response_cache._now() + 60, "x")

        response_cache.invalidate_prefix("feed:")
        assert all(k not in response_cache._CACHE for k in ("feed:0", "feed:1", "feed:2"))
        assert "other:key" in response_cache._CACHE

    def test_clear_empties_cache(self):
        response_cache._CACHE["k1"] = (9999.0, "v1")
        response_cache._CACHE["k2"] = (9999.0, "v2")
        response_cache.clear()
        assert len(response_cache._CACHE) == 0


# ---------------------------------------------------------------------------
# purge_expired
# ---------------------------------------------------------------------------

class TestPurgeExpired:
    def test_purge_removes_stale_keys(self):
        now = response_cache._now()
        response_cache._CACHE["stale"] = (now - 1.0, "old")
        response_cache._CACHE["fresh"] = (now + 60.0, "new")

        removed = response_cache.purge_expired()
        assert removed == 1
        assert "stale" not in response_cache._CACHE
        assert "fresh" in response_cache._CACHE

    def test_purge_returns_zero_on_empty_cache(self):
        assert response_cache.purge_expired() == 0

    def test_purge_no_false_positives(self):
        response_cache._CACHE["active"] = (response_cache._now() + 100.0, "ok")
        removed = response_cache.purge_expired()
        assert removed == 0
        assert "active" in response_cache._CACHE


# ---------------------------------------------------------------------------
# Periodic auto-eviction counter
# ---------------------------------------------------------------------------

class TestPeriodicEviction:
    @pytest.mark.asyncio
    async def test_purge_triggered_at_interval(self):
        # Insert a stale entry
        response_cache._CACHE["stale"] = (response_cache._now() - 1.0, "dead")

        # Drive counter to just below threshold so next call triggers purge
        response_cache._call_counter = response_cache._PURGE_INTERVAL - 1
        factory = AsyncMock(return_value=0)
        await response_cache.get_or_set("trigger", 60.0, factory)

        # Stale key should have been swept
        assert "stale" not in response_cache._CACHE
        # Counter resets to 0 after purge
        assert response_cache._call_counter == 0

    @pytest.mark.asyncio
    async def test_counter_increments_each_call(self):
        for i in range(5):
            await response_cache.get_or_set(f"k{i}", 60.0, AsyncMock(return_value=i))
        # Counter should be 5 (or 0 if interval was hit — but interval is 50)
        assert response_cache._call_counter == 5


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_returns_remaining_ttl(self):
        response_cache._CACHE["a"] = (response_cache._now() + 30.0, "val")
        s = response_cache.stats()
        assert "a" in s
        assert 0 < s["a"] <= 30.0

    def test_stats_expired_key_shows_zero_ttl(self):
        response_cache._CACHE["old"] = (response_cache._now() - 5.0, "val")
        s = response_cache.stats()
        assert s["old"] == 0.0
