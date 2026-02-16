"""
Tests unitaires pour bot/handlers/commands.py

Story 1.9 - Tests handlers commandes Telegram (/help, /start).
Story 1.11 - Stubs supprimes, commandes reelles dans trust_budget_commands.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bot.handlers import commands
from telegram import Chat, Message, Update, User


@pytest.fixture
def mock_update():
    """Fixture Update Telegram mocke."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 123456
    update.effective_user.username = "mainteneur"

    update.message = MagicMock(spec=Message)
    update.message.reply_text = AsyncMock()
    update.message.chat_id = -1001234567890
    update.message.message_thread_id = 100  # Chat & Proactive topic

    return update


@pytest.fixture
def mock_context():
    """Fixture Context Telegram mocke."""
    context = MagicMock()
    return context


@pytest.mark.asyncio
async def test_command_help(mock_update, mock_context):
    """
    Test 1/2: Commande /help retourne liste commandes (AC5).

    Verifie que /help affiche la liste complete des commandes
    disponibles dans le format defini par AC5.
    """
    await commands.help_command(mock_update, mock_context)

    # Verifier que reply_text a ete appele
    mock_update.message.reply_text.assert_called_once()

    # Recuperer le texte envoye
    call_args = mock_update.message.reply_text.call_args
    text = call_args[0][0]

    # Verifier contenu (AC5)
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

    # Verifier parse_mode=Markdown
    assert call_args[1]["parse_mode"] == "Markdown"


@pytest.mark.asyncio
async def test_command_start(mock_update, mock_context):
    """
    Test 2/2: Commande /start est un alias de /help.

    Verifie que /start appelle help_command() et retourne le meme texte.
    """
    with patch("bot.handlers.commands.help_command", new=AsyncMock()) as mock_help:
        await commands.start_command(mock_update, mock_context)

        # Verifier que help_command a ete appele avec les bons arguments
        mock_help.assert_called_once_with(mock_update, mock_context)


def test_no_stub_commands_remain():
    """
    Story 1.11: Verifie que les stubs ont ete supprimes de commands.py.

    Les 6 commandes (status, journal, receipt, confiance, stats, budget)
    sont maintenant dans trust_budget_commands.py.
    """
    assert not hasattr(commands, "status_command_stub")
    assert not hasattr(commands, "journal_command_stub")
    assert not hasattr(commands, "receipt_command_stub")
    assert not hasattr(commands, "confiance_command_stub")
    assert not hasattr(commands, "stats_command_stub")
    assert not hasattr(commands, "budget_command_stub")
