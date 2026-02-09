"""
Tests unitaires pour bot/handlers/corrections.py (Story 1.7, Task 2.3).

Teste la capture des corrections Antonio via inline button [Correct].
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from telegram import Update, CallbackQuery, Message, User, Chat
from telegram.ext import ContextTypes

from bot.handlers.corrections import CorrectionsHandler


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg Pool pour tests."""
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    conn.execute = AsyncMock(return_value="UPDATE 1")  # Success
    return pool


@pytest.fixture
def mock_update_correct_button():
    """Mock Update pour bouton [Correct] cliqué."""
    update = Mock(spec=Update)
    update.callback_query = Mock(spec=CallbackQuery)
    update.callback_query.answer = AsyncMock()
    update.callback_query.data = "correct_abc123-def4-5678-9012-345678901234"
    update.callback_query.from_user = Mock(spec=User)
    update.callback_query.from_user.id = 12345
    update.callback_query.message = Mock(spec=Message)
    update.callback_query.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_update_correction_text():
    """Mock Update pour texte correction."""
    update = Mock(spec=Update)
    update.message = Mock(spec=Message)
    update.message.text = "URSSAF → finance"
    update.effective_user = Mock(spec=User)
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Mock Context avec user_data."""
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {}
    return context


@pytest.mark.asyncio
async def test_handle_correct_button_stores_receipt_id(
    mock_db_pool, mock_update_correct_button, mock_context
):
    """
    Test : Bouton [Correct] stocke receipt_id dans user_data.

    Workflow:
    1. Antonio clique [Correct] sur notification
    2. Handler stocke receipt_id dans context.user_data
    3. Handler demande texte correction à Antonio
    """
    handler = CorrectionsHandler(mock_db_pool)

    await handler.handle_correct_button(mock_update_correct_button, mock_context)

    # Vérifier receipt_id stocké dans user_data
    assert "awaiting_correction_for" in mock_context.user_data
    assert mock_context.user_data["awaiting_correction_for"] == "abc123-def4-5678-9012-345678901234"

    # Vérifier message envoyé à Antonio
    mock_update_correct_button.callback_query.message.reply_text.assert_called_once()
    call_args = mock_update_correct_button.callback_query.message.reply_text.call_args
    assert "Correction action" in call_args[0][0]
    assert "abc123" in call_args[0][0]  # Affiche début du receipt_id


@pytest.mark.asyncio
async def test_handle_correction_text_updates_receipt(
    mock_db_pool, mock_update_correction_text, mock_context
):
    """
    Test : Texte correction met à jour core.action_receipts (AC1, AC2).

    Workflow:
    1. user_data contient receipt_id en attente
    2. Antonio envoie texte correction
    3. Handler UPDATE core.action_receipts SET correction, status='corrected'
    """
    handler = CorrectionsHandler(mock_db_pool)

    # Simuler correction en attente
    mock_context.user_data["awaiting_correction_for"] = "abc123-def4-5678-9012-345678901234"

    await handler.handle_correction_text(mock_update_correction_text, mock_context)

    # Vérifier UPDATE SQL exécuté
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.execute.assert_called_once()
    sql_call = conn.execute.call_args[0][0]
    assert "UPDATE core.action_receipts" in sql_call
    assert "SET correction = $1" in sql_call
    assert "status = 'corrected'" in sql_call

    # Vérifier paramètres SQL
    params = conn.execute.call_args[0][1:]
    assert params[0] == "URSSAF → finance"  # correction
    assert "Antonio" in params[1]  # feedback_comment
    assert params[2] == "abc123-def4-5678-9012-345678901234"  # receipt_id

    # Vérifier user_data nettoyé
    assert "awaiting_correction_for" not in mock_context.user_data

    # Vérifier confirmation à Antonio
    mock_update_correction_text.message.reply_text.assert_called_once()
    confirmation = mock_update_correction_text.message.reply_text.call_args[0][0]
    assert "Correction enregistrée" in confirmation


@pytest.mark.asyncio
async def test_handle_correction_text_without_awaiting_does_nothing(
    mock_db_pool, mock_update_correction_text, mock_context
):
    """
    Test : Texte correction sans awaiting_correction_for ne fait rien.

    Scénario:
    - user_data est vide (pas de correction en attente)
    - Handler retourne None (laisse passer au handler général)
    """
    handler = CorrectionsHandler(mock_db_pool)

    # Pas de correction en attente
    assert "awaiting_correction_for" not in mock_context.user_data

    result = await handler.handle_correction_text(mock_update_correction_text, mock_context)

    # Handler ne fait rien (retourne None)
    assert result is None

    # Aucun UPDATE SQL exécuté
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_handle_correction_text_receipt_not_found_error(
    mock_db_pool, mock_update_correction_text, mock_context
):
    """
    Test : Erreur si receipt_id introuvable dans BDD.

    Scénario:
    - UPDATE retourne "UPDATE 0" (aucune ligne modifiée)
    - Handler envoie message d'erreur à Antonio
    """
    handler = CorrectionsHandler(mock_db_pool)

    # Simuler UPDATE 0 (receipt introuvable)
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.execute.return_value = "UPDATE 0"

    # Simuler correction en attente
    mock_context.user_data["awaiting_correction_for"] = "nonexistent-receipt-id"

    await handler.handle_correction_text(mock_update_correction_text, mock_context)

    # Vérifier message d'erreur envoyé
    mock_update_correction_text.message.reply_text.assert_called_once()
    error_msg = mock_update_correction_text.message.reply_text.call_args[0][0]
    assert "Erreur" in error_msg


@pytest.mark.asyncio
async def test_handle_correction_text_db_exception_error(
    mock_db_pool, mock_update_correction_text, mock_context
):
    """
    Test : Exception DB gérée gracefully avec message erreur.

    Scénario:
    - conn.execute raise Exception (DB down, timeout, etc.)
    - Handler catch exception et envoie message erreur à Antonio
    """
    handler = CorrectionsHandler(mock_db_pool)

    # Simuler exception DB
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.execute.side_effect = Exception("Database connection lost")

    # Simuler correction en attente
    mock_context.user_data["awaiting_correction_for"] = "abc123"

    await handler.handle_correction_text(mock_update_correction_text, mock_context)

    # Vérifier message d'erreur envoyé
    mock_update_correction_text.message.reply_text.assert_called_once()
    error_msg = mock_update_correction_text.message.reply_text.call_args[0][0]
    assert "Erreur" in error_msg
    assert "Database connection lost" in error_msg
