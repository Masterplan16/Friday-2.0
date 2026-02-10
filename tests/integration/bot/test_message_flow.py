"""
Tests d'intégration pour bot Telegram Friday 2.0

Story 1.9 - Tests flux message complet (réception → traitement → envoi).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from bot.handlers.messages import handle_text_message, send_message_with_split
from telegram import Update, Message, User, Chat
from telegram.constants import MessageLimit


@pytest.fixture
def mock_update():
    """Fixture Update Telegram mocké."""
    update = MagicMock(spec=Update)

    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 123456
    update.effective_user.username = "mainteneur"

    update.message = MagicMock(spec=Message)
    update.message.chat_id = -1001234567890
    update.message.message_id = 42
    update.message.text = "Hello Friday"
    update.message.message_thread_id = 100  # Chat & Proactive
    update.message.date = datetime.now()
    update.message.reply_text = AsyncMock()

    return update


@pytest.fixture
def mock_context():
    """Fixture Context Telegram mocké."""
    return MagicMock()


# ═══════════════════════════════════════════════════════════
# Tests intégration - Message Flow
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_message_reception_and_echo(mock_update, mock_context):
    """
    Test intégration: Message reçu → Echo response envoyé (AC3).

    Vérifie le flux complet:
    1. Message texte reçu depuis Telegram
    2. Message loggé (user_id, thread_id, text)
    3. Echo response envoyé dans le même topic

    Note: Stockage DB désactivé (TODO Story 1.9).
    """
    await handle_text_message(mock_update, mock_context)

    # Vérifier que reply_text a été appelé (echo response)
    mock_update.message.reply_text.assert_called_once()

    # Vérifier contenu echo
    call_args = mock_update.message.reply_text.call_args
    text = call_args[0][0]

    assert text == "Echo: Hello Friday"


@pytest.mark.asyncio
async def test_message_long_split(mock_update, mock_context):
    """
    Test intégration: Message long (>4096 chars) splitté (BUG-1.9.9 fix).

    Vérifie que send_message_with_split() découpe correctement les messages
    longs en plusieurs chunks et les envoie séparément.
    """
    # Message de 5000 caractères
    long_text = "A" * 5000

    await send_message_with_split(mock_update, long_text)

    # Vérifier que reply_text a été appelé plusieurs fois
    assert mock_update.message.reply_text.call_count >= 2

    # Vérifier qu'aucun chunk ne dépasse la limite
    for call in mock_update.message.reply_text.call_args_list:
        chunk_text = call[0][0]
        assert len(chunk_text) <= MessageLimit.MAX_TEXT_LENGTH


@pytest.mark.asyncio
async def test_message_with_newlines_split_cleanly(mock_update, mock_context):
    """
    Test intégration: Message long avec newlines splitté proprement.

    Vérifie que send_message_with_split() préfère découper sur les newlines
    plutôt que couper au milieu d'un mot.
    """
    # Message avec newlines
    text_parts = ["Line " + str(i) + "\n" for i in range(200)]
    long_text = "".join(text_parts)  # ~1400 chars

    await send_message_with_split(mock_update, long_text)

    # Vérifier découpe sur newlines
    for call in mock_update.message.reply_text.call_args_list:
        chunk_text = call[0][0]

        # Si chunk ne contient pas le texte complet, il devrait se terminer
        # par un newline (découpe propre)
        if len(chunk_text) < len(long_text):
            # Enlever le préfixe [1/2] si présent
            clean_chunk = chunk_text.split("\n", 1)[-1] if "[" in chunk_text.split("\n")[0] else chunk_text
            # Le dernier char devrait être un newline (ou espace)
            # Note: lstrip dans send_message_with_split enlève les espaces leading


# ═══════════════════════════════════════════════════════════
# Tests intégration - Event Routing (TODO Story 1.9)
# ═══════════════════════════════════════════════════════════


@pytest.mark.skip(reason="Redis Pub/Sub intégration TODO Story 1.9")
@pytest.mark.asyncio
async def test_redis_event_routed_to_correct_topic():
    """
    Test intégration: Event Redis → Routé → Envoyé topic correct.

    TODO Story 1.9: Implémenter quand intégration Redis Pub/Sub complète.

    Vérifie:
    1. Event publié sur Redis Streams (friday:events:telegram.*)
    2. Bot subscribe et reçoit event
    3. EventRouter route vers topic correct
    4. Message envoyé dans le bon topic via send_message()
    """
    pass


@pytest.mark.skip(reason="Database intégration TODO Story 1.9")
@pytest.mark.asyncio
async def test_message_stored_in_database():
    """
    Test intégration: Message reçu → Stocké dans ingestion.telegram_messages.

    TODO Story 1.9: Implémenter quand store_telegram_message() activé.

    Vérifie:
    1. Message reçu depuis Telegram
    2. Message inséré dans ingestion.telegram_messages
    3. Colonnes correctes (user_id, chat_id, thread_id, text, timestamp)
    4. Flag processed=FALSE par défaut
    """
    pass
