"""Backward-compatible re-export of ContextProvider.

Story 7.2 originally defined ContextProvider here.
Story 4.1 defined the real ContextProvider in context_provider.py.
This module re-exports ContextProvider for backward compatibility.

Usage:
    from agents.src.core.context import ContextProvider  # backward-compat
    from agents.src.core.context_provider import ContextProvider  # preferred
"""

from agents.src.core.context_provider import ContextProvider  # noqa: F401

__all__ = ["ContextProvider"]
