"""
Friday 2.0 - Extended healthcheck for 10 services.

3 states: healthy, degraded, unhealthy.
Cache via Redis with configurable TTL.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import asyncpg
import httpx
import structlog
from redis.asyncio import Redis

from .schemas import HealthResponse, ServiceHealth, ServiceStatusType, SystemStatusType

logger = structlog.get_logger()

CRITICAL_SERVICES: frozenset[str] = frozenset({"postgresql", "redis"})

# Service check configuration: name -> (check_type, url_or_config)
# D25: emailengine retiré, remplacé par imap-fetcher (healthcheck fichier, pas HTTP)
SERVICE_CHECKS: dict[str, dict[str, str]] = {
    "n8n": {"type": "http", "url": "http://n8n:5678/healthz"},
    "caddy": {"type": "http", "url": "http://caddy:80/health"},
    "presidio_analyzer": {"type": "http", "url": "http://presidio-analyzer:3000/health"},
    "presidio_anonymizer": {"type": "http", "url": "http://presidio-anonymizer:3000/health"},
    "faster_whisper": {"type": "http", "url": "http://faster-whisper:8001/health"},
    "kokoro_tts": {"type": "http", "url": "http://kokoro-tts:8002/health"},
    "surya_ocr": {"type": "http", "url": "http://surya-ocr:8003/health"},
    "telegram_bot": {"type": "http", "url": "http://telegram-bot:8080/health"},
}

CACHE_KEY = "healthcheck:cache"


class HealthChecker:
    """Checks health of all Friday 2.0 services."""

    def __init__(
        self,
        pg_pool: asyncpg.Pool | None = None,
        redis: Redis | None = None,  # type: ignore[type-arg]
        cache_ttl: int = 5,
    ) -> None:
        self.pg_pool = pg_pool
        self.redis = redis
        self.cache_ttl = cache_ttl
        self._http_client: httpx.AsyncClient | None = None

    async def check_postgresql(self) -> tuple[ServiceStatusType, int | None]:
        """Check PostgreSQL connectivity and measure latency."""
        if self.pg_pool is None:
            return ("down", None)
        start = time.monotonic()
        try:
            async with self.pg_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            latency_ms = int((time.monotonic() - start) * 1000)
            return ("up", latency_ms)
        except Exception as exc:
            logger.error("postgresql_check_failed", error=str(exc))
            return ("down", None)

    async def check_redis(self) -> tuple[ServiceStatusType, int | None]:
        """Check Redis connectivity and measure latency."""
        if self.redis is None:
            return ("down", None)
        start = time.monotonic()
        try:
            await self.redis.ping()
            latency_ms = int((time.monotonic() - start) * 1000)
            return ("up", latency_ms)
        except Exception as exc:
            logger.error("redis_check_failed", error=str(exc))
            return ("down", None)

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Return a reusable HTTP client (lazy-initialized)."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=2.0)
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    async def check_http_service(self, name: str, url: str) -> tuple[ServiceStatusType, int | None]:
        """Check an HTTP service health endpoint."""
        start = time.monotonic()
        try:
            client = await self._get_http_client()
            response = await client.get(url)
            response.raise_for_status()
            latency_ms = int((time.monotonic() - start) * 1000)
            return ("up", latency_ms)
        except httpx.ConnectError:
            # Connection refused = service not deployed or not reachable
            return ("not_deployed", None)
        except httpx.HTTPStatusError:
            return ("down", None)
        except Exception as exc:
            logger.warning("http_check_failed", service=name, error=str(exc))
            return ("not_deployed", None)

    async def _get_cached_result(self) -> dict[str, Any] | None:
        """Try to get cached healthcheck result from Redis."""
        if self.redis is None:
            return None
        try:
            cached = await self.redis.get(CACHE_KEY)
            if cached:
                result: dict[str, Any] = json.loads(cached)
                result["cache_hit"] = True
                return result
        except Exception as exc:
            logger.warning("healthcheck_cache_read_failed", error=str(exc))
        return None

    async def _cache_result(self, result: dict[str, Any]) -> None:
        """Cache healthcheck result in Redis."""
        if self.redis is None:
            return
        try:
            await self.redis.setex(CACHE_KEY, self.cache_ttl, json.dumps(result))
        except Exception as exc:
            logger.warning("healthcheck_cache_write_failed", error=str(exc))

    async def check_all_services(self) -> HealthResponse:
        """Check all services in parallel with caching."""
        # Check cache first
        cached = await self._get_cached_result()
        if cached is not None:
            return HealthResponse(**cached)

        # Run all checks in parallel
        pg_task = asyncio.create_task(self.check_postgresql())
        redis_task = asyncio.create_task(self.check_redis())

        http_tasks: dict[str, asyncio.Task[tuple[ServiceStatusType, int | None]]] = {}
        for name, config in SERVICE_CHECKS.items():
            http_tasks[name] = asyncio.create_task(self.check_http_service(name, config["url"]))

        # Gather results
        pg_status, pg_latency = await pg_task
        redis_status, redis_latency = await redis_task

        services: dict[str, ServiceHealth] = {
            "postgresql": ServiceHealth(status=pg_status, latency_ms=pg_latency),
            "redis": ServiceHealth(status=redis_status, latency_ms=redis_latency),
        }

        for name, task in http_tasks.items():
            try:
                svc_status, svc_latency = await task
                services[name] = ServiceHealth(status=svc_status, latency_ms=svc_latency)
            except Exception:
                services[name] = ServiceHealth(status="down")

        # Determine system status
        system_status = self._determine_system_status(services)
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        response = HealthResponse(
            status=system_status,
            timestamp=timestamp,
            services=services,
            cache_hit=False,
        )

        # Cache the result
        await self._cache_result(response.model_dump())

        return response

    @staticmethod
    def _determine_system_status(
        services: dict[str, ServiceHealth],
    ) -> SystemStatusType:
        """Determine overall system status from individual service statuses."""
        # Any critical service DOWN -> unhealthy
        for name in CRITICAL_SERVICES:
            svc = services.get(name)
            if svc is not None and svc.status == "down":
                return "unhealthy"

        # Any non-critical service DOWN (not "not_deployed") -> degraded
        for name, svc in services.items():
            if name not in CRITICAL_SERVICES and svc.status == "down":
                return "degraded"

        # All OK (or not_deployed) -> healthy
        return "healthy"
