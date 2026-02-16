"""
Friday 2.0 - FastAPI Gateway main application.

Entry point for the API gateway. Manages lifespan (startup/shutdown),
CORS, structured logging, and routes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from .auth import get_current_user
from .config import GatewaySettings, get_settings
from .healthcheck import HealthChecker
from .logging_config import setup_logging
from .routes import heartbeat, webhooks
from .schemas import AuthUser, HealthResponse

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown."""
    settings = get_settings()
    setup_logging(settings.log_level)

    logger.info("gateway_starting", environment=settings.environment)

    # Warn if API_TOKEN is not configured
    if not settings.api_token:
        logger.warning("api_token_not_configured_all_protected_routes_will_return_500")

    # Initialize PostgreSQL pool
    pg_pool = None
    if settings.postgres_dsn:
        try:
            pg_pool = await asyncpg.create_pool(
                dsn=settings.postgres_dsn,
                min_size=2,
                max_size=10,
            )
            logger.info("postgresql_pool_created")
        except Exception as exc:
            logger.error("postgresql_pool_creation_failed", error=str(exc))

    # Initialize Redis
    redis_client = None
    if settings.redis_url:
        try:
            redis_client = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
            await redis_client.ping()
            logger.info("redis_connected")
        except Exception as exc:
            logger.error("redis_connection_failed", error=str(exc))
            redis_client = None

    # Initialize HealthChecker
    health_checker = HealthChecker(
        pg_pool=pg_pool,
        redis=redis_client,
        cache_ttl=settings.healthcheck_cache_ttl,
    )

    # Store in app state
    app.state.pg_pool = pg_pool
    app.state.redis = redis_client
    app.state.health_checker = health_checker

    logger.info("gateway_started")

    yield

    # Shutdown
    logger.info("gateway_stopping")
    await health_checker.close()
    if pg_pool is not None:
        await pg_pool.close()
    if redis_client is not None:
        await redis_client.close()
    logger.info("gateway_stopped")


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    """Factory to create the FastAPI application."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Friday 2.0 Gateway",
        description="API Gateway pour Friday 2.0 - Second Cerveau Personnel",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS middleware (restrictive in production, permissive in dev)
    allow_methods = ["GET", "POST", "PUT", "DELETE"]
    allow_headers = ["Authorization", "Content-Type"]
    if settings.environment == "development":
        allow_methods = ["*"]
        allow_headers = ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
    )

    # --- Routes ---

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        summary="Extended healthcheck",
        description=(
            "Check health of 10 services. "
            "Returns healthy/degraded/unhealthy with per-service details."
        ),
    )
    async def health_check(request: Request) -> JSONResponse:
        """
        Healthcheck endpoint monitoring 10 services.

        States:
        - healthy: all critical services UP
        - degraded: at least one non-critical service DOWN
        - unhealthy: at least one critical service DOWN

        Cache: 5 seconds TTL via Redis.
        """
        health_checker: HealthChecker = request.app.state.health_checker
        result = await health_checker.check_all_services()

        status_code = 200
        if result.status == "unhealthy":
            status_code = 503

        return JSONResponse(content=result.model_dump(), status_code=status_code)

    @app.get(
        "/api/v1/protected",
        response_model=AuthUser,
        summary="Protected route example",
        description="Requires valid bearer token in Authorization header.",
    )
    async def protected_route(
        current_user: dict[str, str] = Depends(get_current_user),
    ) -> dict[str, str]:
        """Protected route requiring bearer token authentication."""
        return {"username": current_user["username"]}

    # Include routers
    app.include_router(webhooks.router)  # Story 2.1
    app.include_router(heartbeat.router)  # Story 4.1

    return app


# Create default app instance for uvicorn
app = create_app()
