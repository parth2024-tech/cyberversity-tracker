"""
Authentication and admin session router.
Provides Secure HttpOnly session establishment, revocation, and status checking.
"""

from __future__ import annotations

import hmac
import time
from typing import Any

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.auth import (
    ADMIN_SESSION_COOKIE_NAME,
    ADMIN_SESSION_TTL_SECONDS,
    sign_admin_session,
    verify_admin_session,
)

auth_router = APIRouter(prefix="/auth", tags=["Authentication"])


class SessionLoginRequest(BaseModel):
    admin_key: str = Field(..., description="Administrative API key configured on server")


class SessionResponse(BaseModel):
    status: str
    authenticated: bool
    expires_in_seconds: int = 0


@auth_router.post(
    "/session",
    response_model=SessionResponse,
    summary="Establish an HttpOnly Admin Session",
    description="Validates administrative key and exchanges it for a Secure HttpOnly session cookie, protecting against DOM XSS.",
)
async def login_admin_session(
    body: SessionLoginRequest,
    response: Response,
    request: Request,
) -> Any:
    configured_key = settings.api.admin_api_key

    if settings.is_production and not configured_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrative access disabled: ADMIN_API_KEY must be configured in production.",
        )

    if not configured_key:
        # Development / test mode with no key configured
        return SessionResponse(
            status="authorized_open_dev",
            authenticated=True,
            expires_in_seconds=ADMIN_SESSION_TTL_SECONDS,
        )

    provided = body.admin_key.strip()
    if not hmac.compare_digest(provided, configured_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrative credentials.",
        )

    expires_at = int(time.time()) + ADMIN_SESSION_TTL_SECONDS
    session_token = sign_admin_session(configured_key, expires_at)

    # In production, enforce Secure flag. In local HTTP testing, permit secure=False
    is_secure = settings.is_production and request.url.hostname not in ("localhost", "127.0.0.1")

    response.set_cookie(
        key=ADMIN_SESSION_COOKIE_NAME,
        value=session_token,
        max_age=ADMIN_SESSION_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=is_secure,
        path="/",
    )

    return SessionResponse(
        status="authenticated",
        authenticated=True,
        expires_in_seconds=ADMIN_SESSION_TTL_SECONDS,
    )


@auth_router.delete(
    "/session",
    summary="Revoke Admin Session Cookie",
    description="Clears the HttpOnly session cookie from the browser.",
)
async def logout_admin_session(response: Response) -> dict[str, str]:
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="strict",
    )
    return {"status": "session_terminated"}


@auth_router.get(
    "/status",
    summary="Check Administrative Session Status",
)
async def check_admin_status(
    aetherguard_admin_session: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE_NAME),
) -> dict[str, bool]:
    configured_key = settings.api.admin_api_key

    if not configured_key:
        # Open access in local development without key
        return {"authenticated": True, "auth_required": False}

    is_authed = bool(
        aetherguard_admin_session
        and verify_admin_session(aetherguard_admin_session, configured_key)
    )
    return {"authenticated": is_authed, "auth_required": True}
