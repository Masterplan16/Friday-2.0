"""
Configuration pytest pour tests agents/email.

Initialise TrustManager pour tests unitaires nécessitant @friday_action.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from agents.src.middleware.trust import init_trust_manager


class MockAsyncPool:
    """Mock d'un pool asyncpg pour tests unitaires."""

    def __init__(self):
        self.mock_conn = AsyncMock()
        self.mock_conn.fetch.return_value = []  # Empty correction rules
        self.mock_conn.fetchval.return_value = None
        self.mock_conn.execute.return_value = None

    @asynccontextmanager
    async def acquire(self):
        """Context manager async pour acquire()."""
        yield self.mock_conn

    async def fetchval(self, query, *args):
        """Mock fetchval direct sur pool."""
        return "auto"


@pytest.fixture(scope="session", autouse=True)
def initialize_trust_manager():
    """
    Initialise TrustManager en mode mock pour tests unitaires.

    Nécessaire pour les fonctions utilisant @friday_action decorator.
    """
    # Créer mock pool avec vrai async context manager
    mock_pool = MockAsyncPool()

    # Initialiser TrustManager avec mock pool (synchrone)
    init_trust_manager(db_pool=mock_pool)

    yield

    # Cleanup si nécessaire
    # (TrustManager n'a pas de méthode close pour l'instant)
