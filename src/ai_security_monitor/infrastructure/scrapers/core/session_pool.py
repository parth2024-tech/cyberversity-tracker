"""
Session manager and authentication pool for Twitter / X and social scrapers.
Manages auth_token, ct0 cookies, guest tokens, and account rotation.
"""

from __future__ import annotations

import os
import time

import httpx

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.infrastructure.scrapers.config.headers import (
    TWITTER_BEARER_TOKEN,
    TWITTER_GRAPHQL_HEADERS,
)

logger = get_logger(__name__)


class TwitterAccount:
    """Represents an authentic Twitter user session."""

    def __init__(self, auth_token: str, ct0: str, username: str = "anon") -> None:
        self.auth_token = auth_token.strip()
        self.ct0 = ct0.strip()
        self.username = username
        self.is_active = True
        self.rate_limited_until = 0.0

    @property
    def is_available(self) -> bool:
        """Check if account is active and not currently rate-limited."""
        return self.is_active and time.time() > self.rate_limited_until

    def mark_rate_limited(self, cooldown_seconds: float = 900.0) -> None:
        """Place account into temporary cooldown."""
        self.rate_limited_until = time.time() + cooldown_seconds
        logger.warning(
            f"Twitter account @{self.username} rate-limited for {cooldown_seconds}s"
        )


class SessionPool:
    """Manages pool of accounts, guest tokens, and request credential injection."""

    def __init__(self, accounts: list[TwitterAccount] | None = None) -> None:
        self.accounts: list[TwitterAccount] = accounts or []
        self._current_index = 0
        self.guest_token: str | None = None
        self.guest_token_expiry: float = 0.0

        # Auto-detect single account from environment variables if present
        env_auth = os.getenv("TWITTER_AUTH_TOKEN")
        env_ct0 = os.getenv("TWITTER_CT0")
        if env_auth and env_ct0 and not self.accounts:
            self.accounts.append(
                TwitterAccount(auth_token=env_auth, ct0=env_ct0, username="env_user")
            )

    @property
    def has_authenticated_accounts(self) -> bool:
        """Whether at least one authenticated account is configured."""
        return any(a.is_active for a in self.accounts)

    def add_account(self, auth_token: str, ct0: str, username: str = "anon") -> None:
        """Add a new account to the rotation pool."""
        self.accounts.append(
            TwitterAccount(auth_token=auth_token, ct0=ct0, username=username)
        )

    def get_account(self) -> TwitterAccount | None:
        """Get next available active account in round-robin fashion."""
        available = [a for a in self.accounts if a.is_available]
        if not available:
            return None
        self._current_index = self._current_index % len(available)
        account = available[self._current_index]
        self._current_index = (self._current_index + 1) % len(available)
        return account

    async def get_or_refresh_guest_token(self, client: httpx.AsyncClient) -> str | None:
        """Activate and cache an anonymous Twitter guest token."""
        now = time.time()
        if self.guest_token and now < self.guest_token_expiry:
            return self.guest_token

        activate_url = "https://api.twitter.com/1.1/guest/activate.json"
        headers = {
            "authorization": f"Bearer {TWITTER_BEARER_TOKEN}",
            "user-agent": TWITTER_GRAPHQL_HEADERS["user-agent"],
        }
        try:
            resp = await client.post(activate_url, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                self.guest_token = data.get("guest_token")
                # Guest tokens typically last 3 hours; refresh after 2.5 hours
                self.guest_token_expiry = now + (150 * 60)
                logger.info("Successfully acquired fresh Twitter guest token")
                return self.guest_token
            logger.warning(
                f"Guest token activation failed with HTTP {resp.status_code}"
            )
        except Exception as e:
            logger.warning(f"Failed to activate Twitter guest token: {e}")

        return None

    async def prepare_request(
        self, client: httpx.AsyncClient
    ) -> tuple[dict[str, str], dict[str, str], bool]:
        """
        Prepare headers, cookies, and authentication state for Twitter request.
        Returns (headers, cookies, is_authenticated).
        """
        headers = dict(TWITTER_GRAPHQL_HEADERS)
        cookies: dict[str, str] = {}

        account = self.get_account()
        if account:
            headers["x-csrf-token"] = account.ct0
            cookies["auth_token"] = account.auth_token
            cookies["ct0"] = account.ct0
            return headers, cookies, True

        # Fallback to guest token
        guest_token = await self.get_or_refresh_guest_token(client)
        if guest_token:
            headers["x-guest-token"] = guest_token
            return headers, cookies, False

        return headers, cookies, False


# Global default pool instance
default_session_pool = SessionPool()
