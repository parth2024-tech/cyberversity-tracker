"""Unit tests for the resilient scrapers architecture."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_security_monitor.infrastructure.scrapers.core.rate_limiter import RateLimiter
from ai_security_monitor.infrastructure.scrapers.core.session_pool import (
    SessionPool,
    TwitterAccount,
)
from ai_security_monitor.infrastructure.scrapers.extractors.reddit_endpoints import (
    RedditEndpointsExtractor,
)
from ai_security_monitor.infrastructure.scrapers.extractors.twitter_graphql import (
    TwitterGraphQLExtractor,
)


def test_session_pool_rotation():
    """SessionPool should rotate available accounts in round-robin and exclude rate-limited accounts."""
    acc1 = TwitterAccount(auth_token="token_1", ct0="ct0_1", username="user1")
    acc2 = TwitterAccount(auth_token="token_2", ct0="ct0_2", username="user2")
    pool = SessionPool(accounts=[acc1, acc2])

    assert pool.has_authenticated_accounts is True
    # Round-robin selection
    assert pool.get_account().username == "user1"
    assert pool.get_account().username == "user2"
    assert pool.get_account().username == "user1"

    # Rate-limit acc1
    acc1.mark_rate_limited(cooldown_seconds=300)
    assert acc1.is_available is False
    assert pool.get_account().username == "user2"
    assert pool.get_account().username == "user2"


@pytest.mark.asyncio
async def test_session_pool_guest_token_activation():
    """SessionPool should activate guest token when no authenticated accounts exist."""
    pool = SessionPool(accounts=[])
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"guest_token": "1234567890"}
    mock_client.post.return_value = mock_resp

    headers, cookies, is_auth = await pool.prepare_request(mock_client)
    assert is_auth is False
    assert headers["x-guest-token"] == "1234567890"


def test_rate_limiter_backoff_and_header_parsing():
    """RateLimiter should correctly parse Retry-After and x-rate-limit-reset headers."""
    limiter = RateLimiter(base_delay=1.0, max_delay=30.0)

    # 1. Backoff bounds
    delay = limiter.compute_backoff(attempt=2)
    assert 0.5 <= delay <= 4.0

    # 2. Integer Retry-After
    headers = {"Retry-After": "15"}
    assert limiter.extract_retry_delay(headers) == 15.0

    # 3. x-rate-limit-reset (Unix epoch timestamp)
    future_reset = time.time() + 25.0
    headers_reset = {"x-rate-limit-reset": str(future_reset)}
    delay_reset = limiter.extract_retry_delay(headers_reset)
    assert delay_reset is not None and 20.0 <= delay_reset <= 26.0


def test_twitter_graphql_extractor():
    """TwitterGraphQLExtractor should unwind nested GraphQL timeline JSON trees."""
    sample_graphql_payload = {
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {
                        "instructions": [
                            {
                                "type": "TimelineAddEntries",
                                "entries": [
                                    {
                                        "entryId": "tweet-184567890",
                                        "content": {
                                            "entryType": "TimelineTimelineItem",
                                            "itemContent": {
                                                "itemType": "TimelineTweet",
                                                "tweet_results": {
                                                    "result": {
                                                        "__typename": "Tweet",
                                                        "rest_id": "184567890",
                                                        "core": {
                                                            "user_results": {
                                                                "result": {
                                                                    "rest_id": "999",
                                                                    "is_blue_verified": True,
                                                                    "legacy": {
                                                                        "name": "DeepSeek AI",
                                                                        "screen_name": "deepseek_ai",
                                                                    },
                                                                }
                                                            }
                                                        },
                                                        "legacy": {
                                                            "full_text": "DeepSeek-V4.1 weights open now!",
                                                            "created_at": "Sat Oct 17 08:35:54 +0000 2026",
                                                            "favorite_count": 5200,
                                                            "retweet_count": 1400,
                                                            "reply_count": 320,
                                                            "entities": {
                                                                "urls": [
                                                                    {
                                                                        "expanded_url": "https://github.com/deepseek-ai/DeepSeek-V4",
                                                                        "url": "https://t.co/abc",
                                                                    }
                                                                ],
                                                                "hashtags": [
                                                                    {"text": "AI"}
                                                                ],
                                                            },
                                                        },
                                                    }
                                                },
                                            },
                                        },
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        }
    }

    tweets = TwitterGraphQLExtractor.extract_tweets_from_timeline(
        sample_graphql_payload
    )
    assert len(tweets) == 1
    t = tweets[0]
    assert t.id == "184567890"
    assert t.author.screen_name == "deepseek_ai"
    assert t.author.handle == "@deepseek_ai"
    assert "DeepSeek-V4.1" in t.text
    assert t.metrics.favorite_count == 5200
    assert "https://github.com/deepseek-ai/DeepSeek-V4" in t.urls
    assert "AI" in t.hashtags


def test_reddit_endpoints_extractor():
    """RedditEndpointsExtractor should extract normalized posts and top comment trees."""
    sample_listing = {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "post_100",
                        "title": "vLLM 0.6.0 benchmarks released",
                        "subreddit": "LocalLLaMA",
                        "author": "vllm_dev",
                        "score": 850,
                        "num_comments": 45,
                        "url": "https://github.com/vllm-project/vllm",
                        "permalink": "/r/LocalLLaMA/comments/post_100/vllm_benchmarks/",
                        "selftext": "Benchmark results on RTX 4090 and H100.",
                        "created_utc": 1792300000.0,
                        "stickied": False,
                    }
                }
            ]
        }
    }

    posts = RedditEndpointsExtractor.extract_posts_from_listing(sample_listing)
    assert len(posts) == 1
    p = posts[0]
    assert p.id == "post_100"
    assert p.title == "vLLM 0.6.0 benchmarks released"
    assert p.subreddit == "LocalLLaMA"
    assert p.score == 850
    assert (
        p.full_permalink
        == "https://www.reddit.com/r/LocalLLaMA/comments/post_100/vllm_benchmarks/"
    )

    sample_comments = [
        {},
        {
            "data": {
                "children": [
                    {
                        "data": {
                            "id": "comm_1",
                            "author": "perf_engineer",
                            "body": "Throughput is 2x faster with chunked prefill.",
                            "score": 120,
                        }
                    }
                ]
            }
        },
    ]

    comments = RedditEndpointsExtractor.extract_comments_from_thread(sample_comments)
    assert len(comments) == 1
    c = comments[0]
    assert c.id == "comm_1"
    assert c.author == "perf_engineer"
    assert "2x faster" in c.body


def test_rotating_headers_profiles():
    """Verify modern desktop browser profiles and cycle on retry attempts."""
    from ai_security_monitor.infrastructure.scrapers.config.headers import (
        BROWSER_PROFILES,
        get_rotating_headers,
    )

    h0 = get_rotating_headers("huggingface.co", attempt=0)
    h1 = get_rotating_headers("huggingface.co", attempt=1)

    assert "user-agent" in h0
    assert "user-agent" in h1
    assert h0["user-agent"] != h1["user-agent"]
    assert len(BROWSER_PROFILES) >= 5
    assert "sec-ch-ua" in h0 or "sec-fetch-dest" in h0


def test_is_anti_bot_challenge():
    """Verify detection of anti-bot challenge signatures and HTTP error codes."""
    import httpx

    from ai_security_monitor.infrastructure.scrapers.core.client import (
        is_anti_bot_challenge,
    )

    r403 = httpx.Response(403, request=httpx.Request("GET", "https://example.com"))
    assert is_anti_bot_challenge(r403) is True

    r429 = httpx.Response(429, request=httpx.Request("GET", "https://example.com"))
    assert is_anti_bot_challenge(r429) is True

    r503_cf = httpx.Response(
        503,
        text="<title>Just a moment...</title>Attention Required! | Cloudflare",
        request=httpx.Request("GET", "https://example.com"),
    )
    assert is_anti_bot_challenge(r503_cf) is True

    r200 = httpx.Response(
        200,
        text="<html><body>Valid AI Research Paper</body></html>",
        request=httpx.Request("GET", "https://example.com"),
    )
    assert is_anti_bot_challenge(r200) is False


@pytest.mark.asyncio
async def test_curl_cffi_impersonation_fallback():
    """Verify curl_cffi Chrome TLS impersonation when present and clean fallback when absent."""
    import sys
    from unittest.mock import patch

    from ai_security_monitor.infrastructure.scrapers.core.client import (
        ResilientScraperClient,
    )

    client = ResilientScraperClient()

    # 1. When curl_cffi is missing or raises ImportError
    with patch.dict(sys.modules, {"curl_cffi": None, "curl_cffi.requests": None}):
        resp = await client._try_curl_cffi("GET", "https://example.com")
        assert resp is None

    # 2. When curl_cffi is mocked to succeed
    mock_session_cls = MagicMock()
    mock_session_inst = AsyncMock()
    mock_curl_resp = MagicMock()
    mock_curl_resp.status_code = 200
    mock_curl_resp.content = b"<html>Success from curl_cffi Chrome impersonation</html>"
    mock_curl_resp.headers = {"content-type": "text/html"}
    mock_session_inst.request.return_value = mock_curl_resp
    mock_session_cls.return_value.__aenter__.return_value = mock_session_inst

    with patch.dict(
        "sys.modules",
        {
            "curl_cffi": MagicMock(),
            "curl_cffi.requests": MagicMock(AsyncSession=mock_session_cls),
        },
    ):
        resp = await client._try_curl_cffi("GET", "https://example.com")
        assert resp is not None
        assert resp.status_code == 200
        assert b"Success from curl_cffi" in resp.content
