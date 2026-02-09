"""
Friday 2.0 - Gateway test fixtures.

Shared fixtures for gateway unit tests.
"""

from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from services.gateway.config import GatewaySettings, get_settings
from services.gateway.healthcheck import HealthChecker
from services.gateway.main import create_app


@pytest.fixture
def test_settings() -> GatewaySettings:
    """Gateway settings for testing."""
    return GatewaySettings(
        api_token="test-secret-token-12345",
        postgres_dsn="",
        redis_url="",
        environment="testing",
        log_level="DEBUG",
        healthcheck_cache_ttl=5,
    )


class MockAsyncContextManager:
    """Mock for asyncpg pool.acquire() async context manager."""

    def __init__(self, conn: AsyncMock) -> None:
        self.conn = conn

    async def __aenter__(self) -> AsyncMock:
        return self.conn

    async def __aexit__(self, *args: object) -> None:
        pass


class FailingAsyncContextManager:
    """Mock that raises on __aenter__ (simulate connection failure)."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def __aenter__(self) -> None:
        raise self.exc

    async def __aexit__(self, *args: object) -> None:
        pass


@pytest.fixture
def mock_pg_conn() -> AsyncMock:
    """Mock asyncpg connection."""
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    return conn


@pytest.fixture
def mock_pg_pool(mock_pg_conn: AsyncMock) -> MagicMock:
    """Mock asyncpg connection pool."""
    pool = MagicMock()
    pool.acquire.return_value = MockAsyncContextManager(mock_pg_conn)
    pool.close = AsyncMock()
    return pool


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock Redis client."""
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def health_checker(mock_pg_pool: MagicMock, mock_redis: AsyncMock) -> HealthChecker:
    """HealthChecker with mocked dependencies."""
    return HealthChecker(
        pg_pool=mock_pg_pool,
        redis=mock_redis,
        cache_ttl=5,
    )


@pytest.fixture
def app(test_settings: GatewaySettings, health_checker: HealthChecker) -> TestClient:
    """FastAPI test client with mocked dependencies."""
    application = create_app(settings=test_settings)

    # Override get_settings dependency for auth module
    application.dependency_overrides[get_settings] = lambda: test_settings

    # Override lifespan state
    application.state.health_checker = health_checker
    application.state.pg_pool = health_checker.pg_pool
    application.state.redis = health_checker.redis

    return TestClient(application, raise_server_exceptions=False)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Valid authentication headers."""
    return {"Authorization": "Bearer test-secret-token-12345"}


@pytest.fixture
def invalid_auth_headers() -> dict[str, str]:
    """Invalid authentication headers."""
    return {"Authorization": "Bearer wrong-token"}
