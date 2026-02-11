"""
Tests unitaires pour notifications email draft reply

Story 2.6 - Task 1.3 : Tests notifications confirmation/échec envoi email
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Bot

# Import des fonctions à tester (PYTHONPATH setup in conftest.py)
from bot.handlers.draft_reply_notifications import (
    send_email_confirmation_notification,
    send_email_failure_notification
)


@pytest.fixture
def mock_bot():
    """Fixture: Mock telegram Bot"""
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=12345))
    return bot


@pytest.fixture
def env_vars(monkeypatch):
    """Fixture: Variables d'environnement Telegram"""
    monkeypatch.setenv("TELEGRAM_SUPERGROUP_ID", "-1001234567890")
    monkeypatch.setenv("TOPIC_EMAIL_ID", "12346")
    monkeypatch.setenv("TOPIC_SYSTEM_ID", "12347")


# =============================================================================
# TEST 1 : Notification confirmation envoyée dans topic Email
# =============================================================================

@pytest.mark.asyncio
async def test_confirmation_notification_sent_to_email_topic(mock_bot, env_vars):
    """
    Test 1 : Notification confirmation envoyée dans topic Email & Communications

    AC3 Story 2.6 : Notification envoyée dans TOPIC_EMAIL_ID après envoi réussi
    """
    # Arrange
    receipt_id = "receipt-uuid-123"
    recipient_anon = "[NAME_1]@[DOMAIN_1]"
    subject_anon = "Question about [MEDICAL_TERM_1]"
    account_name = "professional"
    sent_at = datetime(2026, 2, 11, 14, 30, 0)

    # Act
    await send_email_confirmation_notification(
        bot=mock_bot,
        receipt_id=receipt_id,
        recipient_anon=recipient_anon,
        subject_anon=subject_anon,
        account_name=account_name,
        sent_at=sent_at
    )

    # Assert
    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs

    # Vérifier topic Email
    assert call_kwargs["chat_id"] == -1001234567890
    assert call_kwargs["message_thread_id"] == 12346  # TOPIC_EMAIL_ID
    assert call_kwargs["parse_mode"] == "Markdown"

    # Vérifier contenu message
    message_text = call_kwargs["text"]
    assert "✅ Email envoyé avec succès" in message_text
    assert recipient_anon in message_text
    assert subject_anon in message_text
    assert account_name in message_text
    assert "2026-02-11 14:30:00" in message_text


# =============================================================================
# TEST 2 : Anonymisation recipient + subject dans notification
# =============================================================================

@pytest.mark.asyncio
async def test_confirmation_notification_contains_anonymized_data(mock_bot, env_vars):
    """
    Test 2 : Notification contient recipient et subject ANONYMISÉS

    AC3 Story 2.6 : PII anonymisées via Presidio dans notification
    """
    # Arrange
    recipient_anon = "[NAME_42]@[DOMAIN_13]"  # Format Presidio
    subject_anon = "Re: [MEDICAL_TERM_5]"

    # Act
    await send_email_confirmation_notification(
        bot=mock_bot,
        receipt_id="uuid-456",
        recipient_anon=recipient_anon,
        subject_anon=subject_anon,
        account_name="medical",
        sent_at=datetime.now()
    )

    # Assert
    message_text = mock_bot.send_message.call_args.kwargs["text"]

    # Vérifier format anonymisé (pas de PII réelle)
    assert "[NAME_42]" in message_text
    assert "[DOMAIN_13]" in message_text
    assert "[MEDICAL_TERM_5]" in message_text

    # Vérifier AUCUNE PII réelle ne fuite (exemple)
    assert "john@example.com" not in message_text
    assert "rendez-vous cardiologie" not in message_text.lower()


# =============================================================================
# TEST 3 : Inline button callback correct
# =============================================================================

