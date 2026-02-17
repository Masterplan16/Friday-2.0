"""
Tests unitaires pour corrections email classification (Story 2.2, AC5).

Tests handler inline buttons catégories pour corrections email.classify.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ==========================================
# Tests handle_correct_button_email
# ==========================================


@pytest.mark.asyncio
@patch("bot.handlers.corrections.anonymize_text")
async def test_handle_correct_button_email_shows_category_buttons(mock_anonymize):
    """Test affichage inline buttons catégories pour email.classify."""
    from bot.handlers.corrections import CorrectionsHandler

    # Setup mocks
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": "00000000-0000-0000-0000-000000000123",
        "module": "email",
        "action_type": "classify",
        "input_summary": "Email from @urssaf.fr",
        "output_summary": "→ pro (0.92)",
    }

    mock_pool_ctx = AsyncMock()
    mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire = MagicMock(return_value=mock_pool_ctx)

    handler = CorrectionsHandler(mock_pool)

    # Mock Telegram Update avec callback_data
    update = MagicMock()
    update.callback_query.data = "correct_00000000-0000-0000-0000-000000000123"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {}

    # Test
    await handler.handle_correct_button(update, context)

    # Assertions
    update.callback_query.answer.assert_called_once()
    update.callback_query.message.reply_text.assert_called_once()

    # Vérifier que le message contient les catégories
    call_args = update.callback_query.message.reply_text.call_args
    assert "Quelle est la bonne catégorie" in call_args[0][0]

    # Vérifier que reply_markup est un InlineKeyboardMarkup avec 8 boutons
    reply_markup = call_args[1]["reply_markup"]
    assert isinstance(reply_markup, InlineKeyboardMarkup)

    # 8 catégories => 8 boutons (layout 2 par ligne = 4 lignes)
    buttons_flat = [btn for row in reply_markup.inline_keyboard for btn in row]
    assert len(buttons_flat) == 8

    # Vérifier que les callbacks sont corrects
    categories = ["pro", "finance", "universite", "recherche", "perso", "urgent", "spam", "inconnu"]
    for idx, btn in enumerate(buttons_flat):
        assert btn.callback_data == f"cc_{categories[idx]}_00000000-0000-0000-0000-000000000123"


@pytest.mark.asyncio
@patch("bot.handlers.corrections.anonymize_text")
async def test_handle_correct_button_email_not_found(mock_anonymize):
    """Test erreur si receipt introuvable."""
    from bot.handlers.corrections import CorrectionsHandler

    # Setup mocks
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None  # Receipt introuvable

    mock_pool_ctx = AsyncMock()
    mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire = MagicMock(return_value=mock_pool_ctx)

    handler = CorrectionsHandler(mock_pool)

    # Mock Telegram Update
    update = MagicMock()
    update.callback_query.data = "correct_99999999-9999-9999-9999-999999999999"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()

    context = MagicMock()

    # Test
    await handler.handle_correct_button(update, context)

    # Assertions - doit envoyer message erreur
    update.callback_query.message.reply_text.assert_called_once()
    call_args = update.callback_query.message.reply_text.call_args
    assert "introuvable" in call_args[0][0].lower()


@pytest.mark.asyncio
async def test_handle_correct_button_non_email_uses_text_input():
    """Test que les modules non-email utilisent toujours l'input texte libre."""
    from bot.handlers.corrections import CorrectionsHandler

    # Setup mocks
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": "00000000-0000-0000-0000-000000000456",
        "module": "archiviste",
        "action_type": "classify_doc",
        "input_summary": "Document.pdf",
        "output_summary": "→ fiscal",
    }

    mock_pool_ctx = AsyncMock()
    mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire = MagicMock(return_value=mock_pool_ctx)

    handler = CorrectionsHandler(mock_pool)

    # Mock Telegram Update
    update = MagicMock()
    update.callback_query.data = "correct_00000000-0000-0000-0000-000000000456"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {}

    # Test
    await handler.handle_correct_button(update, context)

    # Assertions - doit demander texte libre (pas de reply_markup)
    call_args = update.callback_query.message.reply_text.call_args
    assert "Quelle est la correction" in call_args[0][0]
    assert "reply_markup" not in call_args[1] or call_args[1].get("reply_markup") is None

    # Vérifier que user_data a été set pour awaiting_correction_for
    assert context.user_data["awaiting_correction_for"] == "00000000-0000-0000-0000-000000000456"


