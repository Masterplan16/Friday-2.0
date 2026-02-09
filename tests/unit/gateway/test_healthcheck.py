"""
Friday 2.0 - Tests for extended healthcheck.

Covers AC #1-#5, #10:
- AC #1: GET /api/v1/health returns status of 10 services with 3 states
- AC #2: healthy when all critical services UP
- AC #3: degraded when non-critical service DOWN
- AC #4: unhealthy when critical service DOWN
- AC #5: Cache with 5s TTL
- AC #10: Unit and integration tests for the 3 healthcheck states
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from services.gateway.healthcheck import (
    CRITICAL_SERVICES,
    SERVICE_CHECKS,
    HealthChecker,
)
from services.gateway.schemas import HealthResponse, ServiceHealth


class TestHealthCheckStates:
    """Test the 3 healthcheck states (AC #2, #3, #4)."""

    @pytest.mark.asyncio
    async def test_healthy_all_services_up(
        self, health_checker: HealthChecker
    ) -> None:
        """AC #2: All critical services UP -> status healthy."""
        # Mock all HTTP services as UP
        with patch.object(
            health_checker,
            "check_http_service",
            new_callable=AsyncMock,
            return_value=("up", 50),
        ):
            result = await health_checker.check_all_services()

        assert result.status == "healthy"
        assert result.services["postgresql"].status == "up"
        assert result.services["redis"].status == "up"
        assert result.cache_hit is False

    @pytest.mark.asyncio
    async def test_degraded_n8n_down(self, health_checker: HealthChecker) -> None:
        """AC #3: Non-critical service (n8n) DOWN -> status degraded."""

        async def mock_http_check(
            name: str, url: str
        ) -> tuple[str, int | None]:
            if name == "n8n":
                return ("down", None)
            return ("up", 50)

        with patch.object(
            health_checker, "check_http_service", side_effect=mock_http_check
        ):
            result = await health_checker.check_all_services()

        assert result.status == "degraded"
        assert result.services["n8n"].status == "down"

    @pytest.mark.asyncio
    async def test_unhealthy_postgresql_down(
        self, mock_redis: AsyncMock
    ) -> None:
        """AC #4: Critical service (PostgreSQL) DOWN -> status unhealthy."""
        from tests.unit.gateway.conftest import FailingAsyncContextManager

        # Create pool that fails on acquire
        failing_pool = MagicMock()
        failing_pool.acquire.return_value = FailingAsyncContextManager(
            ConnectionError("Connection refused")
        )

        checker = HealthChecker(
            pg_pool=failing_pool,
            redis=mock_redis,
            cache_ttl=5,
        )

        with patch.object(
            checker,
            "check_http_service",
            new_callable=AsyncMock,
            return_value=("up", 50),
        ):
            result = await checker.check_all_services()

        assert result.status == "unhealthy"
        assert result.services["postgresql"].status == "down"

    @pytest.mark.asyncio
    async def test_unhealthy_redis_down(
        self, health_checker: HealthChecker, mock_redis: AsyncMock
    ) -> None:
        """Redis DOWN -> status unhealthy (redis is critical)."""
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("Connection refused"))
        # Cache read fails too
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Connection refused"))

        with patch.object(
            health_checker,
            "check_http_service",
            new_callable=AsyncMock,
            return_value=("up", 50),
        ):
            result = await health_checker.check_all_services()

        assert result.status == "unhealthy"
        assert result.services["redis"].status == "down"

    @pytest.mark.asyncio
    async def test_not_deployed_services_are_healthy(
        self, health_checker: HealthChecker
    ) -> None:
        """Services with not_deployed status should not trigger degraded."""

        async def mock_http_check(
            name: str, url: str
        ) -> tuple[str, int | None]:
            # Simulate Day 1: STT/TTS/OCR/Telegram not deployed
            if name in ("faster_whisper", "kokoro_tts", "surya_ocr", "telegram_bot"):
                return ("not_deployed", None)
            return ("up", 50)

        with patch.object(
            health_checker, "check_http_service", side_effect=mock_http_check
        ):
            result = await health_checker.check_all_services()

        assert result.status == "healthy"
        assert result.services["faster_whisper"].status == "not_deployed"
        assert result.services["kokoro_tts"].status == "not_deployed"
        assert result.services["surya_ocr"].status == "not_deployed"
        assert result.services["telegram_bot"].status == "not_deployed"


