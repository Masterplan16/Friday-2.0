"""
Tests unitaires pour migrations 022-023 (cleanup RGPD).

Story 1.15 - Vérification migrations SQL appliquées correctement
"""

import pytest
import asyncpg
import os


@pytest.fixture
async def db_pool():
    """Fixture pour connexion PostgreSQL test."""
    database_url = os.getenv("DATABASE_URL", "postgresql://friday:friday@localhost:5432/friday_test")
    pool = await asyncpg.create_pool(database_url)
    yield pool
    await pool.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_migration_022_creates_purged_at_column(db_pool):
    """Test migration 022 crée colonne purged_at.

    GIVEN migration 022 appliquée
    WHEN on vérifie information_schema.columns
    THEN colonne purged_at existe dans core.action_receipts
    AND type = TIMESTAMPTZ
    AND commentaire RGPD présent
    """
    # Verify column exists
    column_info = await db_pool.fetchrow(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'core'
          AND table_name = 'action_receipts'
          AND column_name = 'purged_at'
        """
    )

    assert column_info is not None, "Migration 022 failed: purged_at column not found"
    assert column_info["column_name"] == "purged_at"
    assert column_info["data_type"] == "timestamp with time zone", "purged_at should be TIMESTAMPTZ"
    assert column_info["is_nullable"] == "YES", "purged_at should be nullable"

    # Verify index exists
    index_info = await db_pool.fetchrow(
        """
        SELECT indexname FROM pg_indexes
        WHERE schemaname = 'core'
          AND tablename = 'action_receipts'
          AND indexname = 'idx_action_receipts_purged'
        """
    )

    assert index_info is not None, "Migration 022 failed: idx_action_receipts_purged not found"

    # Verify comment exists
    col_comment = await db_pool.fetchval(
        """
        SELECT col_description('core.action_receipts'::regclass,
            (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'core.action_receipts'::regclass
               AND attname = 'purged_at'))
        """
    )

    assert col_comment is not None, "Migration 022 failed: purged_at column comment missing"
    assert "RGPD" in col_comment, "Comment should mention RGPD compliance"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_migration_023_creates_deleted_at_column(db_pool):
    """Test migration 023 crée colonne deleted_at.

    GIVEN migration 023 appliquée
    WHEN on vérifie information_schema.columns
    THEN colonne deleted_at existe dans core.backup_metadata
    AND type = TIMESTAMPTZ
    AND commentaire soft delete présent
    """
    # Verify column exists
    column_info = await db_pool.fetchrow(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'core'
          AND table_name = 'backup_metadata'
          AND column_name = 'deleted_at'
        """
    )

    assert column_info is not None, "Migration 023 failed: deleted_at column not found"
    assert column_info["column_name"] == "deleted_at"
    assert column_info["data_type"] == "timestamp with time zone", "deleted_at should be TIMESTAMPTZ"
    assert column_info["is_nullable"] == "YES", "deleted_at should be nullable"

    # Verify index exists
    index_info = await db_pool.fetchrow(
        """
        SELECT indexname FROM pg_indexes
        WHERE schemaname = 'core'
          AND tablename = 'backup_metadata'
          AND indexname = 'idx_backup_metadata_deleted'
        """
    )

    assert index_info is not None, "Migration 023 failed: idx_backup_metadata_deleted not found"

    # Verify comment exists
    col_comment = await db_pool.fetchval(
        """
        SELECT col_description('core.backup_metadata'::regclass,
            (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'core.backup_metadata'::regclass
               AND attname = 'deleted_at'))
        """
    )

    assert col_comment is not None, "Migration 023 failed: deleted_at column comment missing"
    assert "soft delete" in col_comment.lower(), "Comment should mention soft delete pattern"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_purged_at_allows_null_and_timestamp(db_pool):
    """Test purged_at accepte NULL et TIMESTAMPTZ.

    GIVEN colonne purged_at créée
    WHEN on insère receipt avec purged_at=NULL puis purged_at=NOW()
    THEN les deux inserts réussissent
    """
    # Cleanup préalable
    await db_pool.execute("DELETE FROM core.action_receipts WHERE id = 'test-purged-at-nullable'")

    # Insert with purged_at=NULL
    await db_pool.execute(
        """
        INSERT INTO core.action_receipts (id, module, action, created_at, purged_at, status, trust_level, confidence)
        VALUES ($1, $2, $3, NOW(), NULL, $4, $5, $6)
        """,
        "test-purged-at-nullable", "test", "test_action", "auto", "auto", 0.95
    )

    receipt = await db_pool.fetchrow(
        "SELECT purged_at FROM core.action_receipts WHERE id = $1",
        "test-purged-at-nullable"
    )
    assert receipt["purged_at"] is None, "purged_at should accept NULL"

    # Update with purged_at=NOW()
    await db_pool.execute(
        "UPDATE core.action_receipts SET purged_at = NOW() WHERE id = $1",
        "test-purged-at-nullable"
    )

    receipt = await db_pool.fetchrow(
        "SELECT purged_at FROM core.action_receipts WHERE id = $1",
        "test-purged-at-nullable"
    )
    assert receipt["purged_at"] is not None, "purged_at should accept TIMESTAMPTZ"

    # Cleanup
    await db_pool.execute("DELETE FROM core.action_receipts WHERE id = 'test-purged-at-nullable'")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deleted_at_allows_null_and_timestamp(db_pool):
    """Test deleted_at accepte NULL et TIMESTAMPTZ.

    GIVEN colonne deleted_at créée
    WHEN on insère backup avec deleted_at=NULL puis deleted_at=NOW()
    THEN les deux inserts réussissent
    """
    # Cleanup préalable
    await db_pool.execute("DELETE FROM core.backup_metadata WHERE filename = 'test-deleted-at-nullable.dump.age'")

    # Insert with deleted_at=NULL
    await db_pool.execute(
        """
        INSERT INTO core.backup_metadata (filename, backup_date, size_bytes, checksum_sha256, retention_policy, deleted_at)
        VALUES ($1, NOW(), $2, $3, $4, NULL)
        """,
        "test-deleted-at-nullable.dump.age", 1000000, "a" * 64, "keep_7_days"
    )

    backup = await db_pool.fetchrow(
        "SELECT deleted_at FROM core.backup_metadata WHERE filename = $1",
        "test-deleted-at-nullable.dump.age"
    )
    assert backup["deleted_at"] is None, "deleted_at should accept NULL"

    # Update with deleted_at=NOW()
    await db_pool.execute(
        "UPDATE core.backup_metadata SET deleted_at = NOW() WHERE filename = $1",
        "test-deleted-at-nullable.dump.age"
    )

    backup = await db_pool.fetchrow(
        "SELECT deleted_at FROM core.backup_metadata WHERE filename = $1",
        "test-deleted-at-nullable.dump.age"
    )
    assert backup["deleted_at"] is not None, "deleted_at should accept TIMESTAMPTZ"

    # Cleanup
    await db_pool.execute("DELETE FROM core.backup_metadata WHERE filename = 'test-deleted-at-nullable.dump.age'")
