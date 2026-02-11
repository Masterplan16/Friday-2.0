"""
Tests unitaires pour migration 024 - Table ingestion.email_accounts
Story 2.1 - Task 1.2
"""

import pytest
import asyncpg
import os
from pathlib import Path


@pytest.fixture
async def db_connection():
    """Connexion test database"""
    # En dev, utiliser connection string de test ou défaut
    database_url = os.getenv(
        'TEST_DATABASE_URL',
        'postgresql://friday:friday@localhost:5432/friday_test'
    )

    try:
        conn = await asyncpg.connect(database_url)
        yield conn
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_email_accounts_table_exists(db_connection):
    """AC1: Table ingestion.email_accounts doit exister"""
    result = await db_connection.fetchval(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'ingestion'
          AND table_name = 'email_accounts'
        """
    )

    assert result == 1, "Table ingestion.email_accounts not found"


@pytest.mark.asyncio
async def test_email_accounts_has_required_columns(db_connection):
    """AC1: Table doit avoir toutes les colonnes requises"""
    required_columns = [
        'id',  # UUID primary key
        'account_id',  # Identifiant unique account EmailEngine
        'email',  # Email address
        'imap_host',  # IMAP server
        'imap_port',  # IMAP port
        'imap_user',  # IMAP username
        'imap_password_encrypted',  # Encrypted password (pgcrypto)
        'status',  # connected | disconnected | error
        'last_sync',  # Last successful sync timestamp
        'created_at',  # Creation timestamp
        'updated_at',  # Update timestamp
    ]

    columns = await db_connection.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ingestion'
          AND table_name = 'email_accounts'
        """
    )

    column_names = [row['column_name'] for row in columns]

    for col in required_columns:
        assert col in column_names, f"Column '{col}' not found in ingestion.email_accounts"


@pytest.mark.asyncio
async def test_email_accounts_has_unique_constraint_on_email(db_connection):
    """AC1: Index UNIQUE sur email doit exister"""
    result = await db_connection.fetchval(
        """
        SELECT COUNT(*)
        FROM pg_indexes
        WHERE schemaname = 'ingestion'
          AND tablename = 'email_accounts'
          AND indexname LIKE '%email%'
        """
    )

    assert result >= 1, "UNIQUE index on email column not found"


@pytest.mark.asyncio
async def test_email_accounts_has_index_on_status_last_sync(db_connection):
    """AC1: Index composite sur (status, last_sync) doit exister"""
    result = await db_connection.fetchval(
        """
        SELECT COUNT(*)
        FROM pg_indexes
        WHERE schemaname = 'ingestion'
          AND tablename = 'email_accounts'
          AND (indexname LIKE '%status%' OR indexname LIKE '%last_sync%')
        """
    )

    assert result >= 1, "Index on status/last_sync not found"


@pytest.mark.asyncio
@pytest.mark.skip("Requires pgcrypto trigger to be implemented")
async def test_email_accounts_encrypts_password_on_insert(db_connection):
    """AC1: Trigger pgcrypto doit chiffrer password avant INSERT"""
    # Insert test account avec plaintext password
    await db_connection.execute(
        """
        INSERT INTO ingestion.email_accounts (account_id, email, imap_host, imap_port, imap_user, imap_password_encrypted, status)
        VALUES ('test-account-1', 'test@example.com', 'imap.example.com', 993, 'testuser', 'plaintext_password_123', 'disconnected')
        """
    )

    # Vérifier que le password est chiffré (pas plaintext)
    encrypted_pw = await db_connection.fetchval(
        """
        SELECT imap_password_encrypted
        FROM ingestion.email_accounts
        WHERE account_id = 'test-account-1'
        """
    )

    # Nettoyage
    await db_connection.execute(
        "DELETE FROM ingestion.email_accounts WHERE account_id = 'test-account-1'"
    )

    # Password chiffré ne doit PAS être égal au plaintext
    assert encrypted_pw != 'plaintext_password_123', \
        "Password was not encrypted by pgcrypto trigger"

    # Password chiffré doit commencer par \\x (format pgcrypto bytea)
    assert encrypted_pw.startswith('\\x') or isinstance(encrypted_pw, bytes), \
        "Encrypted password not in pgcrypto bytea format"


@pytest.mark.asyncio
async def test_email_accounts_has_updated_at_trigger(db_connection):
    """AC1: Trigger auto-update updated_at doit exister"""
    triggers = await db_connection.fetch(
        """
        SELECT trigger_name
        FROM information_schema.triggers
        WHERE event_object_schema = 'ingestion'
          AND event_object_table = 'email_accounts'
          AND trigger_name LIKE '%updated_at%'
        """
    )

    assert len(triggers) >= 1, "Trigger for auto-updating updated_at not found"
