"""
Tests d'intégration pour migration 026_cold_start_tracking.sql

Vérifie la création de la table core.cold_start_tracking avec seed initial.
Nécessite DATABASE_URL configurée et migration 026 appliquée.
"""

import asyncpg
import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_026_creates_cold_start_tracking_table(db_pool):
    """
    Vérifie que la table core.cold_start_tracking existe avec la structure attendue.
    """
    async with db_pool.acquire() as conn:
        # Vérifier existence table
        table_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'core'
                AND table_name = 'cold_start_tracking'
            )
            """
        )
        assert table_exists, "Table core.cold_start_tracking n'existe pas"

        # Vérifier colonnes
        columns = await conn.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'core'
            AND table_name = 'cold_start_tracking'
            ORDER BY ordinal_position
            """
        )

        column_names = [col["column_name"] for col in columns]
        expected_columns = [
            "module",
            "action_type",
            "phase",
            "emails_processed",
            "accuracy",
        ]

        assert column_names == expected_columns, (
            f"Colonnes incorrectes. Attendues: {expected_columns}, " f"Obtenues: {column_names}"
        )

        # Vérifier types
        column_types = {col["column_name"]: col["data_type"] for col in columns}
        assert column_types["module"] == "character varying"
        assert column_types["action_type"] == "character varying"
        assert column_types["phase"] == "character varying"
        assert column_types["emails_processed"] == "integer"
        assert column_types["accuracy"] in ("double precision", "numeric")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_026_creates_primary_key(db_pool):
    """
    Vérifie que la clé primaire (module, action_type) existe.
    """
    async with db_pool.acquire() as conn:
        pk_constraint = await conn.fetchrow(
            """
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_schema = 'core'
            AND table_name = 'cold_start_tracking'
            AND constraint_type = 'PRIMARY KEY'
            """
        )

        assert pk_constraint is not None, "Clé primaire manquante"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_026_creates_index(db_pool):
    """
    Vérifie que l'index sur (module, action_type) existe.
    """
    async with db_pool.acquire() as conn:
        index_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = 'core'
                AND tablename = 'cold_start_tracking'
                AND indexname = 'idx_cold_start_module_action'
            )
            """
        )

        assert index_exists, "Index idx_cold_start_module_action manquant"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_026_seeds_email_classify(db_pool):
    """
    Vérifie que le seed initial pour email.classify existe en phase cold_start.
    """
    async with db_pool.acquire() as conn:
        seed_row = await conn.fetchrow(
            """
            SELECT module, action_type, phase, emails_processed, accuracy
            FROM core.cold_start_tracking
            WHERE module = 'email' AND action_type = 'classify'
            """
        )

        assert seed_row is not None, "Seed email.classify manquant"
        assert seed_row["phase"] == "cold_start"
        assert seed_row["emails_processed"] == 0
        assert seed_row["accuracy"] is None or seed_row["accuracy"] == 0.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_026_phase_values_valid(db_pool):
    """
    Vérifie que seules les valeurs de phase valides sont acceptées.
    """
    async with db_pool.acquire() as conn:
        # Tenter d'insérer phase invalide devrait échouer
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO core.cold_start_tracking
                (module, action_type, phase, emails_processed)
                VALUES ('test', 'test_action', 'invalid_phase', 0)
                """
            )

        # Phases valides devraient réussir
        valid_phases = ["cold_start", "calibrated", "production"]

        for phase in valid_phases:
            await conn.execute(
                """
                INSERT INTO core.cold_start_tracking
                (module, action_type, phase, emails_processed)
                VALUES ($1, $2, $3, 0)
                ON CONFLICT (module, action_type) DO UPDATE
                SET phase = EXCLUDED.phase
                """,
                f"test_module_{phase}",
                "test_action",
                phase,
            )

            # Vérifier insertion
            result = await conn.fetchval(
                """
                SELECT phase FROM core.cold_start_tracking
                WHERE module = $1 AND action_type = 'test_action'
                """,
                f"test_module_{phase}",
            )
            assert result == phase

        # Cleanup test data
        await conn.execute(
            """
            DELETE FROM core.cold_start_tracking
            WHERE module LIKE 'test_module_%'
            """
        )
