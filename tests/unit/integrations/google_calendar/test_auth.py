"""Unit tests for Google Calendar OAuth2 authentication."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from agents.src.integrations.google_calendar.auth import GoogleCalendarAuth
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials


@pytest.fixture
def mock_credentials():
    """Create mock Google OAuth2 credentials."""
    return Mock(
        token="mock_access_token",
        refresh_token="mock_refresh_token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="mock_client_id",
        client_secret="mock_client_secret",
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
        ],
        expiry=datetime.now() + timedelta(hours=1),
        valid=True,
    )


@pytest.fixture
def temp_credentials_path(tmp_path):
    """Create temporary path for credentials storage."""
    return tmp_path / "test_token.json"


class TestGoogleCalendarAuth:
    """Test suite for GoogleCalendarAuth."""

    @pytest.mark.asyncio
    async def test_oauth2_first_run_flow(self, temp_credentials_path, mock_credentials):
        """Test OAuth2 flow on first run (no existing token.json)."""
        # Arrange
        auth_manager = GoogleCalendarAuth(credentials_path=str(temp_credentials_path))

        # Mock client_secret.json existence and InstalledAppFlow
        with patch("pathlib.Path.exists") as mock_exists:
            # client_secret.json exists, token.json doesn't
            mock_exists.return_value = True

            with patch(
                "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file"
            ) as mock_flow_factory:
                mock_flow = Mock()
                mock_flow.run_local_server.return_value = mock_credentials
                mock_flow_factory.return_value = mock_flow

                with patch.object(auth_manager, "save_credentials"):
                    # Act
                    creds = await auth_manager.get_credentials()

        # Assert
        assert creds is not None
        assert creds.token == "mock_access_token"
        assert creds.refresh_token == "mock_refresh_token"
        assert creds.valid is True
        mock_flow.run_local_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_refresh_automatic(self, temp_credentials_path, mock_credentials):
        """Test automatic token refresh when expired."""
        # Arrange - Create expired token
        expired_creds = Mock(
            token="old_token",
            refresh_token="mock_refresh_token",
            token_uri="https://oauth2.googleapis.com/token",
            client_id="mock_client_id",
            client_secret="mock_client_secret",
            scopes=[
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events",
            ],
            expiry=datetime.now() - timedelta(hours=1),  # Expired
            valid=False,
            expired=True,
        )

        # Save expired token to file
        token_data = {
            "token": expired_creds.token,
            "refresh_token": expired_creds.refresh_token,
            "token_uri": expired_creds.token_uri,
            "client_id": expired_creds.client_id,
            "client_secret": expired_creds.client_secret,
            "scopes": expired_creds.scopes,
            "expiry": expired_creds.expiry.isoformat(),
        }
        temp_credentials_path.write_text(json.dumps(token_data))

        auth_manager = GoogleCalendarAuth(credentials_path=str(temp_credentials_path))

        # Mock refresh request
        with patch("google.auth.transport.requests.Request") as mock_request:
            with patch.object(Credentials, "from_authorized_user_file", return_value=expired_creds):
                with patch.object(expired_creds, "refresh") as mock_refresh:
                    # Simulate successful refresh
                    def refresh_side_effect(req):
                        expired_creds.token = "new_refreshed_token"
                        expired_creds.valid = True
                        expired_creds.expired = False

                    mock_refresh.side_effect = refresh_side_effect

                    # Act
                    creds = await auth_manager.get_credentials()

            # Assert
            assert creds is not None
            assert creds.token == "new_refreshed_token"
            mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_credentials_expired_re_authentication(
        self, temp_credentials_path, mock_credentials
    ):
        """Test re-authentication when credentials cannot be refreshed."""
        # Arrange - Create token that fails refresh
        bad_creds = Mock(
            token="old_token",
            refresh_token="invalid_refresh_token",
            valid=False,
            expired=True,
        )
        bad_creds.refresh.side_effect = RefreshError("Invalid refresh token")

        temp_credentials_path.write_text(
            json.dumps(
                {
                    "token": "old_token",
                    "refresh_token": "invalid_refresh_token",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "client_id": "mock_client_id",
                    "client_secret": "mock_client_secret",
                    "scopes": [
                        "https://www.googleapis.com/auth/calendar",
                        "https://www.googleapis.com/auth/calendar.events",
                    ],
                }
            )
        )

        auth_manager = GoogleCalendarAuth(credentials_path=str(temp_credentials_path))

        # Mock client_secret.json existence and re-authentication flow
        with patch("pathlib.Path.exists") as mock_exists:
            # client_secret.json exists
            mock_exists.return_value = True

            with patch(
                "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file"
            ) as mock_flow_factory:
                mock_flow = Mock()
                mock_flow.run_local_server.return_value = mock_credentials
                mock_flow_factory.return_value = mock_flow

                with patch.object(Credentials, "from_authorized_user_file", return_value=bad_creds):
                    with patch("google.auth.transport.requests.Request"):
                        with patch.object(auth_manager, "save_credentials"):
                            # Act
                            creds = await auth_manager.get_credentials()

        # Assert - Should re-authenticate
        assert creds is not None
        assert creds.token == "mock_access_token"
        mock_flow.run_local_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_sops_decrypt_token_json(self, temp_credentials_path):
        """Test SOPS decryption of token.json.enc."""
        # Arrange - Create encrypted token file (simulated)
        encrypted_path = temp_credentials_path.with_suffix(".json.enc")
        encrypted_path.write_text("encrypted_content_placeholder")

        auth_manager = GoogleCalendarAuth(
            credentials_path=str(temp_credentials_path),
            encrypted_credentials_path=str(encrypted_path),
        )

        mock_decrypted_data = {
            "token": "decrypted_token",
            "refresh_token": "decrypted_refresh_token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "mock_client_id",
            "client_secret": "mock_client_secret",
            "scopes": [
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events",
            ],
            "expiry": (datetime.now() + timedelta(hours=1)).isoformat(),
        }

        # Mock SOPS decrypt
        with patch("subprocess.run") as mock_sops:
            mock_sops.return_value = Mock(
                returncode=0, stdout=json.dumps(mock_decrypted_data).encode()
            )

            # Act
            decrypted = await auth_manager._decrypt_credentials_with_sops(str(encrypted_path))

        # Assert
        assert decrypted is not None
        assert decrypted["token"] == "decrypted_token"
        mock_sops.assert_called_once()

    @pytest.mark.asyncio
    async def test_fail_explicit_invalid_client_secret(self, temp_credentials_path):
        """Test fail-explicit behavior when client_secret.json is invalid."""
        # Arrange
        auth_manager = GoogleCalendarAuth(
            credentials_path=str(temp_credentials_path),
            client_secret_path="nonexistent_client_secret.json",
        )

        # Mock flow to raise exception
        with patch(
            "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file"
        ) as mock_flow:
            mock_flow.side_effect = FileNotFoundError("client_secret.json not found")

            # Act & Assert
            with pytest.raises(NotImplementedError) as exc_info:
                await auth_manager.get_credentials()

            assert "OAuth2 authentication failed" in str(exc_info.value)
            assert "client_secret.json not found" in str(exc_info.value)
