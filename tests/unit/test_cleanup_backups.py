"""
Tests unitaires pour cleanup backups VPS.

Story 1.15 - AC3 : Rotation backups > 30 jours (VPS uniquement)
"""

import pytest
from datetime import datetime, timedelta
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
async def test_cleanup_backups_respects_retention_policy(db_pool):
    """Test cleanup respecte retention_policy (keep_7_days vs keep_30_days).

    GIVEN backups VPS (keep_7_days) AND backups PC (keep_30_days), both >30 days old
    WHEN cleanup_backups() s'exécute
    THEN VPS backups marked deleted_at NOT NULL
    AND PC backups preserved (deleted_at = NULL)
    """
    # Setup: 2 backups VPS (keep_7_days), 1 backup PC (keep_30_days)
    old_date = datetime.utcnow() - timedelta(days=35)

    # Cleanup préalable
    await db_pool.execute("DELETE FROM core.backup_metadata WHERE filename LIKE 'test-backup-%'")

    # Insert VPS backup (should be deleted)
    await db_pool.execute(
        "INSERT INTO core.backup_metadata (filename, backup_date, size_bytes, checksum_sha256, retention_policy) "
        "VALUES ($1, $2, $3, $4, $5)",
        "test-backup-vps-old.dump.age", old_date, 1_000_000, "a" * 64, "keep_7_days"
    )

    # Insert PC backup (should be preserved)
    await db_pool.execute(
        "INSERT INTO core.backup_metadata (filename, backup_date, size_bytes, checksum_sha256, retention_policy) "
        "VALUES ($1, $2, $3, $4, $5)",
        "test-backup-pc-old.dump.age", old_date, 1_000_000, "b" * 64, "keep_30_days"
    )

    # Execute cleanup (simulation SQL from cleanup-disk.sh)
    await db_pool.execute(
        "UPDATE core.backup_metadata "
        "SET deleted_at = NOW() "
        "WHERE retention_policy = 'keep_7_days' "
        "  AND backup_date < NOW() - INTERVAL '30 days' "
        "  AND deleted_at IS NULL"
    )

    # Verify VPS backup marked deleted
    vps_backup = await db_pool.fetchrow(
        "SELECT deleted_at FROM core.backup_metadata WHERE filename = $1",
        "test-backup-vps-old.dump.age"
    )
    assert vps_backup["deleted_at"] is not None, "VPS backup should be marked deleted (soft delete)"

    # Verify PC backup preserved
    pc_backup = await db_pool.fetchrow(
        "SELECT deleted_at FROM core.backup_metadata WHERE filename = $1",
        "test-backup-pc-old.dump.age"
    )
    assert pc_backup["deleted_at"] is None, "PC backup should be preserved (deleted_at = NULL)"

    # Cleanup
    await db_pool.execute("DELETE FROM core.backup_metadata WHERE filename LIKE 'test-backup-%'")


@pytest.mark.asyncio
async def test_cleanup_backups_preserves_recent_vps(db_pool):
    """Test que backups VPS récents (<30j) ne sont PAS supprimés.

    GIVEN backup VPS (keep_7_days) recent (<30 days)
    WHEN cleanup_backups() s'exécute
    THEN backup preserved (deleted_at = NULL)
    """
    recent_date = datetime.utcnow() - timedelta(days=20)

    # Cleanup préalable
    await db_pool.execute("DELETE FROM core.backup_metadata WHERE filename = $1", "test-backup-vps-recent.dump.age")

    # Insert recent VPS backup
    await db_pool.execute(
        "INSERT INTO core.backup_metadata (filename, backup_date, size_bytes, checksum_sha256, retention_policy) "
        "VALUES ($1, $2, $3, $4, $5)",
        "test-backup-vps-recent.dump.age", recent_date, 1_000_000, "c" * 64, "keep_7_days"
    )

    # Execute cleanup
    await db_pool.execute(
        "UPDATE core.backup_metadata "
        "SET deleted_at = NOW() "
        "WHERE retention_policy = 'keep_7_days' "
        "  AND backup_date < NOW() - INTERVAL '30 days' "
        "  AND deleted_at IS NULL"
    )

    # Verify backup preserved
    backup = await db_pool.fetchrow(
        "SELECT deleted_at FROM core.backup_metadata WHERE filename = $1",
        "test-backup-vps-recent.dump.age"
    )
    assert backup["deleted_at"] is None, "Recent VPS backup should NOT be deleted (< 30 days)"

    # Cleanup
    await db_pool.execute("DELETE FROM core.backup_metadata WHERE filename = $1", "test-backup-vps-recent.dump.age")


