"""
Fixtures pytest partagées pour tests intégration Friday 2.0.

Ce fichier contient les fixtures pour :
- PostgreSQL : Connexion DB réelle pour tests d'intégration
- Redis : Connexion Redis pour tests événements

Note : L'event loop est géré automatiquement par pytest-asyncio en mode auto.
Voir pytest.ini pour la configuration.
"""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from agents.src.middleware.trust import init_trust_manager

# ==========================================
# PYTHONPATH Setup (Fix LOW-3 à LOW-6)
# ==========================================

# Add repo root to PYTHONPATH (une seule fois pour tous les tests)
# Remplace tous les sys.path.insert() dans les fichiers de tests individuels
repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


# ==========================================
# TrustManager Mock (shared across unit + e2e)
# ==========================================


class MockAsyncPool:
    """Mock d'un pool asyncpg pour tests nécessitant TrustManager."""

    def __init__(self):
        self.mock_conn = AsyncMock()
        self.mock_conn.fetch.return_value = []
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
    Initialise TrustManager en mode mock pour tous les tests.

    Nécessaire pour les fonctions utilisant @friday_action decorator.
    """
    mock_pool = MockAsyncPool()
    init_trust_manager(db_pool=mock_pool)
    yield


# ==========================================
# Mock Helpers for Unit Tests
# ==========================================


def create_mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    """
    Helper pour créer un mock asyncpg.Pool avec async context manager correctement configuré.

    Le pattern correct pour mocker pool.acquire() est :
    - pool.acquire() retourne un MagicMock (pas AsyncMock)
    - Ce MagicMock a __aenter__ et __aexit__ configurés comme AsyncMock
    - __aenter__ retourne la mock_conn

    Args:
        mock_conn: AsyncMock de la connexion asyncpg

    Returns:
        MagicMock pool correctement configuré pour pool.acquire()

    Usage:
        >>> mock_conn = AsyncMock()
        >>> mock_conn.fetch.return_value = [...]
        >>> mock_pool = create_mock_pool_with_conn(mock_conn)
        >>> async with mock_pool.acquire() as conn:
        ...     results = await conn.fetch(...)
    """
    mock_pool = MagicMock()
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire = MagicMock(return_value=acquire_ctx)
    return mock_pool


# ==========================================
# Integration Tests Guard
# ==========================================


@pytest.fixture(scope="session", autouse=True)
def skip_if_no_integration():
    """
    Garde pour tests d'intégration.

    Skip automatiquement tous les tests marqués @pytest.mark.integration
    si la variable d'environnement INTEGRATION_TESTS n'est pas définie.

    Usage:
        export INTEGRATION_TESTS=1
        pytest tests/integration -m integration
    """
    # Cette fixture est autouse=True, donc elle s'exécute pour tous les tests
    # Mais on ne skip que si le test est marqué "integration"
    pass


def pytest_collection_modifyitems(config, items):
    """
    Hook pytest pour modifier les tests collectés.

    Skip automatiquement les tests marqués "integration" si INTEGRATION_TESTS
    n'est pas défini dans l'environnement.
    """
    if not os.getenv("INTEGRATION_TESTS"):
        skip_integration = pytest.mark.skip(
            reason="INTEGRATION_TESTS=1 not set - skipping integration tests"
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


# ==========================================
# PostgreSQL Fixtures
# ==========================================


@pytest.fixture(scope="session")
async def db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    """
    Fixture PostgreSQL Pool pour tests d'intégration.

    Utilise DATABASE_URL en priorité, sinon variables d'environnement individuelles :
    - DATABASE_URL (ex: postgresql://user:pass@host:5432/db)
    - Ou POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

    IMPORTANT : La base de données doit exister et avoir les migrations appliquées.
    """
    database_url = os.getenv("DATABASE_URL")

    if database_url:
        # Utiliser DATABASE_URL si défini (prioritaire pour CI/CD)
        pool = await asyncpg.create_pool(dsn=database_url, min_size=2, max_size=5)
    else:
        # Fallback sur variables individuelles (dev local)
        pool = await asyncpg.create_pool(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "friday_test"),
            user=os.getenv("POSTGRES_USER", "friday_test"),
            password=os.getenv("POSTGRES_PASSWORD", "test_password"),
            min_size=2,
            max_size=5,
        )

    yield pool

    await pool.close()


@pytest.fixture
async def db_conn(db_pool: asyncpg.Pool) -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Fixture connexion PostgreSQL unique pour un test.

    Ouvre une transaction au début du test et rollback à la fin
    pour garantir l'isolation entre tests.
    """
    async with db_pool.acquire() as conn:
        # Démarrer transaction
        async with conn.transaction():
            yield conn
            # Rollback automatique à la sortie du context manager


@pytest.fixture
async def clean_tables(db_pool: asyncpg.Pool):
    """
    Fixture pour nettoyer les tables entre tests d'intégration.

    ATTENTION : Supprime TOUTES les données des tables testées.
    À utiliser uniquement sur base de test, jamais en production.

    Nettoie les 3 schemas : core, ingestion, knowledge
    """
    async with db_pool.acquire() as conn:
        # Core schema
        await conn.execute("TRUNCATE TABLE core.action_receipts CASCADE")
        await conn.execute("TRUNCATE TABLE core.correction_rules CASCADE")
        await conn.execute("TRUNCATE TABLE core.trust_metrics CASCADE")
        # Ingestion schema
        await conn.execute("TRUNCATE TABLE ingestion.emails CASCADE")
        await conn.execute("TRUNCATE TABLE ingestion.emails_legacy CASCADE")
        await conn.execute("TRUNCATE TABLE ingestion.documents CASCADE")
        await conn.execute("TRUNCATE TABLE ingestion.media CASCADE")
        # Knowledge schema
        await conn.execute("TRUNCATE TABLE knowledge.entities CASCADE")
        await conn.execute("TRUNCATE TABLE knowledge.embeddings CASCADE")
        await conn.execute("TRUNCATE TABLE knowledge.thesis_notes CASCADE")
        await conn.execute("TRUNCATE TABLE knowledge.finance_transactions CASCADE")

    yield

    # Cleanup après test
    async with db_pool.acquire() as conn:
        # Core schema
        await conn.execute("TRUNCATE TABLE core.action_receipts CASCADE")
        await conn.execute("TRUNCATE TABLE core.correction_rules CASCADE")
        await conn.execute("TRUNCATE TABLE core.trust_metrics CASCADE")
        # Ingestion schema
        await conn.execute("TRUNCATE TABLE ingestion.emails CASCADE")
        await conn.execute("TRUNCATE TABLE ingestion.emails_legacy CASCADE")
        await conn.execute("TRUNCATE TABLE ingestion.documents CASCADE")
        await conn.execute("TRUNCATE TABLE ingestion.media CASCADE")
        # Knowledge schema
        await conn.execute("TRUNCATE TABLE knowledge.entities CASCADE")
        await conn.execute("TRUNCATE TABLE knowledge.embeddings CASCADE")
        await conn.execute("TRUNCATE TABLE knowledge.thesis_notes CASCADE")
        await conn.execute("TRUNCATE TABLE knowledge.finance_transactions CASCADE")
