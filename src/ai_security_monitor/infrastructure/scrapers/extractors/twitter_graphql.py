"""
Extractor for unwinding Twitter / X nested GraphQL timeline JSON trees.
Handles TimelineAddEntries, TweetWithVisibilityResults, longform note tweets, and engagement metrics.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.infrastructure.scrapers.models.tweet import (
    Tweet,
    TweetAuthor,
    TweetMetrics,
)

logger = get_logger(__name__)


class TwitterGraphQLExtractor:
    """Unwinds nested Twitter GraphQL timeline response structures into normalized Tweet models."""

    @classmethod
    def parse_twitter_date(cls, date_str: str) -> datetime:
        """Parse Twitter date format (e.g. 'Sat Oct 17 08:35:54 +0000 2026') or ISO-8601 to UTC."""
        if not date_str:
            return datetime.now(UTC)
        try:
            # Common Twitter RFC-822/RFC-2822 variation
            return parsedate_to_datetime(date_str).astimezone(UTC)
        except Exception:
            pass

        try:
            # Standard strptime fallback for "%a %b %d %H:%M:%S %z %Y"
            return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y").astimezone(
                UTC
            )
        except Exception:
            pass

        return datetime.now(UTC)

    @classmethod
    def extract_tweet_from_result(cls, tweet_result: dict[str, Any]) -> Tweet | None:
        """Extract a single normalized Tweet from a GraphQL tweet_results result dict."""
        if not tweet_result:
            return None

        # Handle TweetWithVisibilityResults wrapper
        result = tweet_result.get("tweet", tweet_result)
        # Check __typename
        typename = result.get("__typename", "")
        if typename == "TweetTombstone":
            return None

        legacy = result.get("legacy") or {}
        tweet_id = str(result.get("rest_id") or legacy.get("id_str") or "")
        if not tweet_id:
            return None

        # Extract text: prioritize full longform note_tweet text over 280-char truncated full_text
        note_tweet = (
            result.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
        )
        text = note_tweet.get("text") or legacy.get("full_text") or ""
        text = html.unescape(text).strip()

        # Extract author
        user_res = result.get("core", {}).get("user_results", {}).get("result", {})
        user_legacy = user_res.get("legacy", {})
        screen_name = user_legacy.get("screen_name") or user_res.get(
            "rest_id", "unknown"
        )
        author = TweetAuthor(
            id=str(user_res.get("rest_id", "")),
            name=user_legacy.get("name", screen_name),
            screen_name=screen_name,
            verified=bool(
                user_res.get("is_blue_verified") or user_legacy.get("verified")
            ),
            profile_image_url=user_legacy.get("profile_image_url_https", ""),
        )

        # Extract metrics
        views_dict = result.get("views", {})
        view_count_raw = views_dict.get("count")
        view_count = (
            int(view_count_raw)
            if view_count_raw and str(view_count_raw).isdigit()
            else None
        )

        metrics = TweetMetrics(
            retweet_count=int(legacy.get("retweet_count", 0)),
            reply_count=int(legacy.get("reply_count", 0)),
            favorite_count=int(legacy.get("favorite_count", 0)),
            quote_count=int(legacy.get("quote_count", 0)),
            view_count=view_count,
        )

        # Extract URLs and hashtags
        entities = legacy.get("entities", {})
        urls: list[str] = []
        for u in entities.get("urls", []):
            expanded = u.get("expanded_url") or u.get("url")
            if expanded:
                urls.append(expanded)

        hashtags: list[str] = [
            h.get("text") for h in entities.get("hashtags", []) if h.get("text")
        ]

        # Dates
        created_at = cls.parse_twitter_date(legacy.get("created_at", ""))

        url = (
            f"https://x.com/{author.screen_name}/status/{tweet_id}"
            if author.screen_name
            else f"https://x.com/i/web/status/{tweet_id}"
        )

        return Tweet(
            id=tweet_id,
            text=text,
            created_at=created_at,
            author=author,
            metrics=metrics,
            url=url,
            hashtags=hashtags,
            urls=urls,
            is_retweet=bool(legacy.get("retweeted_status_result")),
            is_quote=bool(result.get("quoted_status_result")),
            language=legacy.get("lang", "en"),
            raw_data=result,
        )

    @classmethod
    def extract_tweets_from_timeline(cls, payload: dict[str, Any]) -> list[Tweet]:
        """
        Recursively traverse GraphQL response to extract all tweets from SearchTimeline or UserTweets.
        """
        tweets: list[Tweet] = []
        seen_ids: set[str] = set()

        def _traverse(node: Any) -> None:
            if isinstance(node, dict):
                # Check for direct itemContent.tweet_results.result
                if "tweet_results" in node and isinstance(node["tweet_results"], dict):
                    t_result = node["tweet_results"].get("result")
                    if t_result:
                        tweet = cls.extract_tweet_from_result(t_result)
                        if tweet and tweet.id not in seen_ids:
                            seen_ids.add(tweet.id)
                            tweets.append(tweet)

                # Check for item.itemContent
                for v in node.values():
                    _traverse(v)
            elif isinstance(node, list):
                for item in node:
                    _traverse(item)

        _traverse(payload)
        return tweets
