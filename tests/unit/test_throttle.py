"""Unit tests for DomainAutoThrottle and Retry-After parser."""

import pytest

from ai_security_monitor.infrastructure.fetchers.throttle import (
    DomainAutoThrottle,
    parse_retry_after,
)


def test_parse_retry_after():
    # Numeric
    assert parse_retry_after({"Retry-After": "120"}) == 120.0
    assert parse_retry_after({"retry-after": " 45 "}) == 45.0
    # None on missing or empty
    assert parse_retry_after({}) is None
    assert parse_retry_after(None) is None
    # Invalid string
    assert parse_retry_after({"Retry-After": "not-a-number"}) is None


def test_extract_domain():
    assert (
        DomainAutoThrottle.extract_domain("https://arxiv.org/rss/cs.AI") == "arxiv.org"
    )
    assert (
        DomainAutoThrottle.extract_domain("http://github.com:443/trending")
        == "github.com"
    )
    assert DomainAutoThrottle.extract_domain("") == "default"
    assert DomainAutoThrottle.extract_domain(None) == "default"


def test_throttle_record_speedup_and_backoff():
    throttle = DomainAutoThrottle(start_delay=5.0, min_delay=0.5, max_delay=30.0)

    # Initial delay starts at 5.0
    assert throttle.delay_for("test.com") == 5.0

    # Fast successful request with 1.0s latency -> should speed up
    new_delay = throttle.record("test.com", latency=1.0, ok=True)
    # EMA: (5.0 + 1.0) / 2 = 3.0
    assert new_delay == 3.0
    assert throttle.delay_for("test.com") == 3.0

    # Another fast request with 1.0s latency -> (3.0 + 1.0) / 2 = 2.0
    new_delay = throttle.record("test.com", latency=1.0, ok=True)
    assert new_delay == 2.0

    # Blocked request (ok=False) -> doubles delay
    new_delay = throttle.record("test.com", latency=0.5, ok=False)
    assert new_delay == 4.0  # 2.0 * 2.0

    # Blocked request with explicit retry_after header of 15.0s
    new_delay = throttle.record("test.com", latency=0.5, ok=False, retry_after=15.0)
    assert new_delay == 15.0


def test_throttle_bounds():
    throttle = DomainAutoThrottle(start_delay=5.0, min_delay=1.0, max_delay=10.0)

    # Fast request should not drop below min_delay
    delay = throttle.record("bound.com", latency=0.01, ok=True)
    for _ in range(10):
        delay = throttle.record("bound.com", latency=0.01, ok=True)
    assert delay == 1.0

    # Penalties should not exceed max_delay
    delay = throttle.record("bound.com", latency=20.0, ok=False, retry_after=500.0)
    assert delay == 10.0


@pytest.mark.asyncio
async def test_throttle_wait():
    throttle = DomainAutoThrottle(start_delay=0.05, min_delay=0.01, max_delay=1.0)
    waited = await throttle.wait_for_domain("async.com")
    assert waited == 0.05
    stats = throttle.get_stats()
    assert "async.com" in stats
    assert stats["async.com"]["delay_seconds"] == 0.05
