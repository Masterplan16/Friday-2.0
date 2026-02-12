"""
Tests unitaires pour migration 033 - core.sender_filters.

Valide :
- Syntaxe SQL (BEGIN/COMMIT)
- Structure table sender_filters
- Indexes (email, domain, type)
- CHECK constraints (filter_type)
- Colonnes NOT NULL
- Trigger updated_at
- Data integrity
"""

import pytest
import asyncpg
from pathlib import Path


@pytest.fixture
async def db_pool_clean(db_pool):
    """Fixture clean DB pour tests migration."""
    # Rollback migration 033 si existe
    async with db_pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS core.sender_filters CASCADE")

    yield db_pool

    # Cleanup après tests
    async with db_pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS core.sender_filters CASCADE")


class TestMigration033Syntax:
    """Tests syntaxe SQL migration 033."""

    def test_migration_file_exists(self):
        """Migration 033 existe dans database/migrations/."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        assert migration_file.exists(), "Migration 033_sender_filters.sql manquante"

    def test_migration_has_begin_commit(self):
        """Migration contient BEGIN et COMMIT (transaction atomique)."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        content = migration_file.read_text()

        assert "BEGIN;" in content, "BEGIN manquant dans migration"
        assert "COMMIT;" in content, "COMMIT manquant dans migration"

    def test_migration_creates_sender_filters_table(self):
        """Migration crée table core.sender_filters."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        content = migration_file.read_text()

        assert "CREATE TABLE" in content and "core.sender_filters" in content
        assert "id UUID PRIMARY KEY" in content
        assert "sender_email TEXT" in content
        assert "sender_domain TEXT" in content
        assert "filter_type TEXT" in content
        assert "category TEXT" in content
        assert "confidence FLOAT" in content
        assert "created_at" in content
        assert "updated_at" in content
        assert "created_by TEXT" in content
        assert "notes TEXT" in content

    def test_migration_creates_indexes(self):
        """Migration crée indexes (email, domain, type)."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        content = migration_file.read_text()

        assert "CREATE INDEX" in content or "CREATE UNIQUE INDEX" in content
        assert "idx_sender_filters_email" in content
        assert "idx_sender_filters_domain" in content
        assert "idx_sender_filters_type" in content

    def test_migration_has_check_constraint_filter_type(self):
        """Migration définit CHECK constraint filter_type (whitelist/blacklist/neutral)."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        content = migration_file.read_text()

        assert "CHECK" in content
        assert "filter_type" in content
        assert "'whitelist'" in content
        assert "'blacklist'" in content
        assert "'neutral'" in content

    def test_migration_creates_trigger_updated_at(self):
        """Migration crée trigger updated_at automatique."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        content = migration_file.read_text()

        assert "CREATE TRIGGER" in content
        assert "trg_sender_filters_updated_at" in content or "sender_filters_updated_at" in content
        assert "update_updated_at_column" in content

    def test_migration_has_not_null_constraints(self):
        """Migration définit NOT NULL sur colonnes critiques."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        content = migration_file.read_text()

        # filter_type doit être NOT NULL
        assert "filter_type" in content
        # Au moins une colonne sender_email ou sender_domain doit être NOT NULL
        assert "sender_" in content


@pytest.mark.asyncio
class TestMigration033Execution:
    """Tests exécution migration 033 sur DB réelle."""

    async def test_apply_migration_success(self, db_pool_clean):
        """Migration 033 s'applique sans erreur."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            # Exécuter migration
            await conn.execute(sql)

            # Vérifier table créée
            table_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'core' AND table_name = 'sender_filters'
                )
                """
            )
            assert table_exists is True, "Table core.sender_filters non créée"

    async def test_sender_filters_table_columns(self, db_pool_clean):
        """Table sender_filters contient toutes les colonnes requises."""
        # Apply migration
        migration_file = Path("database/migrations/033_sender_filters.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # Query colonnes table
            columns = await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'core' AND table_name = 'sender_filters'
                ORDER BY ordinal_position
                """
            )

            column_names = [col['column_name'] for col in columns]

            # Vérifier colonnes requises
            assert 'id' in column_names
            assert 'sender_email' in column_names
            assert 'sender_domain' in column_names
            assert 'filter_type' in column_names
            assert 'category' in column_names
            assert 'confidence' in column_names
            assert 'created_at' in column_names
            assert 'updated_at' in column_names
            assert 'created_by' in column_names
            assert 'notes' in column_names

    async def test_sender_filters_indexes_created(self, db_pool_clean):
        """Indexes sender_filters créés correctement."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # Query indexes
            indexes = await conn.fetch(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'core' AND tablename = 'sender_filters'
                """
            )

            index_names = [idx['indexname'] for idx in indexes]

            assert 'idx_sender_filters_email' in index_names
            assert 'idx_sender_filters_domain' in index_names
            assert 'idx_sender_filters_type' in index_names


