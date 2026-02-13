"""
Friday 2.0 - OAuth2/XOAUTH2 Manager (D25 - faille #6)

Module PREPARE mais PAS ACTIVE Day 1.
App Passwords Gmail suffisent pour le moment.

Si Google desactive App Passwords -> activer ce module :
    1. Obtenir OAuth2 credentials (Google Cloud Console)
    2. Set GMAIL_AUTH_METHOD=oauth2 dans .env
    3. Set GMAIL_OAUTH2_CLIENT_ID, GMAIL_OAUTH2_CLIENT_SECRET, GMAIL_OAUTH2_REFRESH_TOKEN
    4. Ce module genere access tokens automatiquement (refresh avant expiration)

Usage futur:
    from services.email_processor.oauth2_manager import get_imap_credentials

    creds = await get_imap_credentials("account_professional")
    # creds.password = access_token si OAuth2, sinon app_password

Decision: D25 (2026-02-13) - Faille adversariale #6 corrigee
Version: 1.0.0 (stub)
"""

import os
import time
from typing import Optional

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class IMAPCredentials(BaseModel):
    """Credentials IMAP (password ou OAuth2 access token)."""

    user: str
    password: str
    auth_method: str  # "app_password" ou "oauth2"


class OAuth2Token(BaseModel):
    """Token OAuth2 avec expiration."""

    access_token: str
    expires_at: float  # Unix timestamp
    token_type: str = "Bearer"

    @property
    def is_expired(self) -> bool:
        """Token expire si <5 min avant expiration."""
        return time.time() > (self.expires_at - 300)


# Cache tokens en memoire (pas de persistence)
_token_cache: dict[str, OAuth2Token] = {}


async def get_imap_credentials(account_id: str) -> IMAPCredentials:
    """
    Retourne les credentials IMAP pour un compte.

    Si auth_method=app_password : retourne le password directement.
    Si auth_method=oauth2 : genere/refresh un access token.

    Args:
        account_id: ID du compte (ex: "account_professional")

    Returns:
        IMAPCredentials avec user + password/token
    """
    raw_id = account_id.replace("account_", "").upper()
    prefix = f"IMAP_ACCOUNT_{raw_id}"

    user = os.getenv(f"{prefix}_IMAP_USER", "")
    auth_method = os.getenv(f"{prefix}_AUTH_METHOD", "app_password")

    if auth_method == "oauth2":
        token = await _get_or_refresh_token(account_id)
        return IMAPCredentials(
            user=user,
            password=token.access_token,
            auth_method="oauth2",
        )

    # Default: app_password
    password = os.getenv(f"{prefix}_IMAP_PASSWORD", "")
    return IMAPCredentials(
        user=user,
        password=password,
        auth_method="app_password",
    )


async def _get_or_refresh_token(account_id: str) -> OAuth2Token:
    """
    Recupere un access token valide depuis le cache ou refresh.

    STUB: Pas implemente Day 1. Raise NotImplementedError.
    A activer quand Google desactive App Passwords.
    """
    # Check cache
    cached = _token_cache.get(account_id)
    if cached and not cached.is_expired:
        return cached

    # Refresh token
    token = await _refresh_oauth2_token(account_id)
    _token_cache[account_id] = token
    return token


async def _refresh_oauth2_token(account_id: str) -> OAuth2Token:
    """
    Refresh OAuth2 token via Google OAuth2 endpoint.

    STUB Day 1 : Raise NotImplementedError.

    Implementation future :
        POST https://oauth2.googleapis.com/token
        client_id=...
        client_secret=...
        refresh_token=...
        grant_type=refresh_token

        Response: { access_token, expires_in, token_type }
    """
    raise NotImplementedError(
        "OAuth2 token refresh not implemented Day 1. "
        "Set GMAIL_AUTH_METHOD=app_password or implement this method. "
        "See D25 plan faille #6 for details."
    )
