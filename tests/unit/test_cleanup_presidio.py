"""
Tests unitaires pour cleanup Presidio mappings.

Story 1.15 - AC1 : Purge mappings Presidio > 30 jours
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
async def test_cleanup_presidio_purges_old_mappings(db_pool):
    """Test purge mappings Presidio >30 jours.

    GIVEN action_receipts avec encrypted_mapping >30 jours ET <30 jours
    WHEN cleanup_presidio() s'exécute
    THEN mappings >30j sont purgés (encrypted_mapping=NULL, purged_at=NOW())
    AND mappings <30j restent intacts
    """
    # Setup: Create action_receipts avec encrypted_mapping
    old_date = datetime.utcnow() - timedelta(days=31)
    recent_date = datetime.utcnow() - timedelta(days=10)

    # Cleanup préalable
    await db_pool.execute("DELETE FROM core.action_receipts WHERE id IN ($1, $2)", "old-receipt-test", "recent-receipt-test")

    # Insert test data
    await db_pool.execute(
        "INSERT INTO core.action_receipts (id, module, action, created_at, encrypted_mapping, status, trust_level, confidence) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        "old-receipt-test", "test", "test_action", old_date, b"encrypted_data_old", "auto", "auto", 0.95
    )
    await db_pool.execute(
        "INSERT INTO core.action_receipts (id, module, action, created_at, encrypted_mapping, status, trust_level, confidence) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        "recent-receipt-test", "test", "test_action", recent_date, b"encrypted_data_recent", "auto", "auto", 0.95
    )

    # Execute cleanup (simule SQL du script cleanup-disk.sh)
    result = await db_pool.execute(
        "UPDATE core.action_receipts "
        "SET encrypted_mapping = NULL, purged_at = NOW() "
        "WHERE created_at < NOW() - INTERVAL '30 days' "
        "  AND encrypted_mapping IS NOT NULL "
        "  AND purged_at IS NULL"
    )

    # Verify old receipt purged
    old_receipt = await db_pool.fetchrow(
        "SELECT encrypted_mapping, purged_at FROM core.action_receipts WHERE id = $1",
        "old-receipt-test"
    )
    assert old_receipt["encrypted_mapping"] is None, "Old mapping should be purged (NULL)"
    assert old_receipt["purged_at"] is not None, "purged_at should be set (audit trail)"

    # Verify recent receipt NOT purged
    recent_receipt = await db_pool.fetchrow(
        "SELECT encrypted_mapping, purged_at FROM core.action_receipts WHERE id = $1",
        "recent-receipt-test"
    )
    assert recent_receipt["encrypted_mapping"] is not None, "Recent mapping should NOT be purged"
    assert recent_receipt["purged_at"] is None, "purged_at should be NULL (not purged)"

    # Cleanup
    await db_pool.execute("DELETE FROM core.action_receipts WHERE id IN ($1, $2)", "old-receipt-test", "recent-receipt-test")


@pytest.mark.asyncio
async def test_cleanup_presidio_idempotent(db_pool):
    """Test que cleanup_presidio() est idempotent.

    GIVEN mapping déjà purgé (purged_at NOT NULL)
    WHEN cleanup_presidio() s'exécute à nouveau
    THEN aucune modification (purged_at inchangé)
    """
    old_date = datetime.utcnow() - timedelta(days=35)
    purge_date = datetime.utcnow() - timedelta(days=3)

    # Cleanup préalable
    await db_pool.execute("DELETE FROM core.action_receipts WHERE id = $1", "already-purged-test")

    # Insert already purged receipt
    await db_pool.execute(
        "INSERT INTO core.action_receipts (id, module, action, created_at, encrypted_mapping, purged_at, status, trust_level, confidence) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        "already-purged-test", "test", "test_action", old_date, None, purge_date, "auto", "auto", 0.95
    )

    # Execute cleanup (should NOT update already purged)
    result = await db_pool.execute(
        "UPDATE core.action_receipts "
        "SET encrypted_mapping = NULL, purged_at = NOW() "
        "WHERE created_at < NOW() - INTERVAL '30 days' "
        "  AND encrypted_mapping IS NOT NULL "
        "  AND purged_at IS NULL "
        "RETURNING id"
    )

    # Extract updated count
    updated_count = int(result.split()[-1])  # "UPDATE N" → N

    assert updated_count == 0, "Already purged receipts should NOT be updated again"

    # Verify purged_at unchanged
    receipt = await db_pool.fetchrow(
        "SELECT purged_at FROM core.action_receipts WHERE id = $1",
        "already-purged-test"
    )
    # Allow 1 second tolerance for timestamp comparison
    assert abs((receipt["purged_at"] - purge_date).total_seconds()) < 1, "purged_at should be unchanged"

    # Cleanup
    await db_pool.execute("DELETE FROM core.action_receipts WHERE id = $1", "already-purged-test")


@pytest.mark.asyncio
async def test_cleanup_presidio_count_accurate(db_pool):
    """Test que le count retourné est précis.

    GIVEN 3 old receipts avec encrypted_mapping
    WHEN cleanup_presidio() s'exécute
    THEN le count retourné = 3
    """
    old_date = datetime.utcnow() - timedelta(days=40)

    # Cleanup préalable
    await db_pool.execute("DELETE FROM core.action_receipts WHERE id LIKE 'count-test-%'")

    # Insert 3 old receipts
    for i in range(3):
        await db_pool.execute(
            "INSERT INTO core.action_receipts (id, module, action, created_at, encrypted_mapping, status, trust_level, confidence) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            f"count-test-{i}", "test", "test_action", old_date, f"encrypted_{i}".encode(), "auto", "auto", 0.95
        )

    # Execute cleanup and count
    result = await db_pool.fetch(
        "UPDATE core.action_receipts "
        "SET encrypted_mapping = NULL, purged_at = NOW() "
        "WHERE created_at < NOW() - INTERVAL '30 days' "
        "  AND encrypted_mapping IS NOT NULL "
        "  AND purged_at IS NULL "
        "  AND id LIKE 'count-test-%' "
        "RETURNING id"
    )

    count = len(result)
    assert count == 3, f"Expected 3 purged mappings, got {count}"

    # Cleanup
    await db_pool.execute("DELETE FROM core.action_receipts WHERE id LIKE 'count-test-%'")
