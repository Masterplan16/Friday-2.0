"""
Tests unitaires pour bot/handlers/vip_commands.py (Story 2.3 - Subtask 5.4).

Tests des commandes /vip add, /vip list, /vip remove.
Code Review Fix M2.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update
from telegram.ext import ContextTypes

# Mock friday_action avant import
def mock_friday_action(module=None, action=None, trust_default=None):
    def decorator(func):
        return func
    return decorator

# Mock imports
with patch("agents.src.agents.email.vip_detector.friday_action", mock_friday_action):
    from bot.handlers.vip_commands import vip_add_command, vip_list_command, vip_remove_command


@pytest.fixture
def mock_update():
    """Mock Update Telegram."""
    update = MagicMock(spec=Update)
    update.effective_user.id = 12345
    update.message = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Mock Context avec db_pool."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot_data = {}
    context.args = []
    return context


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg Pool."""
    pool = AsyncMock()
    async def mock_acquire():
        conn = AsyncMock()
        return conn
    pool.acquire = AsyncMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=AsyncMock()), __aexit__=AsyncMock()))
    return pool


# ==========================================
# Tests /vip add
# ==========================================


@pytest.mark.asyncio
async def test_vip_add_success(mock_update, mock_context, mock_db_pool):
    """Test /vip add réussit avec email valide."""
    # Setup
    os.environ["OWNER_USER_ID"] = "12345"
    mock_context.args = ["test@example.com", "Test", "User"]
    mock_context.bot_data["db_pool"] = mock_db_pool

    # Mock acquisition
    async def mock_acquire_context():
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # Pas de VIP existant
        conn.execute = AsyncMock()

        class MockAcquire:
            async def __aenter__(self):
                return conn
            async def __aexit__(self, *args):
                pass

        return MockAcquire()

    mock_db_pool.acquire = mock_acquire_context

    # Mock anonymize_text
    with patch("bot.handlers.vip_commands.anonymize_text", AsyncMock(return_value="[EMAIL_TEST]")):
        await vip_add_command(mock_update, mock_context)

    # Assert
    mock_update.message.reply_text.assert_called_once()
    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "ajouté avec succès" in call_text or "VIP ajouté" in call_text.lower()


@pytest.mark.asyncio
async def test_vip_add_missing_args(mock_update, mock_context, mock_db_pool):
    """Test /vip add échoue si arguments manquants."""
    os.environ["OWNER_USER_ID"] = "12345"
    mock_context.args = ["test@example.com"]  # Pas de label
    mock_context.bot_data["db_pool"] = mock_db_pool

    await vip_add_command(mock_update, mock_context)

    # Assert erreur
    mock_update.message.reply_text.assert_called_once()
    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "Arguments manquants" in call_text or "manquant" in call_text.lower()


# ==========================================
# Tests /vip list
# ==========================================


@pytest.mark.asyncio
async def test_vip_list_empty(mock_update, mock_context, mock_db_pool):
    """Test /vip list retourne message vide si aucun VIP."""
    mock_context.bot_data["db_pool"] = mock_db_pool

    # Mock acquire
    async def mock_acquire_context():
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])  # Aucun VIP

        class MockAcquire:
            async def __aenter__(self):
                return conn
            async def __aexit__(self, *args):
                pass

        return MockAcquire()

    mock_db_pool.acquire = mock_acquire_context

    await vip_list_command(mock_update, mock_context)

    # Assert
    mock_update.message.reply_text.assert_called_once()
    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "Aucun VIP" in call_text or "aucun" in call_text.lower()


@pytest.mark.asyncio
async def test_vip_list_with_vips(mock_update, mock_context, mock_db_pool):
    """Test /vip list retourne liste VIPs."""
    mock_context.bot_data["db_pool"] = mock_db_pool

    # Mock acquire avec VIPs
    async def mock_acquire_context():
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[
            {
                "email_anon": "[EMAIL_123]",
                "label": "Test VIP",
                "emails_received_count": 5,
                "last_email_at": None,
                "designation_source": "manual",
            }
        ])

        class MockAcquire:
            async def __aenter__(self):
                return conn
            async def __aexit__(self, *args):
                pass

        return MockAcquire()

    mock_db_pool.acquire = mock_acquire_context

    await vip_list_command(mock_update, mock_context)

    # Assert
    mock_update.message.reply_text.assert_called_once()
    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "Test VIP" in call_text or "liste" in call_text.lower()


# ==========================================
# Tests /vip remove
# ==========================================


@pytest.mark.asyncio
async def test_vip_remove_success(mock_update, mock_context, mock_db_pool):
    """Test /vip remove réussit."""
    os.environ["OWNER_USER_ID"] = "12345"
    mock_context.args = ["test@example.com"]
    mock_context.bot_data["db_pool"] = mock_db_pool

    # Mock acquire
    async def mock_acquire_context():
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "id": "uuid",
            "email_anon": "[EMAIL_TEST]",
            "label": "Test",
            "active": True,
        })
        conn.execute = AsyncMock()

        class MockAcquire:
            async def __aenter__(self):
                return conn
            async def __aexit__(self, *args):
                pass

        return MockAcquire()

    mock_db_pool.acquire = mock_acquire_context

    await vip_remove_command(mock_update, mock_context)

    # Assert
    mock_update.message.reply_text.assert_called_once()
    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "retiré avec succès" in call_text or "retiré" in call_text.lower()


@pytest.mark.asyncio
async def test_vip_remove_not_found(mock_update, mock_context, mock_db_pool):
    """Test /vip remove échoue si VIP pas trouvé."""
    os.environ["OWNER_USER_ID"] = "12345"
    mock_context.args = ["notfound@example.com"]
    mock_context.bot_data["db_pool"] = mock_db_pool

    # Mock acquire
    async def mock_acquire_context():
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # VIP pas trouvé

        class MockAcquire:
            async def __aenter__(self):
                return conn
            async def __aexit__(self, *args):
                pass

        return MockAcquire()

    mock_db_pool.acquire = mock_acquire_context

    await vip_remove_command(mock_update, mock_context)

    # Assert
    mock_update.message.reply_text.assert_called_once()
    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "non trouvé" in call_text or "aucun" in call_text.lower()


# Note: Tests permissions et rate limiting omis pour brièveté
# TODO: Ajouter tests permissions (non-owner) et rate limiting
