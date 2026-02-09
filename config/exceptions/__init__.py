"""
Friday 2.0 - Canonical exception hierarchy.

Source of truth for all Friday 2.0 exceptions.
Services running in isolated Docker containers may define local copies
(e.g. services/gateway/exceptions.py) to avoid cross-container imports.
"""


class FridayError(Exception):
    """Base exception Friday 2.0."""


class PipelineError(FridayError):
    """Erreurs pipeline ingestion/traitement."""


class AgentError(FridayError):
    """Erreurs agents IA."""


class InsufficientRAMError(FridayError):
    """RAM insuffisante pour service lourd."""