# ==========================================
# Tests handle_category_correction
# ==========================================


@pytest.mark.asyncio
async def test_handle_category_correction_success():
    """Test correction catégorie email réussie."""
    from bot.handlers.corrections import CorrectionsHandler

    # Setup mocks
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": "00000000-0000-0000-0000-000000000789",
        "module": "email",
        "action_type": "classify",
        "output_summary": "→ pro (0.92)",  # Catégorie originale
    }
    mock_conn.execute.return_value = "UPDATE 1"

    mock_pool_ctx = AsyncMock()
    mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire = MagicMock(return_value=mock_pool_ctx)

    handler = CorrectionsHandler(mock_pool)

    # Mock Telegram Update avec callback de sélection catégorie
    update = MagicMock()
    update.callback_query.data = "cc_finance_00000000-0000-0000-0000-000000000789"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.edit_text = AsyncMock()
    update.callback_query.from_user.id = 123456

    context = MagicMock()

    # Test
    await handler.handle_category_correction(update, context)

    # Assertions
    update.callback_query.answer.assert_called_once()

    # Vérifier UPDATE BDD
    mock_conn.execute.assert_called_once()
    call_args = mock_conn.execute.call_args[0]
    assert "UPDATE core.action_receipts" in call_args[0]
    assert "status = 'corrected'" in call_args[0]

    # Vérifier JSON correction
    correction_json = call_args[1]
    assert '"correct_category": "finance"' in correction_json
    assert '"original_category": "pro"' in correction_json

    # Vérifier message confirmation
    update.callback_query.message.edit_text.assert_called_once()
    confirmation_text = update.callback_query.message.edit_text.call_args[0][0]
    assert "Correction enregistrée" in confirmation_text
    assert "finance" in confirmation_text


@pytest.mark.asyncio
async def test_handle_category_correction_receipt_not_found():
    """Test erreur si receipt introuvable lors de la correction."""
    from bot.handlers.corrections import CorrectionsHandler

    # Setup mocks
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None  # Receipt introuvable

    mock_pool_ctx = AsyncMock()
    mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire = MagicMock(return_value=mock_pool_ctx)

    handler = CorrectionsHandler(mock_pool)

    # Mock Telegram Update
    update = MagicMock()
    update.callback_query.data = "cc_finance_99999999-9999-9999-9999-999999999999"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.edit_text = AsyncMock()

    context = MagicMock()

    # Test
    await handler.handle_category_correction(update, context)

    # Assertions - doit afficher erreur
    # answer() appelé 2x: 1x vide au début, 1x avec erreur
    assert update.callback_query.answer.call_count == 2
    # Deuxième appel doit contenir le message d'erreur
    second_call = update.callback_query.answer.call_args_list[1]
    assert second_call[0][0] == "Receipt introuvable"
    assert second_call[1]["show_alert"] is True
    # Pas de edit_text appelé
    update.callback_query.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_handle_category_correction_parses_category_from_output():
    """Test extraction catégorie originale depuis output_summary."""
    from bot.handlers.corrections import CorrectionsHandler

    # Setup mocks
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()

    # Différents formats output_summary possibles
    test_cases = [
        ("→ pro (0.92)", "pro"),
        ("→ finance (confidence=0.85)", "finance"),
        ("→ inconnu (0.50)", "inconnu"),
    ]

    for output_summary, expected_category in test_cases:
        mock_conn.fetchrow.return_value = {
            "id": "00000000-0000-0000-0000-000000000000",
            "module": "email",
            "action_type": "classify",
            "output_summary": output_summary,
        }
        mock_conn.execute.return_value = "UPDATE 1"

        mock_pool_ctx = AsyncMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_pool_ctx)

        handler = CorrectionsHandler(mock_pool)

        # Mock Update
        update = MagicMock()
        update.callback_query.data = f"cc_spam_00000000-0000-0000-0000-000000000000"
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.edit_text = AsyncMock()
        update.callback_query.from_user.id = 123456

        context = MagicMock()

        # Test
        await handler.handle_category_correction(update, context)

        # Vérifier que la catégorie originale extraite est correcte
        correction_json = mock_conn.execute.call_args[0][1]
        assert f'"original_category": "{expected_category}"' in correction_json
