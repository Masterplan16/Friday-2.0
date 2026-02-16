"""
Test de la migration 012 - ingestion.emails_legacy

Vérifie que la table est créée correctement avec toutes les contraintes.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import pytest


@pytest.fixture
async def db_connection():
    """Connexion PostgreSQL pour tests d'intégration"""
    # Connection string depuis env ou défaut test
    # Port 5433 car 5432 déjà utilisé (docker-compose.yml ligne 37)
    db_url = os.getenv(
        "DATABASE_URL", "postgresql://friday:friday_test_local_dev_123@localhost:5433/friday"
    )

    conn = await asyncpg.connect(db_url)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_012_table_exists(db_connection):
    """Vérifie que la table ingestion.emails_legacy existe"""
    result = await db_connection.fetchval(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_schema = 'ingestion'
            AND table_name = 'emails_legacy'
        )
        """
    )
    assert result is True, "Table ingestion.emails_legacy n'existe pas"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_012_columns_exist(db_connection):
    """Vérifie que toutes les colonnes requises existent"""
    required_columns = {
        "message_id",
        "account",
        "sender",
        "recipients",
        "subject",
        "body_text",
        "body_html",
        "received_at",
        "has_attachments",
        "attachment_count",
        "imported_at",
        "import_batch_id",
        "import_source",
    }

    result = await db_connection.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ingestion'
        AND table_name = 'emails_legacy'
        """
    )

    existing_columns = {row["column_name"] for row in result}

    missing = required_columns - existing_columns
    assert not missing, f"Colonnes manquantes: {missing}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_012_primary_key(db_connection):
    """Vérifie que message_id est la PRIMARY KEY"""
    result = await db_connection.fetchval(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_schema = 'ingestion'
            AND tc.table_name = 'emails_legacy'
            AND tc.constraint_type = 'PRIMARY KEY'
            AND kcu.column_name = 'message_id'
        )
        """
    )
    assert result is True, "PRIMARY KEY sur message_id manquante"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_012_indexes_exist(db_connection):
    """Vérifie que les indexes sont créés"""
    expected_indexes = {
        "idx_emails_legacy_received",
        "idx_emails_legacy_account",
        "idx_emails_legacy_import_batch",
        "idx_emails_legacy_has_attachments",
    }

    result = await db_connection.fetch(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'ingestion'
        AND tablename = 'emails_legacy'
        """
    )

    existing_indexes = {row["indexname"] for row in result}

    # Exclude automatic PK index
    existing_indexes = {idx for idx in existing_indexes if not idx.endswith("_pkey")}

    missing = expected_indexes - existing_indexes
    assert not missing, f"Indexes manquants: {missing}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_012_insert_10_test_emails(db_connection):
    """Insert 10 emails test et vérifie les contraintes"""

    # Nettoyer d'abord (au cas où)
    await db_connection.execute(
        "DELETE FROM ingestion.emails_legacy WHERE import_source = 'pytest'"
    )

    # Créer 10 emails test
    test_emails = []
    batch_id = uuid4()

    for i in range(10):
        test_emails.append(
            (
                f"<test-{i}-{uuid4()}@example.com>",  # message_id unique
                f"test{i}@cabinet.fr",  # account
                f"sender{i}@example.com",  # sender
                [f"recipient{i}@example.com", f"cc{i}@example.com"],  # recipients
                f"Test Email #{i}",  # subject
                f"Ceci est le contenu texte de l'email test #{i}",  # body_text
                f"<p>Ceci est le contenu HTML de l'email test #{i}</p>",  # body_html
                datetime(2024, 1, i + 1, 10, 30, tzinfo=timezone.utc),  # received_at
                i % 2 == 0,  # has_attachments (alternance)
                i % 3,  # attachment_count
                batch_id,  # import_batch_id
                "pytest",  # import_source
            )
        )

    # INSERT batch
    inserted = await db_connection.executemany(
        """
        INSERT INTO ingestion.emails_legacy (
            message_id, account, sender, recipients,
            subject, body_text, body_html, received_at,
            has_attachments, attachment_count,
            import_batch_id, import_source
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """,
        test_emails,
    )

    # Vérifier 10 rows insérées
    count = await db_connection.fetchval(
        "SELECT COUNT(*) FROM ingestion.emails_legacy WHERE import_source = 'pytest'"
    )
    assert count == 10, f"Attendu 10 emails insérés, trouvé {count}"

    # Vérifier que imported_at est auto-rempli
    result = await db_connection.fetchrow(
        """
        SELECT imported_at
        FROM ingestion.emails_legacy
        WHERE import_source = 'pytest'
        LIMIT 1
        """
    )
    assert result["imported_at"] is not None, "imported_at devrait être auto-rempli"

    # Vérifier recipients array fonctionne
    result = await db_connection.fetchrow(
        """
        SELECT recipients
        FROM ingestion.emails_legacy
        WHERE import_source = 'pytest'
        ORDER BY message_id
        LIMIT 1
        """
    )
    assert isinstance(result["recipients"], list), "recipients devrait être un array"
    assert len(result["recipients"]) == 2, "recipients devrait contenir 2 éléments"

    # Cleanup
    await db_connection.execute(
        "DELETE FROM ingestion.emails_legacy WHERE import_source = 'pytest'"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_012_pk_constraint_uniqueness(db_connection):
    """Vérifie que la PRIMARY KEY message_id empêche les doublons"""

    # Nettoyer
    await db_connection.execute(
        "DELETE FROM ingestion.emails_legacy WHERE import_source = 'pytest_pk'"
    )

    # Insérer un email
    message_id = f"<test-pk-{uuid4()}@example.com>"
    await db_connection.execute(
        """
        INSERT INTO ingestion.emails_legacy (
            message_id, account, received_at, import_source
        ) VALUES ($1, 'test@example.com', NOW(), 'pytest_pk')
        """,
        message_id,
    )

    # Tenter d'insérer le même message_id → devrait échouer
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await db_connection.execute(
            """
            INSERT INTO ingestion.emails_legacy (
                message_id, account, received_at, import_source
            ) VALUES ($1, 'test2@example.com', NOW(), 'pytest_pk')
            """,
            message_id,
        )

    # Cleanup
    await db_connection.execute(
        "DELETE FROM ingestion.emails_legacy WHERE import_source = 'pytest_pk'"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_012_index_performance(db_connection):
    """Vérifie que les indexes améliorent les queries (EXPLAIN ANALYZE)"""

    # Query qui devrait utiliser idx_emails_legacy_received
    result = await db_connection.fetchval(
        """
        EXPLAIN (FORMAT JSON)
        SELECT * FROM ingestion.emails_legacy
        ORDER BY received_at DESC
        LIMIT 10
        """
    )

    # Parser le JSON retourné par PostgreSQL
    plan_json = json.loads(result) if isinstance(result, str) else result
    plan = plan_json[0]["Plan"]
    # Vérifier qu'un scan est utilisé quelque part dans le plan
    # (peut être dans Node Type racine ou dans Plans enfants)
    plan_str = str(plan)
    assert "Scan" in plan_str, "Query plan devrait inclure un scan (Seq Scan, Index Scan, etc.)"

    # Query qui devrait utiliser idx_emails_legacy_account
    result = await db_connection.fetchval(
        """
        EXPLAIN (FORMAT JSON)
        SELECT * FROM ingestion.emails_legacy
        WHERE account = 'test@example.com'
        """
    )

    # Parser le JSON retourné par PostgreSQL
    plan_json = json.loads(result) if isinstance(result, str) else result
    plan = plan_json[0]["Plan"]
    plan_str = str(plan)
    assert "Scan" in plan_str, "Query plan devrait inclure un scan (Seq Scan, Index Scan, etc.)"


if __name__ == "__main__":
    # Run tests avec pytest
    pytest.main([__file__, "-v", "-m", "integration"])