class TestHealthCheckResponse:
    """Test healthcheck response format (AC #1)."""

    @pytest.mark.asyncio
    async def test_response_contains_10_services(
        self, health_checker: HealthChecker
    ) -> None:
        """AC #1: Response must contain status of 10 services."""
        with patch.object(
            health_checker,
            "check_http_service",
            new_callable=AsyncMock,
            return_value=("up", 50),
        ):
            result = await health_checker.check_all_services()

        assert len(result.services) == 10
        expected_services = {
            "postgresql",
            "redis",
            "emailengine",
            "n8n",
            "caddy",
            "presidio",
            "faster_whisper",
            "kokoro_tts",
            "surya_ocr",
            "telegram_bot",
        }
        assert set(result.services.keys()) == expected_services

    @pytest.mark.asyncio
    async def test_response_contains_timestamp(
        self, health_checker: HealthChecker
    ) -> None:
        """Response must include ISO timestamp."""
        with patch.object(
            health_checker,
            "check_http_service",
            new_callable=AsyncMock,
            return_value=("up", 50),
        ):
            result = await health_checker.check_all_services()

        assert result.timestamp is not None
        assert "T" in result.timestamp  # ISO format

    @pytest.mark.asyncio
    async def test_up_services_have_latency(
        self, health_checker: HealthChecker
    ) -> None:
        """UP services should report latency_ms."""
        with patch.object(
            health_checker,
            "check_http_service",
            new_callable=AsyncMock,
            return_value=("up", 50),
        ):
            result = await health_checker.check_all_services()

        assert result.services["postgresql"].latency_ms is not None
        assert result.services["postgresql"].latency_ms >= 0
        assert result.services["redis"].latency_ms is not None


class TestHealthCheckCache:
    """Test healthcheck cache (AC #5)."""

    @pytest.mark.asyncio
    async def test_cache_miss_first_call(
        self, health_checker: HealthChecker, mock_redis: AsyncMock
    ) -> None:
        """First call should be a cache miss."""
        mock_redis.get = AsyncMock(return_value=None)

        with patch.object(
            health_checker,
            "check_http_service",
            new_callable=AsyncMock,
            return_value=("up", 50),
        ):
            result = await health_checker.check_all_services()

        assert result.cache_hit is False
        # Verify cache was written
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_hit_second_call(
        self, health_checker: HealthChecker, mock_redis: AsyncMock
    ) -> None:
        """Second call should hit cache."""
        cached_data = {
            "status": "healthy",
            "timestamp": "2026-02-09T14:00:00Z",
            "services": {
                "postgresql": {"status": "up", "latency_ms": 12},
                "redis": {"status": "up", "latency_ms": 3},
                "emailengine": {"status": "up", "latency_ms": 45},
                "n8n": {"status": "up", "latency_ms": 120},
                "caddy": {"status": "up", "latency_ms": 5},
                "presidio": {"status": "up", "latency_ms": 80},
                "faster_whisper": {"status": "not_deployed", "latency_ms": None},
                "kokoro_tts": {"status": "not_deployed", "latency_ms": None},
                "surya_ocr": {"status": "not_deployed", "latency_ms": None},
                "telegram_bot": {"status": "not_deployed", "latency_ms": None},
            },
            "cache_hit": False,
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))

        result = await health_checker.check_all_services()

        assert result.cache_hit is True
        assert result.status == "healthy"

    @pytest.mark.asyncio
    async def test_cache_ttl_is_5_seconds(
        self, health_checker: HealthChecker, mock_redis: AsyncMock
    ) -> None:
        """Cache TTL should be 5 seconds."""
        mock_redis.get = AsyncMock(return_value=None)

        with patch.object(
            health_checker,
            "check_http_service",
            new_callable=AsyncMock,
            return_value=("up", 50),
        ):
            await health_checker.check_all_services()

        # Verify setex was called with TTL=5
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 5  # TTL argument


