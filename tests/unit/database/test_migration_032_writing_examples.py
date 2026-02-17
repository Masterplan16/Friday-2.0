"""
Tests unitaires pour migration 032 - core.writing_examples table

Tests la création de la table writing_examples pour le stockage des exemples
de style rédactionnel (few-shot learning).

Story: 2.5 Brouillon Réponse Email
"""

import pytest

pytestmark = pytest.mark.skip(
    reason="Nécessite une connexion PostgreSQL réelle - test d'intégration"
)

import asyncio
from datetime import datetime

import asyncpg
import pytest


@pytest.fixture
async def db_pool():
    """Fixture pour connexion PostgreSQL test"""
    pool = await asyncpg.create_pool(
        host="localhost",
        port=5432,
        database="friday_test",
        user="postgres",
        password="postgres",
        min_size=1,
        max_size=5,
    )
    yield pool
    await pool.close()


@pytest.fixture
async def clean_writing_examples(db_pool):
    """Nettoyer la table writing_examples avant/après chaque test"""
    async with db_pool.acquire() as conn:
        # Avant test
        await conn.execute("TRUNCATE TABLE core.writing_examples CASCADE")

    yield

    # Après test
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE core.writing_examples CASCADE")


@pytest.mark.asyncio
async def test_migration_032_applies_without_error(db_pool):
    """
    Test 1: Migration 032 s'applique sans erreur

    Vérifie que la migration peut être exécutée sur une base propre
    """
    async with db_pool.acquire() as conn:
        # Vérifier que la table existe
        result = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'core'
                AND table_name = 'writing_examples'
            )
            """
        )
        assert result is True, "Table core.writing_examples devrait exister après migration 032"


@pytest.mark.asyncio
async def test_writing_examples_email_type_constraint(db_pool, clean_writing_examples):
    """
    Test 2: Contrainte CHECK sur email_type fonctionne

    Valeurs valides: professional, personal, medical, academic
    Valeurs invalides: spam, unknown, etc.
    """
    async with db_pool.acquire() as conn:
        # Test valeur valide : professional
        await conn.execute(
            """
            INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
            VALUES ('professional', 'Test Subject', 'Test Body', 'Mainteneur')
            """
        )

        # Test valeur valide : medical
        await conn.execute(
            """
            INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
            VALUES ('medical', 'Test Medical', 'Test Body Medical', 'Mainteneur')
            """
        )

        # Test valeur valide : academic
        await conn.execute(
            """
            INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
            VALUES ('academic', 'Test Academic', 'Test Body Academic', 'Mainteneur')
            """
        )

        # Test valeur valide : personal
        await conn.execute(
            """
            INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
            VALUES ('personal', 'Test Personal', 'Test Body Personal', 'Mainteneur')
            """
        )

        # Test valeur invalide : 'spam' devrait échouer
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
                VALUES ('spam', 'Test Spam', 'Test Body Spam', 'Mainteneur')
                """
            )

        # Test valeur invalide : 'unknown' devrait échouer
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
                VALUES ('unknown', 'Test Unknown', 'Test Body Unknown', 'Mainteneur')
                """
            )


@pytest.mark.asyncio
async def test_writing_examples_index_created(db_pool):
    """
    Test 3: Index idx_writing_examples_email_type_sent_by créé correctement

    Vérifie que l'index composite existe pour optimiser les queries
    ORDER BY created_at DESC
    """
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'core'
            AND tablename = 'writing_examples'
            AND indexname = 'idx_writing_examples_email_type_sent_by'
            """
        )

        assert result is not None, "Index idx_writing_examples_email_type_sent_by devrait exister"

        # Vérifier que l'index contient les bonnes colonnes
        indexdef = result["indexdef"].lower()
        assert "email_type" in indexdef, "Index devrait contenir email_type"
        assert "sent_by" in indexdef, "Index devrait contenir sent_by"
        assert "created_at" in indexdef, "Index devrait contenir created_at"


