"""
Friday 2.0 - Tests for bearer token authentication.

Covers AC #7: Auth bearer token simple for single-user.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from services.gateway.config import GatewaySettings, get_settings
from services.gateway.healthcheck import HealthChecker
from services.gateway.main import create_app


class TestBearerTokenAuth:
    """Test bearer token authentication (AC #7)."""

    def test_valid_token_returns_200(
        self, app: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Valid bearer token should return 200 with user info."""
        response = app.get("/api/v1/protected", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "mainteneur"

    def test_invalid_token_returns_401(
        self, app: TestClient, invalid_auth_headers: dict[str, str]
    ) -> None:
        """Invalid bearer token should return 401."""
        response = app.get("/api/v1/protected", headers=invalid_auth_headers)
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    def test_missing_token_returns_401_or_403(self, app: TestClient) -> None:
        """Missing Authorization header should return 401 or 403."""
        response = app.get("/api/v1/protected")
        assert response.status_code in (401, 403)

    def test_empty_bearer_returns_401(self, app: TestClient) -> None:
        """Empty bearer token should return 401."""
        response = app.get(
            "/api/v1/protected", headers={"Authorization": "Bearer "}
        )
        # FastAPI HTTPBearer will reject empty tokens
        assert response.status_code in (401, 403)

    def test_no_api_token_configured_returns_500(
        self, test_settings: GatewaySettings
    ) -> None:
        """If API_TOKEN env var is not set, should return 500."""
        no_token_settings = GatewaySettings(
            api_token="",
            environment="testing",
        )
        application = create_app(settings=no_token_settings)
        application.dependency_overrides[get_settings] = lambda: no_token_settings
        application.state.health_checker = HealthChecker()
        client = TestClient(application, raise_server_exceptions=False)
        response = client.get(
            "/api/v1/protected",
            headers={"Authorization": "Bearer any-token"},
        )
        assert response.status_code == 500

    def test_health_endpoint_no_auth_required(self, app: TestClient) -> None:
        """Health endpoint should NOT require authentication."""
        response = app.get("/api/v1/health")
        # Should not be 401/403 - health is public
        assert response.status_code in (200, 503)
