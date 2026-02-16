"""
Tests Unitaires - Commandes Telegram Casquettes

Story 7.3: Multi-casquettes & Conflits Calendrier (AC2)

Tests:
- /casquette affichage (mock ContextManager)
- /casquette medecin force contexte
- /casquette auto réactive auto-detect
- Inline buttons clics
- Validation casquette invalide → erreur
- Unicode emojis rendering
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, Message, User, Chat, InlineKeyboardMarkup

from bot.handlers.casquette_commands import handle_casquette_command
from bot.handlers.casquette_callbacks import handle_casquette_button
from agents.src.core.models import UserContext, ContextSource, Casquette


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_update():
    """Mock Telegram Update."""
    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.message.from_user = MagicMock(spec=User)
    update.message.from_user.id = 12345
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_callback_query():
    """Mock Telegram CallbackQuery."""
    update = MagicMock(spec=Update)
    update.callback_query = MagicMock()
    update.callback_query.from_user = MagicMock(spec=User)
    update.callback_query.from_user.id = 12345
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Mock Telegram Context avec db_pool et redis_client."""
    context = MagicMock()
    context.args = []
    context.bot_data = {
        "db_pool": AsyncMock(),
        "redis_client": AsyncMock()
    }
    return context


# ============================================================================
# Tests Commande /casquette
# ============================================================================

@pytest.mark.asyncio
async def test_casquette_command_display(mock_update, mock_context):
    """Test AC2: /casquette affichage contexte actuel."""
    # Mock ContextManager
    with patch("bot.handlers.casquette_commands.ContextManager") as MockContextManager:
        mock_cm = MockContextManager.return_value

        # Mock get_current_context → médecin (source=event)
        mock_cm.get_current_context = AsyncMock(return_value=UserContext(
            casquette=Casquette.MEDECIN,
            source=ContextSource.EVENT,
            updated_at=datetime.now(),
            updated_by="system"
        ))

        # Mock get_upcoming_events → 1 événement
        with patch("bot.handlers.casquette_commands._get_upcoming_events") as mock_events:
            mock_events.return_value = [{
                "casquette": Casquette.ENSEIGNANT,
                "title": "Cours L2 Anatomie",
                "start_time": "14h00",
                "end_time": "16h00"
            }]

            # Appeler handler
            await handle_casquette_command(mock_update, mock_context)

    # Assertions
    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args

    text = call_args[1]["text"]
    assert "🎭" in text  # Emoji contexte
    assert "Médecin" in text  # Casquette actuelle
    assert "Événement en cours" in text  # Source détection
    assert "Cours L2 Anatomie" in text  # Prochain événement

    # Vérifier inline buttons
    reply_markup = call_args[1]["reply_markup"]
    assert isinstance(reply_markup, InlineKeyboardMarkup)
    assert len(reply_markup.inline_keyboard) == 2  # 2 lignes de boutons
    assert len(reply_markup.inline_keyboard[0]) == 2  # 2 boutons première ligne


@pytest.mark.asyncio
async def test_casquette_command_set_medecin(mock_update, mock_context):
    """Test AC2: /casquette medecin force contexte."""
    # Ajouter argument
    mock_context.args = ["medecin"]

    # Mock ContextManager
    with patch("bot.handlers.casquette_commands.ContextManager") as MockContextManager:
        mock_cm = MockContextManager.return_value

        # Mock set_context
        mock_cm.set_context = AsyncMock(return_value=UserContext(
            casquette=Casquette.MEDECIN,
            source=ContextSource.MANUAL,
            updated_at=datetime.now(),
            updated_by="manual"
        ))

        # Appeler handler
        await handle_casquette_command(mock_update, mock_context)

    # Assertions
    mock_cm.set_context.assert_called_once_with(casquette=Casquette.MEDECIN, source="manual")

    mock_update.message.reply_text.assert_called_once()
    text = mock_update.message.reply_text.call_args[1]["text"]
    assert "✅" in text
    assert "Médecin" in text
    assert "Contexte changé" in text


@pytest.mark.asyncio
async def test_casquette_command_set_auto(mock_update, mock_context):
    """Test AC2: /casquette auto réactive auto-detect."""
    # Ajouter argument
    mock_context.args = ["auto"]

    # Mock ContextManager
    with patch("bot.handlers.casquette_commands.ContextManager") as MockContextManager:
        mock_cm = MockContextManager.return_value

        # Mock set_context (casquette=None)
        mock_cm.set_context = AsyncMock(return_value=UserContext(
            casquette=None,
            source=ContextSource.DEFAULT,
            updated_at=datetime.now(),
            updated_by="system"
        ))

        # Appeler handler
        await handle_casquette_command(mock_update, mock_context)

    # Assertions
    mock_cm.set_context.assert_called_once_with(casquette=None, source="system")

    mock_update.message.reply_text.assert_called_once()
    text = mock_update.message.reply_text.call_args[1]["text"]
    assert "✅" in text
    assert "Détection automatique réactivée" in text


