"""
Tests unitaires pour migration 030 - ingestion.attachments.

Valide :
- Syntaxe SQL (BEGIN/COMMIT)
- Structure table attachments
- Indexes, foreign keys, check constraints
- Trigger updated_at
- Colonne has_attachments dans ingestion.emails
- Data integrity
"""

from pathlib import Path

import asyncpg
import pytest


@pytest.fixture
async def db_pool_clean(db_pool):
    """Fixture clean DB pour tests migration."""
    # Rollback migration 030 si existe
    async with db_pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS ingestion.attachments CASCADE")
        await conn.execute("ALTER TABLE ingestion.emails DROP COLUMN IF EXISTS has_attachments")

    yield db_pool

    # Cleanup après tests
    async with db_pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS ingestion.attachments CASCADE")
        await conn.execute("ALTER TABLE ingestion.emails DROP COLUMN IF EXISTS has_attachments")


class TestMigration030Syntax:
    """Tests syntaxe SQL migration 030."""

    def test_migration_file_exists(self):
        """Migration 030 existe dans database/migrations/."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        assert migration_file.exists(), "Migration 030_ingestion_attachments.sql manquante"

    def test_migration_has_begin_commit(self):
        """Migration contient BEGIN et COMMIT (transaction atomique)."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        content = migration_file.read_text()

        assert "BEGIN;" in content, "BEGIN manquant dans migration"
        assert "COMMIT;" in content, "COMMIT manquant dans migration"

    def test_migration_creates_attachments_table(self):
        """Migration crée table ingestion.attachments."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        content = migration_file.read_text()

        assert "CREATE TABLE" in content and "ingestion.attachments" in content
        assert "id UUID PRIMARY KEY" in content
        assert "email_id UUID" in content
        assert "filename TEXT" in content
        assert "filepath TEXT" in content
        assert "size_bytes INTEGER" in content
        assert "mime_type TEXT" in content
        assert "status TEXT" in content

    def test_migration_creates_indexes(self):
        """Migration crée indexes (email_id, status, processed_at)."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        content = migration_file.read_text()

        assert "CREATE INDEX" in content
        assert "idx_attachments_email_id" in content
        assert "idx_attachments_status" in content
        assert "idx_attachments_processed_at" in content

    def test_migration_has_foreign_key(self):
        """Migration définit FK email_id → ingestion.emails(id)."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        content = migration_file.read_text()

        assert "REFERENCES ingestion.emails" in content
        assert "ON DELETE CASCADE" in content

    def test_migration_has_check_constraints(self):
        """Migration définit CHECK constraints (size_bytes, status)."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        content = migration_file.read_text()

        # Size constraint (>0 AND <=25Mo)
        assert "CHECK" in content
        assert "size_bytes" in content

        # Status constraint (pending/processed/archived/error)
        assert "status IN" in content
        assert "'pending'" in content
        assert "'processed'" in content
        assert "'archived'" in content
        assert "'error'" in content

    def test_migration_creates_trigger_updated_at(self):
        """Migration crée trigger updated_at automatique."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        content = migration_file.read_text()

        assert "CREATE TRIGGER" in content
        assert "trg_attachments_updated_at" in content
        assert "update_updated_at" in content

    def test_migration_adds_has_attachments_column(self):
        """Migration ajoute colonne has_attachments dans ingestion.emails."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        content = migration_file.read_text()

        assert "ALTER TABLE ingestion.emails" in content
        assert "ADD COLUMN" in content
        assert "has_attachments BOOLEAN" in content
        assert "DEFAULT FALSE" in content


