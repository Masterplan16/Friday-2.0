"""
Fixtures pytest partagées pour tests intégration Friday 2.0.

Ce fichier contient les fixtures pour :
- PostgreSQL : Connexion DB réelle pour tests d'intégration
- Redis : Connexion Redis pour tests événements

Note : L'event loop est géré automatiquement par pytest-asyncio en mode auto.
Voir pytest.ini pour la configuration.
"""

import os
from typing import AsyncGenerator

import asyncpg
import pytest


# ==========================================
# PostgreSQL Fixtures
# ==========================================


@pytest.fixture(scope="session")
async def db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    """
    Fixture PostgreSQL Pool pour tests d'intégration.

    Utilise les variables d'environnement :
    - POSTGRES_HOST (default: localhost)
    - POSTGRES_PORT (default: 5432)
    - POSTGRES_DB (default: friday_test)
    - POSTGRES_USER (default: friday)
    - POSTGRES_PASSWORD (default: friday_test)

    IMPORTANT : La base de données doit exister et avoir les migrations appliquées.
    """
    pool = await asyncpg.create_pool(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "friday_test"),
        user=os.getenv("POSTGRES_USER", "friday"),
        password=os.getenv("POSTGRES_PASSWORD", "friday_test"),
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
    """
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE core.action_receipts CASCADE")
        await conn.execute("TRUNCATE TABLE core.correction_rules CASCADE")
        await conn.execute("TRUNCATE TABLE core.trust_metrics CASCADE")

    yield

    # Cleanup après test
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE core.action_receipts CASCADE")
        await conn.execute("TRUNCATE TABLE core.correction_rules CASCADE")
        await conn.execute("TRUNCATE TABLE core.trust_metrics CASCADE")
