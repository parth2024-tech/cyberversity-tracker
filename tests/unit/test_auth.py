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
