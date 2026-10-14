"""
Administrative authentication and access control.
Enforces API key verification on mutating endpoints.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ai_security_monitor.config.settings import settings

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


async def require_admin_auth(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    bearer: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> bool:
    """
    Validate that the incoming request has a valid administrative API key.
    Accepts:
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

    provided_token = x_admin_key or (bearer.credentials if bearer else None)

    if not provided_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing administrative credentials. Provide 'X-Admin-Key' or 'Authorization: Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not hmac.compare_digest(provided_token, configured_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrative credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True