@pytest.mark.asyncio
async def test_writing_examples_updated_at_trigger(db_pool, clean_writing_examples):
    """
    Test 4: Trigger updated_at fonctionne correctement

    Vérifie que updated_at est automatiquement mis à jour lors d'un UPDATE
    """
    async with db_pool.acquire() as conn:
        # Insert exemple
        example_id = await conn.fetchval(
            """
            INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
            VALUES ('professional', 'Original Subject', 'Original Body', 'Mainteneur')
            RETURNING id
            """
        )

        # Récupérer created_at et updated_at initial
        row = await conn.fetchrow(
            "SELECT created_at, updated_at FROM core.writing_examples WHERE id = $1", example_id
        )
        created_at_original = row["created_at"]
        updated_at_original = row["updated_at"]

        # Vérifier que created_at == updated_at initialement
        assert (
            created_at_original == updated_at_original
        ), "created_at devrait égaler updated_at après INSERT"

        # Attendre 1 seconde pour différencier les timestamps
        await asyncio.sleep(1)

        # UPDATE l'exemple
        await conn.execute(
            """
            UPDATE core.writing_examples
            SET subject = 'Modified Subject'
            WHERE id = $1
            """,
            example_id,
        )

        # Récupérer updated_at après UPDATE
        updated_at_new = await conn.fetchval(
            "SELECT updated_at FROM core.writing_examples WHERE id = $1", example_id
        )

        # Vérifier que updated_at a changé
        assert (
            updated_at_new > updated_at_original
        ), "updated_at devrait être mis à jour automatiquement après UPDATE"

        # Vérifier que created_at n'a PAS changé
        created_at_new = await conn.fetchval(
            "SELECT created_at FROM core.writing_examples WHERE id = $1", example_id
        )
        assert (
            created_at_new == created_at_original
        ), "created_at ne devrait JAMAIS changer après INSERT"


@pytest.mark.asyncio
async def test_writing_examples_insert_succeeds(db_pool, clean_writing_examples):
    """
    Test 5: INSERT exemple réussit avec toutes les colonnes

    Vérifie que les valeurs par défaut fonctionnent (id UUID, created_at, sent_by)
    """
    async with db_pool.acquire() as conn:
        # Insert avec sent_by explicite
        example_id_1 = await conn.fetchval(
            """
            INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
            VALUES ('professional', 'Test Subject 1', 'Test Body 1', 'Mainteneur')
            RETURNING id
            """
        )

        assert example_id_1 is not None, "INSERT devrait retourner un UUID"

        # Vérifier que l'exemple a été inséré
        row = await conn.fetchrow("SELECT * FROM core.writing_examples WHERE id = $1", example_id_1)

        assert row is not None, "L'exemple devrait exister dans la table"
        assert row["email_type"] == "professional"
        assert row["subject"] == "Test Subject 1"
        assert row["body"] == "Test Body 1"
        assert row["sent_by"] == "Mainteneur"
        assert row["created_at"] is not None
        assert row["updated_at"] is not None
        assert isinstance(row["created_at"], datetime)

        # Insert avec sent_by par défaut (DEFAULT 'Mainteneur')
        example_id_2 = await conn.fetchval(
            """
            INSERT INTO core.writing_examples (email_type, subject, body)
            VALUES ('medical', 'Test Subject 2', 'Test Body 2')
            RETURNING id
            """
        )

        row2 = await conn.fetchrow(
            "SELECT sent_by FROM core.writing_examples WHERE id = $1", example_id_2
        )

        assert (
            row2["sent_by"] == "Mainteneur"
        ), "sent_by devrait avoir la valeur par défaut 'Mainteneur'"


@pytest.mark.asyncio
async def test_writing_examples_columns_not_null(db_pool, clean_writing_examples):
    """
    Test bonus: Contraintes NOT NULL fonctionnent
    """
    async with db_pool.acquire() as conn:
        # Test email_type NULL devrait échouer
        with pytest.raises(asyncpg.NotNullViolationError):
            await conn.execute(
                """
                INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
                VALUES (NULL, 'Subject', 'Body', 'Mainteneur')
                """
            )

        # Test subject NULL devrait échouer
        with pytest.raises(asyncpg.NotNullViolationError):
            await conn.execute(
                """
                INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
                VALUES ('professional', NULL, 'Body', 'Mainteneur')
                """
            )

        # Test body NULL devrait échouer
        with pytest.raises(asyncpg.NotNullViolationError):
            await conn.execute(
                """
                INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
                VALUES ('professional', 'Subject', NULL, 'Mainteneur')
                """
            )
