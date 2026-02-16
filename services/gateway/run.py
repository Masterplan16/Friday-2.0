"""
Gateway entry point for uvicorn.

This file exists to allow proper package imports when running via uvicorn.
When the container mounts ./services/gateway into /app, this directory IS the gateway package.
"""

# Direct import from current package (we ARE in the gateway package)
from main import app  # noqa: F401

__all__ = ["app"]
