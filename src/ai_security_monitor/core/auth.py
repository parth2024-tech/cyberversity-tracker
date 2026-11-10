"""
Administrative authentication and access control.
Enforces API key verification and HttpOnly signed session cookies on mutating endpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from fastapi import Cookie, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ai_security_monitor.config.settings import settings

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

ADMIN_SESSION_COOKIE_NAME = "aetherguard_admin_session"
ADMIN_SESSION_TTL_SECONDS = 7 * 86400  # 7 days


def sign_admin_session(admin_key: str, expires_at: int) -> str:
    """Generate an HMAC-SHA256 signature for a session cookie timestamp."""
    payload = f"admin:{expires_at}".encode()
    sig = hmac.new(admin_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"admin:{expires_at}:{sig}"


def verify_admin_session(session_token: str | None, configured_key: str) -> bool:
    """Verify cryptographic authenticity and freshness of an HttpOnly admin session token."""
    if not session_token or not configured_key:
        return False

    parts = session_token.split(":")
    if len(parts) != 3 or parts[0] != "admin":
        return False

    try:
        expires_at = int(parts[1])
    except ValueError:
        return False

    if time.time() > expires_at:
        return False

    expected_sig = hmac.new(
        configured_key.encode("utf-8"),
        f"admin:{expires_at}".encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(parts[2], expected_sig)


async def require_admin_auth(
    aetherguard_admin_session: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE_NAME),
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    bearer: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> bool:
    """
    Validate that the incoming request has valid administrative credentials.
    Accepts:
      - HttpOnly signed cookie (`aetherguard_admin_session`)
      - X-Admin-Key header
      - Authorization: Bearer <admin_key>
    """
    configured_key = settings.api.admin_api_key

    # In production, admin_api_key must be configured
    if settings.is_production and not configured_key:
        logger.error("Admin API key is not configured in production environment!")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrative access disabled: ADMIN_API_KEY must be configured in production.",
        )

    # In development or testing with no key configured, permit access
    if not configured_key:
        return True

    # 1. Verify HttpOnly signed session cookie first
    if aetherguard_admin_session and verify_admin_session(aetherguard_admin_session, configured_key):
        return True

    # 2. Check X-Admin-Key header or Bearer token
    provided_token = x_admin_key or (bearer.credentials if bearer else None)

    if not provided_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing administrative credentials. Provide 'X-Admin-Key', 'Authorization: Bearer <token>', or an active session.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not hmac.compare_digest(provided_token, configured_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrative credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True