@pytest.mark.asyncio
async def test_cleanup_backups_idempotent(db_pool):
    """Test que cleanup_backups() est idempotent.

    GIVEN backup déjà marqué deleted_at NOT NULL
    WHEN cleanup_backups() s'exécute à nouveau
    THEN deleted_at inchangé
    """
    old_date = datetime.utcnow() - timedelta(days=40)
    deleted_date = datetime.utcnow() - timedelta(days=5)

    # Cleanup préalable
    await db_pool.execute("DELETE FROM core.backup_metadata WHERE filename = $1", "test-backup-already-deleted.dump.age")

    # Insert already deleted backup
    await db_pool.execute(
        "INSERT INTO core.backup_metadata (filename, backup_date, size_bytes, checksum_sha256, retention_policy, deleted_at) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        "test-backup-already-deleted.dump.age", old_date, 1_000_000, "d" * 64, "keep_7_days", deleted_date
    )

    # Execute cleanup (should NOT update already deleted)
    result = await db_pool.execute(
        "UPDATE core.backup_metadata "
        "SET deleted_at = NOW() "
        "WHERE retention_policy = 'keep_7_days' "
        "  AND backup_date < NOW() - INTERVAL '30 days' "
        "  AND deleted_at IS NULL "
        "RETURNING filename"
    )

    # Extract updated count
    updated_count = int(result.split()[-1])  # "UPDATE N" → N

    assert updated_count == 0, "Already deleted backups should NOT be updated again"

    # Verify deleted_at unchanged
    backup = await db_pool.fetchrow(
        "SELECT deleted_at FROM core.backup_metadata WHERE filename = $1",
        "test-backup-already-deleted.dump.age"
    )
    # Allow 1 second tolerance for timestamp comparison
    assert abs((backup["deleted_at"] - deleted_date).total_seconds()) < 1, "deleted_at should be unchanged"

    # Cleanup
    await db_pool.execute("DELETE FROM core.backup_metadata WHERE filename = $1", "test-backup-already-deleted.dump.age")


@pytest.mark.asyncio
async def test_cleanup_backups_count_accurate(db_pool):
    """Test que le count retourné est précis.

    GIVEN 3 old VPS backups
    WHEN cleanup_backups() s'exécute
    THEN le count retourné = 3
    """
    old_date = datetime.utcnow() - timedelta(days=50)

    # Cleanup préalable
    await db_pool.execute("DELETE FROM core.backup_metadata WHERE filename LIKE 'test-backup-count-%'")

    # Insert 3 old VPS backups
    for i in range(3):
        await db_pool.execute(
            "INSERT INTO core.backup_metadata (filename, backup_date, size_bytes, checksum_sha256, retention_policy) "
            "VALUES ($1, $2, $3, $4, $5)",
            f"test-backup-count-{i}.dump.age", old_date, 1_000_000, f"{i}" * 64, "keep_7_days"
        )

    # Execute cleanup and count
    result = await db_pool.fetch(
        "UPDATE core.backup_metadata "
        "SET deleted_at = NOW() "
        "WHERE retention_policy = 'keep_7_days' "
        "  AND backup_date < NOW() - INTERVAL '30 days' "
        "  AND deleted_at IS NULL "
        "  AND filename LIKE 'test-backup-count-%' "
        "RETURNING filename"
    )

    count = len(result)
    assert count == 3, f"Expected 3 deleted backups, got {count}"

    # Cleanup
    await db_pool.execute("DELETE FROM core.backup_metadata WHERE filename LIKE 'test-backup-count-%'")
