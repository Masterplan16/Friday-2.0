"""
Friday 2.0 - Gateway exception hierarchy.

Local copy of FridayError for Docker container isolation.
Canonical source: config/exceptions/__init__.py
"""


class FridayError(Exception):
    """Base exception for Friday 2.0."""


class GatewayError(FridayError):
    """Errors specific to the FastAPI Gateway."""


class HealthCheckError(GatewayError):
    """Errors during health check operations."""


class AuthenticationError(GatewayError):
    """Authentication failures."""
