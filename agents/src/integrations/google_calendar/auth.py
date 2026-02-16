"""Google Calendar OAuth2 authentication manager."""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Scopes required for Google Calendar API
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


class GoogleCalendarAuth:
    """Manage Google Calendar OAuth2 authentication.

    Handles OAuth2 flow, token refresh, and SOPS encryption for credentials.

    Attributes:
        credentials_path: Path to store/load token.json (decrypted)
        encrypted_credentials_path: Path to encrypted token.json.enc (SOPS)
        client_secret_path: Path to Google OAuth2 client_secret.json
    """

    def __init__(
        self,
        credentials_path: str = "config/token.json",
        encrypted_credentials_path: Optional[str] = None,
        client_secret_path: str = "config/google_client_secret.json",
    ):
        """Initialize authentication manager.

        Args:
            credentials_path: Path to token.json file (decrypted)
            encrypted_credentials_path: Path to token.json.enc (SOPS encrypted)
            client_secret_path: Path to client_secret.json from Google Cloud Console
        """
        self.credentials_path = Path(credentials_path)
        self.encrypted_credentials_path = (
            Path(encrypted_credentials_path)
            if encrypted_credentials_path
            else self.credentials_path.with_suffix(".json.enc")
        )
        self.client_secret_path = Path(client_secret_path)

    async def get_credentials(self) -> Credentials:
        """Get valid Google Calendar API credentials.

        Workflow:
        1. Try loading from encrypted token.json.enc (SOPS decrypt)
        2. If not exists, try loading from token.json
        3. If expired, refresh token
        4. If refresh fails, run OAuth2 flow
        5. Save new credentials (encrypted)

        Returns:
            Valid Google OAuth2 credentials

        Raises:
            NotImplementedError: If OAuth2 authentication fails (fail-explicit)
        """
        creds = None

        # Try loading encrypted credentials first (SOPS)
        if self.encrypted_credentials_path.exists():
            try:
                decrypted_data = await self._decrypt_credentials_with_sops(
                    str(self.encrypted_credentials_path)
                )
                if decrypted_data:
                    # Save decrypted to temp file for Credentials.from_authorized_user_info
                    creds = Credentials.from_authorized_user_info(
                        decrypted_data, CALENDAR_SCOPES
                    )
            except Exception as e:
                # Fallback to regular token.json
                pass

        # Try loading from unencrypted token.json
        if not creds and self.credentials_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.credentials_path), CALENDAR_SCOPES
                )
            except Exception as e:
                pass

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                # Refresh failed, need re-authentication
                creds = None

        # Run OAuth2 flow if no valid credentials
        if not creds or not creds.valid:
            try:
                if not self.client_secret_path.exists():
                    raise FileNotFoundError(
                        f"client_secret.json not found at {self.client_secret_path}"
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.client_secret_path), CALENDAR_SCOPES
                )
                creds = flow.run_local_server(port=0)

                # Save credentials
                await self.save_credentials(creds)

            except Exception as e:
                raise NotImplementedError(
                    f"OAuth2 authentication failed: {str(e)}. "
                    "Please check client_secret.json and ensure OAuth2 consent screen is configured."
                ) from e

        return creds

    async def save_credentials(self, creds: Credentials) -> None:
        """Save credentials to file (encrypted with SOPS).

        Args:
            creds: Google OAuth2 credentials to save
        """
        # Convert to dict
        creds_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }

        # Add expiry if exists
        if hasattr(creds, "expiry") and creds.expiry:
            creds_data["expiry"] = creds.expiry.isoformat()

        # Save to unencrypted file first
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self.credentials_path.write_text(json.dumps(creds_data, indent=2))

        # Encrypt with SOPS if configured
        if os.getenv("GOOGLE_CALENDAR_SOPS_ENABLED", "false").lower() == "true":
            try:
                await self._encrypt_credentials_with_sops(
                    str(self.credentials_path), str(self.encrypted_credentials_path)
                )
                # Remove unencrypted file after encryption
                self.credentials_path.unlink(missing_ok=True)
            except Exception as e:
                # Log warning but don't fail - credentials still saved unencrypted
                pass

    async def _decrypt_credentials_with_sops(
        self, encrypted_path: str
    ) -> Optional[dict]:
        """Decrypt credentials using SOPS.

        Args:
            encrypted_path: Path to encrypted token.json.enc

        Returns:
            Decrypted credentials dict, or None if decryption fails
        """
        try:
            result = subprocess.run(
                [
                    "sops",
                    "--input-type",
                    "json",
                    "--output-type",
                    "json",
                    "-d",
                    encrypted_path,
                ],
                capture_output=True,
                check=True,
            )
            return json.loads(result.stdout)
        except Exception as e:
            return None

    async def _encrypt_credentials_with_sops(
        self, input_path: str, output_path: str
    ) -> None:
        """Encrypt credentials using SOPS.

        Args:
            input_path: Path to unencrypted token.json
            output_path: Path to save encrypted token.json.enc
        """
        subprocess.run(
            [
                "sops",
                "--input-type",
                "json",
                "--output-type",
                "json",
                "-e",
                input_path,
            ],
            stdout=open(output_path, "w"),
            check=True,
        )

    async def refresh_credentials(self, creds: Credentials) -> Credentials:
        """Refresh expired credentials.

        Args:
            creds: Expired credentials to refresh

        Returns:
            Refreshed credentials

        Raises:
            RefreshError: If refresh fails
        """
        creds.refresh(Request())
        await self.save_credentials(creds)
        return creds