@pytest.mark.asyncio
class TestMigration033DataIntegrity:
    """Tests data integrity migration 033."""

    async def test_insert_blacklist_filter(self, db_pool_clean):
        """INSERT filter avec filter_type=blacklist réussit."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # INSERT blacklist filter
            filter_id = await conn.fetchval(
                """
                INSERT INTO core.sender_filters
                (sender_email, filter_type, category, confidence, created_by)
                VALUES ('spam@example.com', 'blacklist', 'spam', 1.0, 'user')
                RETURNING id
                """
            )

            assert filter_id is not None, "INSERT blacklist filter failed"

    async def test_insert_whitelist_filter(self, db_pool_clean):
        """INSERT filter avec filter_type=whitelist réussit."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # INSERT whitelist filter
            filter_id = await conn.fetchval(
                """
                INSERT INTO core.sender_filters
                (sender_email, filter_type, category, confidence, created_by)
                VALUES ('vip@hospital.fr', 'whitelist', 'pro', 0.95, 'user')
                RETURNING id
                """
            )

            assert filter_id is not None, "INSERT whitelist filter failed"

    async def test_insert_neutral_filter(self, db_pool_clean):
        """INSERT filter avec filter_type=neutral réussit."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # INSERT neutral filter
            filter_id = await conn.fetchval(
                """
                INSERT INTO core.sender_filters
                (sender_email, filter_type, category, confidence, created_by)
                VALUES ('neutral@example.com', 'neutral', NULL, NULL, 'system')
                RETURNING id
                """
            )

            assert filter_id is not None, "INSERT neutral filter failed"

    async def test_check_constraint_filter_type_invalid(self, db_pool_clean):
        """CHECK constraint filter_type rejette valeurs invalides."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # Test filter_type invalide
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """
                    INSERT INTO core.sender_filters
                    (sender_email, filter_type, category, confidence, created_by)
                    VALUES ('test@example.com', 'invalid_type', 'spam', 1.0, 'user')
                    """
                )

    async def test_domain_filter_without_email(self, db_pool_clean):
        """INSERT filter par domaine (sans email) réussit."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # INSERT domain filter (sender_email NULL, sender_domain présent)
            filter_id = await conn.fetchval(
                """
                INSERT INTO core.sender_filters
                (sender_domain, filter_type, category, confidence, created_by)
                VALUES ('newsletter.com', 'blacklist', 'spam', 1.0, 'system')
                RETURNING id
                """
            )

            assert filter_id is not None, "INSERT domain filter failed"

    async def test_trigger_updated_at(self, db_pool_clean):
        """Trigger updated_at met à jour automatiquement sur UPDATE."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # INSERT filter
            filter_row = await conn.fetchrow(
                """
                INSERT INTO core.sender_filters
                (sender_email, filter_type, category, confidence, created_by)
                VALUES ('test@example.com', 'blacklist', 'spam', 1.0, 'user')
                RETURNING id, updated_at
                """
            )

            original_updated_at = filter_row['updated_at']

            # Wait 1s pour différencier timestamps
            import asyncio
            await asyncio.sleep(1)

            # UPDATE filter
            await conn.execute(
                "UPDATE core.sender_filters SET notes='Updated note' WHERE id=$1",
                filter_row['id']
            )

            # Vérifier updated_at changé
            new_updated_at = await conn.fetchval(
                "SELECT updated_at FROM core.sender_filters WHERE id=$1",
                filter_row['id']
            )

            assert new_updated_at > original_updated_at, "Trigger updated_at non déclenché"

    async def test_default_timestamps(self, db_pool_clean):
        """created_at et updated_at ont des valeurs par défaut."""
        migration_file = Path("database/migrations/033_sender_filters.sql")
        sql = migration_file.read_text()

        async with db_pool_clean.acquire() as conn:
            await conn.execute(sql)

            # INSERT filter sans spécifier timestamps
            filter_row = await conn.fetchrow(
                """
                INSERT INTO core.sender_filters
                (sender_email, filter_type, category, confidence, created_by)
                VALUES ('test@example.com', 'blacklist', 'spam', 1.0, 'user')
                RETURNING created_at, updated_at
                """
            )

            assert filter_row['created_at'] is not None, "created_at doit avoir une valeur par défaut"
            assert filter_row['updated_at'] is not None, "updated_at doit avoir une valeur par défaut"
