"""Google Calendar OAuth2 authentication manager."""

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

import structlog
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = structlog.get_logger(__name__)

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
                    creds = Credentials.from_authorized_user_info(decrypted_data, CALENDAR_SCOPES)
            except Exception as e:
                # H1 fix: log the error instead of silently swallowing
                logger.warning(
                    "Failed to decrypt SOPS credentials, falling back to token.json",
                    error=str(e),
                )

        # Try loading from unencrypted token.json
        if not creds and self.credentials_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.credentials_path), CALENDAR_SCOPES
                )
            except Exception as e:
                # H1 fix: log the error
                logger.warning("Failed to load token.json", error=str(e))

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                # C5 fix: run sync refresh in thread to avoid blocking event loop
                await asyncio.to_thread(creds.refresh, Request())
            except RefreshError as e:
                logger.warning(
                    "Token refresh failed, need re-authentication",
                    error=str(e),
                )
                creds = None

        # Run OAuth2 flow if no valid credentials
        if not creds or not creds.valid:
            try:
                if not self.client_secret_path.exists():
                    raise FileNotFoundError(
                        "client_secret.json not found at %s" % self.client_secret_path
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.client_secret_path), CALENDAR_SCOPES
                )
                # OAuth2 flow is interactive (opens browser) — run in thread
                creds = await asyncio.to_thread(flow.run_local_server, port=0)

                await self.save_credentials(creds)

            except Exception as e:
                raise NotImplementedError(
                    "OAuth2 authentication failed: %s. "
                    "Please check client_secret.json and ensure OAuth2 consent screen is configured."
                    % str(e)
                ) from e

        return creds

    async def save_credentials(self, creds: Credentials) -> None:
        """Save credentials to file (encrypted with SOPS).

        Args:
            creds: Google OAuth2 credentials to save
        """
        creds_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else [],
        }

        if hasattr(creds, "expiry") and creds.expiry:
            creds_data["expiry"] = creds.expiry.isoformat()

        # Save to unencrypted file first
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self.credentials_path.write_text(json.dumps(creds_data, indent=2))

        # H3 fix: SOPS enabled by default in production, warn if disabled
        sops_enabled = os.getenv("GOOGLE_CALENDAR_SOPS_ENABLED", "true").lower() == "true"
        if sops_enabled:
            try:
                await self._encrypt_credentials_with_sops(
                    str(self.credentials_path), str(self.encrypted_credentials_path)
                )
                # Remove unencrypted file after encryption
                self.credentials_path.unlink(missing_ok=True)
            except Exception as e:
                # H1 fix: log the error
                logger.warning(
                    "SOPS encryption failed, credentials saved unencrypted",
                    error=str(e),
                )
        else:
            logger.warning(
                "SOPS encryption DISABLED for Google Calendar credentials. "
                "Set GOOGLE_CALENDAR_SOPS_ENABLED=true in production."
            )

    async def _decrypt_credentials_with_sops(self, encrypted_path: str) -> Optional[dict]:
        """Decrypt credentials using SOPS.

        Args:
            encrypted_path: Path to encrypted token.json.enc

        Returns:
            Decrypted credentials dict, or None if decryption fails
        """
        try:
            # C5 fix: use async subprocess instead of blocking subprocess.run
            process = await asyncio.create_subprocess_exec(
                "sops",
                "--input-type",
                "json",
                "--output-type",
                "json",
                "-d",
                encrypted_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.warning(
                    "SOPS decrypt failed",
                    returncode=process.returncode,
                    stderr=stderr.decode() if stderr else "",
                )
                return None

            return json.loads(stdout)
        except Exception as e:
            logger.warning("SOPS decrypt error", error=str(e))
            return None

    async def _encrypt_credentials_with_sops(self, input_path: str, output_path: str) -> None:
        """Encrypt credentials using SOPS.

        Args:
            input_path: Path to unencrypted token.json
            output_path: Path to save encrypted token.json.enc
        """
        # H2 fix: use async subprocess with proper output handling (no file handle leak)
        process = await asyncio.create_subprocess_exec(
            "sops",
            "--input-type",
            "json",
            "--output-type",
            "json",
            "-e",
            input_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(
                "SOPS encrypt failed: %s" % (stderr.decode() if stderr else "unknown error")
            )

        # Write output to file safely
        Path(output_path).write_bytes(stdout)

    async def refresh_credentials(self, creds: Credentials) -> Credentials:
        """Refresh expired credentials.

        Args:
            creds: Expired credentials to refresh

        Returns:
            Refreshed credentials

        Raises:
            RefreshError: If refresh fails
        """
        # C5 fix: run sync refresh in thread
        await asyncio.to_thread(creds.refresh, Request())
        await self.save_credentials(creds)
        return creds