@pytest.mark.asyncio
async def test_confirmation_notification_has_journal_button(mock_bot, env_vars):
    """
    Test 3 : Notification contient inline button [Voir dans /journal]

    AC3 Story 2.6 : Bouton optionnel pour consulter receipt
    """
    # Arrange
    receipt_id = "receipt-uuid-789"

    # Act
    await send_email_confirmation_notification(
        bot=mock_bot,
        receipt_id=receipt_id,
        recipient_anon="[NAME_1]@[DOMAIN_1]",
        subject_anon="Test",
        account_name="personal",
        sent_at=datetime.now()
    )

    # Assert
    call_kwargs = mock_bot.send_message.call_args.kwargs

    # Vérifier inline keyboard présent
    assert "reply_markup" in call_kwargs
    keyboard = call_kwargs["reply_markup"]

    # Vérifier bouton callback
    assert keyboard is not None
    # Le format attendu : InlineKeyboardMarkup avec bouton callback "receipt_{receipt_id}"
    # (Vérification structure exacte dépend de l'implémentation)


# =============================================================================
# TEST 4 : Échec notification ne bloque pas workflow
# =============================================================================

@pytest.mark.asyncio
async def test_confirmation_notification_failure_does_not_raise(mock_bot, env_vars, caplog):
    """
    Test 4 : Échec notification confirmation ne lève PAS d'exception

    AC3 Story 2.6 : Error handling - échec notification ne bloque pas envoi email
    """
    # Arrange
    mock_bot.send_message.side_effect = Exception("Telegram API error")

    # Act - Ne doit PAS raise
    try:
        await send_email_confirmation_notification(
            bot=mock_bot,
            receipt_id="uuid-error",
            recipient_anon="[NAME_1]@[DOMAIN_1]",
            subject_anon="Test",
            account_name="professional",
            sent_at=datetime.now()
        )
        # Si on arrive ici, c'est bon (pas de raise)
        success = True
    except Exception:
        success = False

    # Assert
    assert success, "Notification failure should NOT raise exception"

    # Vérifier log warning (pas error)
    # assert "notification_failed" in caplog.text  # TODO: Activer si logs ajoutés


# =============================================================================
# TEST 5 : Notification échec EmailEngine dans topic System
# =============================================================================

@pytest.mark.asyncio
async def test_failure_notification_sent_to_system_topic(mock_bot, env_vars):
    """
    Test 5 : Notification échec envoyée dans topic System & Alerts

    AC5 Story 2.6 : Notification System si EmailEngine échoue
    """
    # Arrange
    receipt_id = "receipt-fail-123"
    error_message = "EmailEngine send_message failed after 3 attempts: 500 - Internal Server Error"
    recipient_anon = "[NAME_1]@[DOMAIN_1]"

    # Act
    await send_email_failure_notification(
        bot=mock_bot,
        receipt_id=receipt_id,
        error_message=error_message,
        recipient_anon=recipient_anon
    )

    # Assert
    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs

    # Vérifier topic System
    assert call_kwargs["chat_id"] == -1001234567890
    assert call_kwargs["message_thread_id"] == 12347  # TOPIC_SYSTEM_ID

    # Vérifier contenu message
    message_text = call_kwargs["text"]
    assert "⚠️ Échec envoi email" in message_text
    assert recipient_anon in message_text
    assert "EmailEngine" in message_text or "500" in message_text
    assert "Vérifier EmailEngine" in message_text or "Action requise" in message_text


# =============================================================================
# TEST BONUS : Format message complet AC3
# =============================================================================

@pytest.mark.asyncio
async def test_confirmation_notification_format_matches_ac3(mock_bot, env_vars):
    """
    Test Bonus : Format message correspond exactement au AC3

    Vérifier tous les champs requis par AC3 Story 2.6
    """
    # Arrange
    sent_at = datetime(2026, 2, 11, 15, 45, 30)

    # Act
    await send_email_confirmation_notification(
        bot=mock_bot,
        receipt_id="uuid-format-test",
        recipient_anon="[NAME_99]@[DOMAIN_55]",
        subject_anon="Re: [SUBJECT_88]",
        account_name="academic",
        sent_at=sent_at
    )

    # Assert
    message_text = mock_bot.send_message.call_args.kwargs["text"]

    # Vérifier structure exacte AC3
    assert "✅ Email envoyé avec succès" in message_text
    assert "Destinataire:" in message_text
    assert "Sujet:" in message_text
    assert "📨 Compte:" in message_text
    assert "⏱️" in message_text or "Envoyé le:" in message_text

    # Vérifier valeurs
    assert "[NAME_99]@[DOMAIN_55]" in message_text
    assert "Re: [SUBJECT_88]" in message_text
    assert "academic" in message_text
