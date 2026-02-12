"""
Tests unitaires pour bot/handlers/sender_filter_commands.py (Story 2.8 Task 3)

Tests des commandes Telegram :
- /blacklist <email|domain> - Ajoute un sender en blacklist
- /whitelist <email|domain> <category> - Ajoute un sender en whitelist
- /filters [list|stats] - Liste les filtres actifs ou stats
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_blacklist_add_email():
    """Test /blacklist add email → INSERT blacklist filter."""
    from bot.handlers.sender_filter_commands import blacklist_command

    # Setup mocks
    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context = MagicMock()
    context.args = ["spam@newsletter.com"]

    # Mock DB pool
    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = UUID("12345678-1234-1234-1234-123456789012")

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    context.bot_data = {"db_pool": mock_pool}

    # Test
    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await blacklist_command(update, context)

    # Assertions
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "blacklist" in reply_text.lower()
    assert "spam@newsletter.com" in reply_text.lower()

    # Vérifier INSERT DB
    mock_conn.fetchval.assert_called_once()


@pytest.mark.asyncio
async def test_whitelist_add_email_with_category():
    """Test /whitelist add email category → INSERT whitelist filter."""
    from bot.handlers.sender_filter_commands import whitelist_command

    # Setup mocks
    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context = MagicMock()
    context.args = ["vip@hospital.fr", "pro"]

    # Mock DB pool
    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = UUID("12345678-1234-1234-1234-123456789012")

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    context.bot_data = {"db_pool": mock_pool}

    # Test
    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await whitelist_command(update, context)

    # Assertions
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "whitelist" in reply_text.lower()
    assert "vip@hospital.fr" in reply_text.lower()
    assert "pro" in reply_text.lower()


@pytest.mark.asyncio
async def test_filters_list():
    """Test /filters list → Affiche tous les filtres actifs."""
    from bot.handlers.sender_filter_commands import filters_command

    # Setup mocks
    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context = MagicMock()
    context.args = ["list"]

    # Mock DB pool avec 2 filtres
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {
            "sender_email": "spam@newsletter.com",
            "sender_domain": None,
            "filter_type": "blacklist",
            "category": "spam",
            "created_at": "2026-02-12",
        },
        {
            "sender_email": None,
            "sender_domain": "vip-domain.fr",
            "filter_type": "whitelist",
            "category": "pro",
            "created_at": "2026-02-12",
        },
    ]

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    context.bot_data = {"db_pool": mock_pool}

    # Test
    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await filters_command(update, context)

    # Assertions
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "spam@newsletter.com" in reply_text
    assert "vip-domain.fr" in reply_text
    assert "blacklist" in reply_text.lower()
    assert "whitelist" in reply_text.lower()


@pytest.mark.asyncio
async def test_filters_stats():
    """Test /filters stats → Affiche statistiques filtrage."""
    from bot.handlers.sender_filter_commands import filters_command

    # Setup mocks
    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context = MagicMock()
    context.args = ["stats"]

    # Mock DB pool avec stats
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "total_filters": 10,
        "blacklist_count": 7,
        "whitelist_count": 3,
        "neutral_count": 0,
    }

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    context.bot_data = {"db_pool": mock_pool}

    # Test
    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await filters_command(update, context)

    # Assertions
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "10" in reply_text  # total
    assert "7" in reply_text  # blacklist
    assert "3" in reply_text  # whitelist


@pytest.mark.asyncio
async def test_blacklist_reject_non_owner():
    """Test /blacklist rejette les non-owners."""
    from bot.handlers.sender_filter_commands import blacklist_command

    # Setup mocks
    update = MagicMock()
    update.effective_user.id = 99999  # Pas le owner
    update.message = AsyncMock()

    context = MagicMock()
    context.args = ["spam@example.com"]
    context.bot_data = {"db_pool": MagicMock()}

    # Test
    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await blacklist_command(update, context)

    # Assertions - doit refuser
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "réservée" in reply_text.lower() or "owner" in reply_text.lower()


@pytest.mark.asyncio
async def test_blacklist_invalid_email():
    """Test /blacklist rejette email invalide."""
    from bot.handlers.sender_filter_commands import blacklist_command

    # Setup mocks
    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context = MagicMock()
    context.args = ["invalid-email"]  # Pas de @ ni .
    context.bot_data = {"db_pool": MagicMock()}

    # Test
    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await blacklist_command(update, context)

    # Assertions - doit refuser
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "invalide" in reply_text.lower()


@pytest.mark.asyncio
async def test_whitelist_invalid_category():
    """Test /whitelist rejette catégorie invalide."""
    from bot.handlers.sender_filter_commands import whitelist_command

    # Setup mocks
    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context = MagicMock()
    context.args = ["vip@example.com", "invalid_category"]  # Catégorie invalide
    context.bot_data = {"db_pool": MagicMock()}

    # Test
    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await whitelist_command(update, context)

    # Assertions - doit refuser
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "invalide" in reply_text.lower() or "catégorie" in reply_text.lower()


@pytest.mark.asyncio
async def test_blacklist_missing_args():
    """Test /blacklist sans args → affiche usage."""
    from bot.handlers.sender_filter_commands import blacklist_command

    # Setup mocks
    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context = MagicMock()
    context.args = []  # Pas d'args
    context.bot_data = {"db_pool": MagicMock()}

    # Test
    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await blacklist_command(update, context)

    # Assertions - doit afficher usage
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "usage" in reply_text.lower() or "exemple" in reply_text.lower()


@pytest.mark.asyncio
async def test_blacklist_reject_when_owner_not_set():
    """C2 fix: /blacklist rejette si OWNER_USER_ID non configuré (fail-closed)."""
    from bot.handlers.sender_filter_commands import blacklist_command

    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context = MagicMock()
    context.args = ["spam@example.com"]
    context.bot_data = {"db_pool": MagicMock()}

    # OWNER_USER_ID = None (env var non définie)
    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", None):
        await blacklist_command(update, context)

    # Doit rejeter (fail-closed)
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "réservée" in reply_text.lower()


@pytest.mark.asyncio
async def test_whitelist_reject_when_owner_not_set():
    """C2 fix: /whitelist rejette si OWNER_USER_ID non configuré."""
    from bot.handlers.sender_filter_commands import whitelist_command

    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context = MagicMock()
    context.args = ["vip@hospital.fr", "pro"]
    context.bot_data = {"db_pool": MagicMock()}

    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", None):
        await whitelist_command(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "réservée" in reply_text.lower()


@pytest.mark.asyncio
async def test_filters_delete_success():
    """M3 fix: /filters delete supprime un filtre existant."""
    from bot.handlers.sender_filter_commands import filters_command

    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context = MagicMock()
    context.args = ["delete", "spam@newsletter.com"]

    mock_conn = AsyncMock()
    mock_conn.execute.return_value = "DELETE 1"

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    context.bot_data = {"db_pool": mock_pool}

    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await filters_command(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "supprimé" in reply_text.lower()
    assert "spam@newsletter.com" in reply_text


@pytest.mark.asyncio
async def test_filters_delete_not_found():
    """M3 fix: /filters delete retourne message si filtre inexistant."""
    from bot.handlers.sender_filter_commands import filters_command

    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context = MagicMock()
    context.args = ["delete", "nonexistent@test.com"]

    mock_conn = AsyncMock()
    mock_conn.execute.return_value = "DELETE 0"

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    context.bot_data = {"db_pool": mock_pool}

    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await filters_command(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "aucun" in reply_text.lower()


@pytest.mark.asyncio
async def test_filters_delete_missing_args():
    """M3 fix: /filters delete sans cible affiche usage."""
    from bot.handlers.sender_filter_commands import filters_command

    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context = MagicMock()
    context.args = ["delete"]  # Pas de cible

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = AsyncMock()
    mock_pool.acquire.return_value.__aexit__.return_value = None

    context.bot_data = {"db_pool": mock_pool}

    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await filters_command(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "usage" in reply_text.lower() or "delete" in reply_text.lower()