@pytest.mark.asyncio
class TestMigration030Execution:
    """Tests exécution migration 030 sur DB réelle."""

    async def test_apply_migration_success(self, db_pool_clean):
        """Migration 030 s'applique sans erreur."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            # Exécuter migration
            await conn.execute(sql)

            # Vérifier table créée
            table_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'ingestion' AND table_name = 'attachments'
                )
                """
            )
            assert table_exists is True, "Table ingestion.attachments non créée"

    async def test_attachments_table_columns(self, db_pool_clean):
        """Table attachments contient toutes les colonnes requises."""
        # Apply migration
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # Query colonnes table
            columns = await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'ingestion' AND table_name = 'attachments'
                ORDER BY ordinal_position
                """
            )

            column_names = [col["column_name"] for col in columns]

            # Vérifier colonnes requises
            assert "id" in column_names
            assert "email_id" in column_names
            assert "filename" in column_names
            assert "filepath" in column_names
            assert "size_bytes" in column_names
            assert "mime_type" in column_names
            assert "status" in column_names
            assert "extracted_at" in column_names
            assert "processed_at" in column_names
            assert "created_at" in column_names
            assert "updated_at" in column_names

    async def test_attachments_indexes_created(self, db_pool_clean):
        """Indexes attachments créés correctement."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # Query indexes
            indexes = await conn.fetch(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'ingestion' AND tablename = 'attachments'
                """
            )

            index_names = [idx["indexname"] for idx in indexes]

            assert "idx_attachments_email_id" in index_names
            assert "idx_attachments_status" in index_names
            assert "idx_attachments_processed_at" in index_names

    async def test_has_attachments_column_added(self, db_pool_clean):
        """Colonne has_attachments ajoutée dans ingestion.emails."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # Vérifier colonne existe
            column_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_schema = 'ingestion'
                    AND table_name = 'emails'
                    AND column_name = 'has_attachments'
                )
                """
            )

            assert column_exists is True, "Colonne has_attachments non ajoutée"


@pytest.mark.asyncio
class TestMigration030DataIntegrity:
    """Tests data integrity migration 030."""

    async def test_insert_attachment_with_valid_email(self, db_pool_clean):
        """INSERT attachment avec FK email valide réussit."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # Créer email test
            email_id = await conn.fetchval(
                """
                INSERT INTO ingestion.emails (raw_message, subject, sender)
                VALUES ('{}', 'Test', 'test@example.com')
                RETURNING id
                """
            )

            # INSERT attachment
            attachment_id = await conn.fetchval(
                """
                INSERT INTO ingestion.attachments
                (email_id, filename, filepath, size_bytes, mime_type, status)
                VALUES ($1, 'test.pdf', '/tmp/test.pdf', 150000, 'application/pdf', 'pending')
                RETURNING id
                """,
                email_id,
            )

            assert attachment_id is not None, "INSERT attachment failed"

    async def test_insert_attachment_invalid_email_fails(self, db_pool_clean):
        """INSERT attachment avec FK email invalide échoue."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # INSERT attachment avec email_id inexistant
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    """
                    INSERT INTO ingestion.attachments
                    (email_id, filename, filepath, size_bytes, mime_type, status)
                    VALUES ('00000000-0000-0000-0000-000000000000', 'test.pdf', '/tmp/test.pdf', 150000, 'application/pdf', 'pending')
                    """
                )

    async def test_check_constraint_size_bytes(self, db_pool_clean):
        """CHECK constraint size_bytes (>0 AND <=25Mo) enforce."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # Créer email test
            email_id = await conn.fetchval(
                """
                INSERT INTO ingestion.emails (raw_message, subject, sender)
                VALUES ('{}', 'Test', 'test@example.com')
                RETURNING id
                """
            )

            # Test size_bytes = 0 (invalide)
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """
                    INSERT INTO ingestion.attachments
                    (email_id, filename, filepath, size_bytes, mime_type, status)
                    VALUES ($1, 'test.pdf', '/tmp/test.pdf', 0, 'application/pdf', 'pending')
                    """,
                    email_id,
                )

            # Test size_bytes > 25 Mo (invalide)
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """
                    INSERT INTO ingestion.attachments
                    (email_id, filename, filepath, size_bytes, mime_type, status)
                    VALUES ($1, 'test.pdf', '/tmp/test.pdf', 30000000, 'application/pdf', 'pending')
                    """,
                    email_id,
                )

    async def test_check_constraint_status(self, db_pool_clean):
        """CHECK constraint status (pending/processed/archived/error) enforce."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # Créer email test
            email_id = await conn.fetchval(
                """
                INSERT INTO ingestion.emails (raw_message, subject, sender)
                VALUES ('{}', 'Test', 'test@example.com')
                RETURNING id
                """
            )

            # Test status invalide
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """
                    INSERT INTO ingestion.attachments
                    (email_id, filename, filepath, size_bytes, mime_type, status)
                    VALUES ($1, 'test.pdf', '/tmp/test.pdf', 150000, 'application/pdf', 'invalid_status')
                    """,
                    email_id,
                )

    async def test_trigger_updated_at(self, db_pool_clean):
        """Trigger updated_at met à jour automatiquement sur UPDATE."""
        migration_file = Path("database/migrations/030_ingestion_attachments.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # Créer email test
            email_id = await conn.fetchval(
                """
                INSERT INTO ingestion.emails (raw_message, subject, sender)
                VALUES ('{}', 'Test', 'test@example.com')
                RETURNING id
                """
            )

            # INSERT attachment
            attachment = await conn.fetchrow(
                """
                INSERT INTO ingestion.attachments
                (email_id, filename, filepath, size_bytes, mime_type, status)
                VALUES ($1, 'test.pdf', '/tmp/test.pdf', 150000, 'application/pdf', 'pending')
                RETURNING id, updated_at
                """,
                email_id,
            )

            original_updated_at = attachment["updated_at"]

            # Wait 1s pour différencier timestamps
            import asyncio

            await asyncio.sleep(1)

            # UPDATE attachment
            await conn.execute(
                "UPDATE ingestion.attachments SET status='processed' WHERE id=$1", attachment["id"]
            )

            # Vérifier updated_at changé
            new_updated_at = await conn.fetchval(
                "SELECT updated_at FROM ingestion.attachments WHERE id=$1", attachment["id"]
            )

            assert new_updated_at > original_updated_at, "Trigger updated_at non déclenché"
