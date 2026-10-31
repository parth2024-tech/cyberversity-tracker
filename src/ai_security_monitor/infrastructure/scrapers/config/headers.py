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

# Rotating realistic browser profiles for anti-bot TLS & header fallback
ROTATING_BROWSER_PROFILES: list[dict[str, str]] = [
    # Profile 1: Chrome 131 on Windows 10/11
    {
        "user-agent": DEFAULT_CHROME_USER_AGENT,
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
    },
    # Profile 2: Chrome 130 on macOS
    {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": '"Google Chrome";v="130", "Chromium";v="130", "Not?A_Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
    },
    # Profile 3: Firefox 133 on Windows
    {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.5",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
    },
    # Profile 4: Safari 18 on macOS
    {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
    },
    # Profile 5: Microsoft Edge 131 on Windows
    {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": '"Microsoft Edge";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "upgrade-insecure-requests": "1",
    },
]


# Public alias for profile testing and inspection
BROWSER_PROFILES = ROTATING_BROWSER_PROFILES


def get_rotating_headers(domain: str = "", attempt: int = 0) -> dict[str, str]:
    """Retrieve rotating browser header profile with realistic user agent and security tokens."""
    profile_idx = attempt % len(ROTATING_BROWSER_PROFILES)
    headers = dict(ROTATING_BROWSER_PROFILES[profile_idx])

    if "reddit.com" in domain:
        headers["accept"] = (
            "application/json,text/html,application/xhtml+xml,text/plain,*/*"
        )
    elif "twitter.com" in domain or "x.com" in domain:
        headers.update(
            {
                "authorization": f"Bearer {TWITTER_BEARER_TOKEN}",
                "x-twitter-active-user": "yes",
                "x-twitter-client-language": "en",
            }
        )

    return headers
