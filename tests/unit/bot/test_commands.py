"""
Tests unitaires pour bot/handlers/commands.py

Story 1.9 - Tests handlers commandes Telegram (/help, /status, etc.).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, Message, User, Chat
from bot.handlers import commands


@pytest.fixture
def mock_update():
    """Fixture Update Telegram mocké."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 123456
    update.effective_user.username = "antonio"

    update.message = MagicMock(spec=Message)
    update.message.reply_text = AsyncMock()
    update.message.chat_id = -1001234567890
    update.message.message_thread_id = 100  # Chat & Proactive topic

    return update


@pytest.fixture
def mock_context():
    """Fixture Context Telegram mocké."""
    context = MagicMock()
    return context


# ═══════════════════════════════════════════════════════════
# Tests commandes (3 tests requis)
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_command_help(mock_update, mock_context):
    """
    Test 1/3: Commande /help retourne liste commandes (AC5).

    Vérifie que /help affiche la liste complète des commandes
    disponibles dans le format défini par AC5.
    """
    await commands.help_command(mock_update, mock_context)

    # Vérifier que reply_text a été appelé
    mock_update.message.reply_text.assert_called_once()

    # Récupérer le texte envoyé
    call_args = mock_update.message.reply_text.call_args
    text = call_args[0][0]

    # Vérifier contenu (AC5)
    assert "Commandes Friday 2.0" in text
    assert "CONVERSATION" in text
    assert "CONSULTATION" in text
    assert "/status" in text
    assert "/journal" in text
    assert "/receipt" in text
    assert "/confiance" in text
    assert "/stats" in text
    assert "/budget" in text
    assert "telegram-user-guide.md" in text

    # Vérifier parse_mode=Markdown
    assert call_args[1]["parse_mode"] == "Markdown"


@pytest.mark.asyncio
async def test_command_start(mock_update, mock_context):
    """
    Test 2/3: Commande /start est un alias de /help.

    Vérifie que /start appelle help_command() et retourne le même texte.
    """
    with patch("bot.handlers.commands.help_command", new=AsyncMock()) as mock_help:
        await commands.start_command(mock_update, mock_context)

        # Vérifier que help_command a été appelé avec les bons arguments
        mock_help.assert_called_once_with(mock_update, mock_context)


@pytest.mark.asyncio
async def test_command_status_stub(mock_update, mock_context):
    """
    Test 3/3: Commandes Story 1.11 retournent stubs.

    Vérifie que /status (et autres commandes Story 1.11) retournent
    un message indiquant qu'elles seront disponibles dans Story 1.11.
    """
    await commands.status_command_stub(mock_update, mock_context)

    # Vérifier que reply_text a été appelé
    mock_update.message.reply_text.assert_called_once()

    # Récupérer le texte envoyé
    call_args = mock_update.message.reply_text.call_args
    text = call_args[0][0]

    # Vérifier contenu stub
    assert "Story 1.11" in text
    assert "status" in text.lower()


# ═══════════════════════════════════════════════════════════
# Tests complémentaires
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_all_stub_commands_return_stub_message(mock_update, mock_context):
    """
    Test: Toutes les commandes stubs (Story 1.11) retournent un message stub.

    Vérifie que journal, receipt, confiance, stats, budget retournent tous
    un message indiquant Story 1.11.
    """
    stub_commands = [
        commands.journal_command_stub,
        commands.receipt_command_stub,
        commands.confiance_command_stub,
        commands.stats_command_stub,
        commands.budget_command_stub,
    ]

    for stub_command in stub_commands:
        # Reset mock
        mock_update.message.reply_text.reset_mock()

        # Appeler commande
        await stub_command(mock_update, mock_context)

        # Vérifier stub message
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        text = call_args[0][0]

        assert "Story 1.11" in text