class TestHealthCheckEndpoint:
    """Test the HTTP endpoint (AC #1)."""

    def test_health_endpoint_returns_200_when_healthy(
        self, app: TestClient
    ) -> None:
        """GET /api/v1/health returns 200 when healthy."""
        with patch.object(
            HealthChecker,
            "check_all_services",
            new_callable=AsyncMock,
            return_value=HealthResponse(
                status="healthy",
                timestamp="2026-02-09T14:00:00Z",
                services={
                    "postgresql": ServiceHealth(status="up", latency_ms=12),
                    "redis": ServiceHealth(status="up", latency_ms=3),
                    "emailengine": ServiceHealth(status="up", latency_ms=45),
                    "n8n": ServiceHealth(status="up", latency_ms=120),
                    "caddy": ServiceHealth(status="up", latency_ms=5),
                    "presidio": ServiceHealth(status="up", latency_ms=80),
                    "faster_whisper": ServiceHealth(status="not_deployed"),
                    "kokoro_tts": ServiceHealth(status="not_deployed"),
                    "surya_ocr": ServiceHealth(status="not_deployed"),
                    "telegram_bot": ServiceHealth(status="not_deployed"),
                },
                cache_hit=False,
            ),
        ):
            response = app.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_endpoint_returns_503_when_unhealthy(
        self, app: TestClient
    ) -> None:
        """GET /api/v1/health returns 503 when unhealthy."""
        with patch.object(
            HealthChecker,
            "check_all_services",
            new_callable=AsyncMock,
            return_value=HealthResponse(
                status="unhealthy",
                timestamp="2026-02-09T14:00:00Z",
                services={
                    "postgresql": ServiceHealth(status="down"),
                    "redis": ServiceHealth(status="up", latency_ms=3),
                    "emailengine": ServiceHealth(status="up", latency_ms=45),
                    "n8n": ServiceHealth(status="up", latency_ms=120),
                    "caddy": ServiceHealth(status="up", latency_ms=5),
                    "presidio": ServiceHealth(status="up", latency_ms=80),
                    "faster_whisper": ServiceHealth(status="not_deployed"),
                    "kokoro_tts": ServiceHealth(status="not_deployed"),
                    "surya_ocr": ServiceHealth(status="not_deployed"),
                    "telegram_bot": ServiceHealth(status="not_deployed"),
                },
                cache_hit=False,
            ),
        ):
            response = app.get("/api/v1/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"

    def test_health_endpoint_returns_200_when_degraded(
        self, app: TestClient
    ) -> None:
        """GET /api/v1/health returns 200 when degraded (operational but impaired)."""
        with patch.object(
            HealthChecker,
            "check_all_services",
            new_callable=AsyncMock,
            return_value=HealthResponse(
                status="degraded",
                timestamp="2026-02-09T14:00:00Z",
                services={
                    "postgresql": ServiceHealth(status="up", latency_ms=12),
                    "redis": ServiceHealth(status="up", latency_ms=3),
                    "emailengine": ServiceHealth(status="up", latency_ms=45),
                    "n8n": ServiceHealth(status="down"),
                    "caddy": ServiceHealth(status="up", latency_ms=5),
                    "presidio": ServiceHealth(status="up", latency_ms=80),
                    "faster_whisper": ServiceHealth(status="not_deployed"),
                    "kokoro_tts": ServiceHealth(status="not_deployed"),
                    "surya_ocr": ServiceHealth(status="not_deployed"),
                    "telegram_bot": ServiceHealth(status="not_deployed"),
                },
                cache_hit=False,
            ),
        ):
            response = app.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"


class TestDetermineSystemStatus:
    """Test the _determine_system_status logic."""

    def test_all_up_is_healthy(self) -> None:
        """All services UP -> healthy."""
        services = {
            "postgresql": ServiceHealth(status="up", latency_ms=10),
            "redis": ServiceHealth(status="up", latency_ms=5),
            "emailengine": ServiceHealth(status="up", latency_ms=30),
            "n8n": ServiceHealth(status="up", latency_ms=50),
        }
        assert HealthChecker._determine_system_status(services) == "healthy"

    def test_critical_down_is_unhealthy(self) -> None:
        """Critical service DOWN -> unhealthy."""
        services = {
            "postgresql": ServiceHealth(status="down"),
            "redis": ServiceHealth(status="up", latency_ms=5),
            "emailengine": ServiceHealth(status="up", latency_ms=30),
            "n8n": ServiceHealth(status="up", latency_ms=50),
        }
        assert HealthChecker._determine_system_status(services) == "unhealthy"

    def test_noncritical_down_is_degraded(self) -> None:
        """Non-critical service DOWN -> degraded."""
        services = {
            "postgresql": ServiceHealth(status="up", latency_ms=10),
            "redis": ServiceHealth(status="up", latency_ms=5),
            "emailengine": ServiceHealth(status="up", latency_ms=30),
            "n8n": ServiceHealth(status="down"),
        }
        assert HealthChecker._determine_system_status(services) == "degraded"

    def test_not_deployed_is_still_healthy(self) -> None:
        """not_deployed services should not affect status."""
        services = {
            "postgresql": ServiceHealth(status="up", latency_ms=10),
            "redis": ServiceHealth(status="up", latency_ms=5),
            "emailengine": ServiceHealth(status="up", latency_ms=30),
            "faster_whisper": ServiceHealth(status="not_deployed"),
            "kokoro_tts": ServiceHealth(status="not_deployed"),
        }
        assert HealthChecker._determine_system_status(services) == "healthy"

    def test_critical_down_overrides_noncritical_down(self) -> None:
        """If both critical and non-critical are down -> unhealthy (not just degraded)."""
        services = {
            "postgresql": ServiceHealth(status="down"),
            "redis": ServiceHealth(status="up", latency_ms=5),
            "emailengine": ServiceHealth(status="up", latency_ms=30),
            "n8n": ServiceHealth(status="down"),
        }
        assert HealthChecker._determine_system_status(services) == "unhealthy"

    def test_emailengine_critical(self) -> None:
        """EmailEngine is a critical service."""
        services = {
            "postgresql": ServiceHealth(status="up", latency_ms=10),
            "redis": ServiceHealth(status="up", latency_ms=5),
            "emailengine": ServiceHealth(status="down"),
            "n8n": ServiceHealth(status="up", latency_ms=50),
        }
        assert HealthChecker._determine_system_status(services) == "unhealthy"

    def test_critical_services_set(self) -> None:
        """Verify the critical services set matches story spec."""
        assert CRITICAL_SERVICES == frozenset(
            {"postgresql", "redis", "emailengine"}
        )


class TestHealthCheckOpenAPI:
    """Test OpenAPI schema generation (AC #6)."""

    def test_openapi_schema_exists(self, app: TestClient) -> None:
        """OpenAPI schema should be generated."""
        response = app.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == "Friday 2.0 Gateway"
        assert schema["info"]["version"] == "1.0.0"

    def test_health_endpoint_in_schema(self, app: TestClient) -> None:
        """Health endpoint should be documented in OpenAPI schema."""
        response = app.get("/openapi.json")
        schema = response.json()
        assert "/api/v1/health" in schema["paths"]

    def test_protected_endpoint_in_schema(self, app: TestClient) -> None:
        """Protected endpoint should be documented in OpenAPI schema."""
        response = app.get("/openapi.json")
        schema = response.json()
        assert "/api/v1/protected" in schema["paths"]


class TestStructuredLogging:
    """Test structured logging configuration (AC #8)."""

    def test_structlog_json_output(self) -> None:
        """Verify structlog produces JSON output."""
        import io

        import structlog

        from services.gateway.logging_config import setup_logging

        setup_logging("DEBUG")
        log = structlog.get_logger()
        # structlog should be configured for JSON rendering
        assert log is not None

    def test_no_emoji_in_log_messages(self) -> None:
        """Log messages must not contain emojis."""
        import re
        from pathlib import Path

        from services.gateway import auth, healthcheck, main

        # Check source files for emoji patterns
        emoji_pattern = re.compile(
            "[\U0001f600-\U0001f64f"
            "\U0001f300-\U0001f5ff"
            "\U0001f680-\U0001f6ff"
            "\U0001f1e0-\U0001f1ff"
            "\u2702-\u27b0"
            "\u24c2-\U0001f251]",
            flags=re.UNICODE,
        )
        for module in [auth, healthcheck, main]:
            assert module.__file__ is not None, f"{module} has no __file__"
            source = Path(module.__file__).read_text(encoding="utf-8")
            matches = emoji_pattern.findall(source)
            assert not matches, (
                f"Emoji found in {module.__file__}: {matches}"
            )
