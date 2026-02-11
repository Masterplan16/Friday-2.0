"""
Tests unitaires pour les commandes backup Telegram.

Story 1.12 - Task 4.2
Pattern Story 1.11 - 4-5 tests minimum par commande
"""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bot.handlers.backup_commands import backup_command
from telegram import Message, Update, User
from telegram.ext import ContextTypes


@pytest.fixture
def mock_update():
    """Fixture: Mock Telegram Update avec user."""
    update = AsyncMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 123456  # OWNER_USER_ID pour tests
    update.message = AsyncMock(spec=Message)
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Fixture: Mock Context avec args et bot_data."""
    context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []
    context.bot_data = {}
    return context


@pytest.fixture
def mock_pool():
    """Fixture: Mock asyncpg pool avec connection."""
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock()

    # Create async context manager for acquire()
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)

    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool, conn


@pytest.mark.asyncio
async def test_backup_command_lists_recent_backups(mock_update, mock_context, mock_pool):
    """Test: Liste 5 derniers backups avec données."""
    pool, conn = mock_pool
    mock_context.bot_data["db_pool"] = pool

    # Mock données backup
    conn.fetch.return_value = [
        {
            "backup_date": datetime(2026, 2, 10, 3, 0, tzinfo=timezone.utc),
            "filename": "friday_backup_2026-02-10_0300.dump.age",
            "size_bytes": 50000000,
            "synced_to_pc": True,
            "pc_arrival_time": datetime(2026, 2, 10, 3, 5, tzinfo=timezone.utc),
            "retention_policy": "keep_7_days",
            "last_restore_test": None,
            "restore_test_status": None,
        }
    ]

    # Set OWNER_USER_ID
    os.environ["OWNER_USER_ID"] = "123456"

    # Execute
    await backup_command(mock_update, mock_context)

    # Assertions
    conn.fetch.assert_called_once()
    assert "LIMIT 5" in conn.fetch.call_args[0][0]
    mock_update.message.reply_text.assert_called_once()
    response = mock_update.message.reply_text.call_args[0][0]
    assert "📦" in response
    assert "friday_backup" in response
    assert "✅" in response  # Sync status icon


@pytest.mark.asyncio
async def test_backup_command_verbose_shows_details(mock_update, mock_context, mock_pool):
    """Test: Flag -v ajoute taille + sync status + restore test."""
    pool, conn = mock_pool
    mock_context.bot_data["db_pool"] = pool
    mock_context.args = ["-v"]  # Verbose flag

    # Mock données avec restore test
    conn.fetch.return_value = [
        {
            "backup_date": datetime(2026, 2, 10, 3, 0, tzinfo=timezone.utc),
            "filename": "friday_backup_2026-02-10_0300.dump.age",
            "size_bytes": 50000000,
            "synced_to_pc": True,
            "pc_arrival_time": datetime(2026, 2, 10, 3, 5, tzinfo=timezone.utc),
            "retention_policy": "keep_7_days",
            "last_restore_test": datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc),
            "restore_test_status": "success",
        }
    ]

    os.environ["OWNER_USER_ID"] = "123456"

    # Execute
    await backup_command(mock_update, mock_context)

    # Assertions
    response = mock_update.message.reply_text.call_args[0][0]
    assert "MB" in response  # Taille affichée
    assert "Chiffré:" in response  # Détails encryption
    assert "Rétention:" in response  # Retention policy
    assert "Arrivée PC:" in response  # PC arrival time
    assert "Dernier test restore:" in response  # Restore test info


@pytest.mark.asyncio
async def test_backup_command_empty_database_graceful(mock_update, mock_context, mock_pool):
    """Test: Gestion graceful si aucun backup trouvé."""
    pool, conn = mock_pool
    mock_context.bot_data["db_pool"] = pool

    # Mock aucun backup
    conn.fetch.return_value = []

    os.environ["OWNER_USER_ID"] = "123456"

    # Execute
    await backup_command(mock_update, mock_context)

    # Assertions
    mock_update.message.reply_text.assert_called_once()
    response = mock_update.message.reply_text.call_args[0][0]
    assert "Aucun backup" in response or "0 backup" in response
    assert "03h00" in response  # Mention horaire cron


@pytest.mark.asyncio
async def test_backup_command_unauthorized_user_rejected(mock_update, mock_context):
    """Test: OWNER_USER_ID check refuse non-owner."""
    # Set OWNER_USER_ID différent de user
    os.environ["OWNER_USER_ID"] = "999999"
    mock_update.effective_user.id = 123456  # Pas le owner

    # Execute
    await backup_command(mock_update, mock_context)

    # Assertions
    mock_update.message.reply_text.assert_called_once_with("❌ Unauthorized: Commande réservée au Mainteneur")


@pytest.mark.asyncio
async def test_backup_command_lazy_pool_initialization(mock_update, mock_context, mock_pool):
    """Test: Pool asyncpg lazy init si pas dans bot_data."""
    pool, conn = mock_pool
    # bot_data vide initialement
    mock_context.bot_data = {}

    # Mock pool creation
    conn.fetch.return_value = []

    os.environ["OWNER_USER_ID"] = "123456"
    os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"

    with patch("bot.handlers.backup_commands.asyncpg.create_pool", return_value=pool):
        # Execute
        await backup_command(mock_update, mock_context)

        # Assertions
        assert "db_pool" in mock_context.bot_data
        assert mock_context.bot_data["db_pool"] == pool