@pytest.mark.asyncio
async def test_casquette_command_invalid_argument(mock_update, mock_context):
    """Test AC2: Validation casquette invalide → erreur."""
    # Ajouter argument invalide
    mock_context.args = ["invalid_casquette"]

    # Mock ContextManager (pas appelé car validation échoue)
    with patch("bot.handlers.casquette_commands.ContextManager") as MockContextManager:
        mock_cm = MockContextManager.return_value

        # Appeler handler
        await handle_casquette_command(mock_update, mock_context)

    # Assertions: set_context PAS appelé
    mock_cm.set_context.assert_not_called()

    # Message erreur
    mock_update.message.reply_text.assert_called_once()
    text = mock_update.message.reply_text.call_args[1]["text"]
    assert "❌" in text
    assert "invalide" in text.lower()
    assert "medecin" in text
    assert "enseignant" in text
    assert "chercheur" in text


# ============================================================================
# Tests Callbacks Inline Buttons
# ============================================================================

@pytest.mark.asyncio
async def test_casquette_button_click_enseignant(mock_callback_query, mock_context):
    """Test AC2: Clic inline button [Enseignant]."""
    # Callback data
    mock_callback_query.callback_query.data = "casquette:enseignant"

    # Mock ContextManager
    with patch("bot.handlers.casquette_callbacks.ContextManager") as MockContextManager:
        mock_cm = MockContextManager.return_value

        # Mock set_context
        mock_cm.set_context = AsyncMock(return_value=UserContext(
            casquette=Casquette.ENSEIGNANT,
            source=ContextSource.MANUAL,
            updated_at=datetime.now(),
            updated_by="manual"
        ))

        # Appeler callback handler
        await handle_casquette_button(mock_callback_query, mock_context)

    # Assertions
    mock_callback_query.callback_query.answer.assert_called_once()

    mock_cm.set_context.assert_called_once_with(casquette=Casquette.ENSEIGNANT, source="manual")

    mock_callback_query.callback_query.edit_message_text.assert_called_once()
    text = mock_callback_query.callback_query.edit_message_text.call_args[1]["text"]
    assert "✅" in text
    assert "Enseignant" in text


@pytest.mark.asyncio
async def test_casquette_button_click_auto(mock_callback_query, mock_context):
    """Test AC2: Clic inline button [Auto]."""
    # Callback data
    mock_callback_query.callback_query.data = "casquette:auto"

    # Mock ContextManager
    with patch("bot.handlers.casquette_callbacks.ContextManager") as MockContextManager:
        mock_cm = MockContextManager.return_value

        # Mock set_context (casquette=None)
        mock_cm.set_context = AsyncMock()

        # Appeler callback handler
        await handle_casquette_button(mock_callback_query, mock_context)

    # Assertions
    mock_cm.set_context.assert_called_once_with(casquette=None, source="system")

    text = mock_callback_query.callback_query.edit_message_text.call_args[1]["text"]
    assert "✅" in text
    assert "Détection automatique réactivée" in text


# ============================================================================
# Tests Unicode Emojis
# ============================================================================

@pytest.mark.asyncio
async def test_casquette_emojis_rendering(mock_update, mock_context):
    """Test AC2: Unicode emojis rendering correct."""
    mock_context.args = []

    # Mock ContextManager
    with patch("bot.handlers.casquette_commands.ContextManager") as MockContextManager:
        mock_cm = MockContextManager.return_value

        # Mock get_current_context
        mock_cm.get_current_context = AsyncMock(return_value=UserContext(
            casquette=Casquette.CHERCHEUR,
            source=ContextSource.MANUAL,
            updated_at=datetime.now(),
            updated_by="manual"
        ))

        # Mock get_upcoming_events
        with patch("bot.handlers.casquette_commands._get_upcoming_events") as mock_events:
            mock_events.return_value = []

            # Appeler handler
            await handle_casquette_command(mock_update, mock_context)

    # Vérifier emojis présents
    text = mock_update.message.reply_text.call_args[1]["text"]
    assert "🎭" in text  # Emoji contexte
    assert "🔬" in text  # Emoji chercheur

    # Vérifier inline buttons ont emojis
    reply_markup = mock_update.message.reply_text.call_args[1]["reply_markup"]
    button_texts = [
        button.text
        for row in reply_markup.inline_keyboard
        for button in row
    ]
    assert any("🩺" in text for text in button_texts)  # Médecin
    assert any("🎓" in text for text in button_texts)  # Enseignant
    assert any("🔬" in text for text in button_texts)  # Chercheur
    assert any("🔄" in text for text in button_texts)  # Auto


# ============================================================================
# Tests Edge Cases
# ============================================================================

@pytest.mark.asyncio
async def test_casquette_command_no_upcoming_events(mock_update, mock_context):
    """Test: Affichage contexte sans événements à venir."""
    mock_context.args = []

    # Mock ContextManager
    with patch("bot.handlers.casquette_commands.ContextManager") as MockContextManager:
        mock_cm = MockContextManager.return_value

        # Mock get_current_context
        mock_cm.get_current_context = AsyncMock(return_value=UserContext(
            casquette=None,
            source=ContextSource.DEFAULT,
            updated_at=datetime.now(),
            updated_by="system"
        ))

        # Mock get_upcoming_events → []
        with patch("bot.handlers.casquette_commands._get_upcoming_events") as mock_events:
            mock_events.return_value = []

            # Appeler handler
            await handle_casquette_command(mock_update, mock_context)

    # Assertions
    text = mock_update.message.reply_text.call_args[1]["text"]
    assert "Auto-détection" in text
    assert "Aucun événement à venir" in text or "_Aucun événement à venir_" in text
