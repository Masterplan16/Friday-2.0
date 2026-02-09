"""
Friday 2.0 - Gateway configuration via Pydantic Settings.

All values from environment variables. NEVER hardcode credentials.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class GatewaySettings(BaseSettings):
    """Gateway configuration loaded from environment variables."""

    # Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    environment: str = "production"
    log_level: str = "INFO"

    # Authentication
    api_token: str = ""  # MUST be set via env var, never default to a real value

    # Database
    postgres_dsn: str = ""  # postgresql://user:pass@host:port/db

    # Redis
    redis_url: str = ""  # redis://user:pass@host:port/db

    # Healthcheck
    healthcheck_cache_ttl: int = 5  # seconds

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {"env_prefix": "", "case_sensitive": False}


@lru_cache
def get_settings() -> GatewaySettings:
    """Factory for gateway settings (cached singleton)."""
    return GatewaySettings()
