"""Unit tests for administrative authentication and access control."""

from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.auth import require_admin_auth

_auth_app = FastAPI()


@_auth_app.post("/test-admin-only")
async def admin_only_route(_admin: bool = Depends(require_admin_auth)):
    return {"status": "authorized"}


client = TestClient(_auth_app)


def test_auth_permits_when_no_key_configured_in_dev():
    """In non-production dev environments without key, access is permitted."""
    with (
        patch.object(settings.api, "admin_api_key", None),
        patch.object(settings, "environment", "development"),
    ):
        res = client.post("/test-admin-only")
        assert res.status_code == 200
        assert res.json() == {"status": "authorized"}


def test_auth_rejects_missing_credentials_when_key_configured():
    """When an admin key is set, unauthenticated requests are rejected with 401."""
    with patch.object(settings.api, "admin_api_key", "super-secret-key"):
        res = client.post("/test-admin-only")
        assert res.status_code == 401
        assert "missing administrative credentials" in res.json()["detail"].lower()


def test_auth_rejects_invalid_key():
    """Invalid token returns 401."""
    with patch.object(settings.api, "admin_api_key", "super-secret-key"):
        res = client.post(
            "/test-admin-only", headers={"X-Admin-Key": "wrong-secret-key"}
        )
        assert res.status_code == 401
        assert "invalid administrative credentials" in res.json()["detail"].lower()


def test_auth_accepts_valid_x_admin_key():
    """Valid X-Admin-Key header grants access."""
    with patch.object(settings.api, "admin_api_key", "super-secret-key"):
        res = client.post(
            "/test-admin-only", headers={"X-Admin-Key": "super-secret-key"}
        )
        assert res.status_code == 200
        assert res.json() == {"status": "authorized"}


def test_auth_accepts_valid_bearer_token():
    """Valid Bearer authorization token grants access."""
    with patch.object(settings.api, "admin_api_key", "super-secret-key"):
        res = client.post(
            "/test-admin-only",
            headers={"Authorization": "Bearer super-secret-key"},
        )
        assert res.status_code == 200
        assert res.json() == {"status": "authorized"}


def test_auth_denies_in_production_when_no_key_configured():
    """In production, missing ADMIN_API_KEY must fail-closed with 401."""
    with (
        patch.object(settings.api, "admin_api_key", None),
        patch.object(settings, "environment", "production"),
    ):
        res = client.post("/test-admin-only")
        assert res.status_code == 401
        assert "must be configured in production" in res.json()["detail"].lower()


def test_auth_accepts_valid_httponly_session_cookie():
    """Valid signed HttpOnly session cookie grants access without exposing credentials in JS."""
    import time

    from ai_security_monitor.core.auth import (
        ADMIN_SESSION_COOKIE_NAME,
        sign_admin_session,
    )

    key = "super-secret-key"
    expires_at = int(time.time()) + 3600
    valid_cookie = sign_admin_session(key, expires_at)

    with patch.object(settings.api, "admin_api_key", key):
        res = client.post(
            "/test-admin-only",
            cookies={ADMIN_SESSION_COOKIE_NAME: valid_cookie},
        )
        assert res.status_code == 200
        assert res.json() == {"status": "authorized"}


def test_auth_rejects_expired_or_tampered_session_cookie():
    """Expired or cryptographically tampered cookies are rejected."""
    import time

    from ai_security_monitor.core.auth import (
        ADMIN_SESSION_COOKIE_NAME,
        sign_admin_session,
    )

    key = "super-secret-key"
    past = int(time.time()) - 100
    expired_cookie = sign_admin_session(key, past)
    tampered_cookie = "admin:9999999999:badsignature123"

    with patch.object(settings.api, "admin_api_key", key):
        res_exp = client.post("/test-admin-only", cookies={ADMIN_SESSION_COOKIE_NAME: expired_cookie})
        assert res_exp.status_code == 401

        res_tamp = client.post("/test-admin-only", cookies={ADMIN_SESSION_COOKIE_NAME: tampered_cookie})
        assert res_tamp.status_code == 401


def test_auth_session_endpoint_lifecycle():
    """Test full login, status, and logout lifecycle for /api/auth/session."""
    from ai_security_monitor.presentation.api.main import create_app

    full_app = create_app()
    full_client = TestClient(full_app)
    key = "test-cluster-key"

    with patch.object(settings.api, "admin_api_key", key):
        # 1. Invalid key fails
        bad_res = full_client.post("/api/auth/session", json={"admin_key": "wrong"})
        assert bad_res.status_code == 401

        # 2. Valid key establishes HttpOnly session
        good_res = full_client.post("/api/auth/session", json={"admin_key": key})
        assert good_res.status_code == 200
        assert "aetherguard_admin_session" in good_res.cookies

        # 3. Session status check reports authenticated
        status_res = full_client.get("/api/auth/status", cookies=good_res.cookies)
        assert status_res.status_code == 200
        assert status_res.json()["authenticated"] is True

        # 4. Logout revokes session cookie
        logout_res = full_client.delete("/api/auth/session")
        assert logout_res.status_code == 200

