"""
Friday 2.0 - Bearer token authentication.

Single-user auth for owner. Token from API_TOKEN env var (age/SOPS encrypted).
"""

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import GatewaySettings, get_settings

logger = structlog.get_logger()

security = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    settings: GatewaySettings = Depends(get_settings),
) -> dict[str, str]:
    """
    Verify the bearer token. Single-user, simple comparison.

    Returns user dict if valid, raises 401 if invalid.
    """
    if not settings.api_token:
        logger.error("api_token_not_configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API token not configured",
        )

    token = credentials.credentials
    if token != settings.api_token:
        logger.warning("invalid_token_attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {"username": "antonio"}


async def get_current_user(
    user: dict[str, str] = Depends(verify_token),
) -> dict[str, str]:
    """Dependency to get the current authenticated user."""
    return user
