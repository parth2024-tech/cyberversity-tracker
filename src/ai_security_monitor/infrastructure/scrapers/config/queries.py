"""
Extracted GraphQL query IDs, feature flags, and payload builders for Twitter web client.
"""

from __future__ import annotations

from typing import Any

# Reverse-engineered Twitter GraphQL Query IDs mapped to operation names
TWITTER_GRAPHQL_QUERY_IDS: dict[str, str] = {
    "SearchTimeline": "nK1dw4oV3k4w5TdtcAdSww",
    "UserTweets": "E3opETHurjfQ1phUB3qdHQ",
    "UserByScreenName": "sMQaAfcVU4e03iO3egpCMA",
    "TweetDetail": "VWFGPVAGkZMGRKGe3GFFnA",
}

# Standard feature flags required by Twitter's GraphQL execution engine
TWITTER_FEATURES: dict[str, bool] = {
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}


def build_search_variables(
    raw_query: str, count: int = 20, cursor: str | None = None
) -> dict[str, Any]:
    """Build variables dictionary for SearchTimeline GraphQL query."""
    variables: dict[str, Any] = {
        "rawQuery": raw_query,
        "count": count,
        "querySource": "typed_query",
        "product": "Latest",
    }
    if cursor:
        variables["cursor"] = cursor
    return variables


def build_user_tweets_variables(
    user_id: str, count: int = 20, cursor: str | None = None
) -> dict[str, Any]:
    """Build variables dictionary for UserTweets GraphQL query."""
    variables: dict[str, Any] = {
        "userId": user_id,
        "count": count,
        "includePromotedContent": False,
        "withQuickPromoteEligibilityTweetFields": True,
        "withVoice": True,
        "withV2Timeline": True,
    }
    if cursor:
        variables["cursor"] = cursor
    return variables
