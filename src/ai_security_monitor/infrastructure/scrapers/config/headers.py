"""
Static web bearer tokens, client headers, and browser impersonation configurations.
"""

from __future__ import annotations

# Universal static public web client bearer token embedded in Twitter's main JavaScript bundles
TWITTER_BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

DEFAULT_CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

TWITTER_GRAPHQL_HEADERS: dict[str, str] = {
    "authorization": f"Bearer {TWITTER_BEARER_TOKEN}",
    "x-twitter-active-user": "yes",
    "x-twitter-client-language": "en",
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": DEFAULT_CHROME_USER_AGENT,
}

REDDIT_CLIENT_HEADERS: dict[str, str] = {
    "accept": "application/json,application/xml,text/xml,text/plain,*/*",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": DEFAULT_CHROME_USER_AGENT,
}
