"""
Friday 2.0 - Gateway Pydantic schemas.

API response models for healthcheck and auth endpoints.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ServiceStatusType = Literal["up", "down", "not_deployed"]
SystemStatusType = Literal["healthy", "degraded", "unhealthy"]


class ServiceHealth(BaseModel):
    """Health status of a single service."""

    status: ServiceStatusType
    latency_ms: int | None = None


class HealthResponse(BaseModel):
    """Response model for GET /api/v1/health."""

    status: SystemStatusType
    timestamp: str
    services: dict[str, ServiceHealth]
    cache_hit: bool = False


class AuthUser(BaseModel):
    """Authenticated user info."""

    username: str


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
