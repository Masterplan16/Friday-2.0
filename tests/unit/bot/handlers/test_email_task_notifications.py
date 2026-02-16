"""
Tests unitaires pour notifications tâches email (Story 2.7)

AC3 : Notification topic Actions avec inline buttons
AC4 : Notification topic Email avec lien receipt

M4 fix: Tests unitaires manquants (couverture notifications)
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.agents.email.models import TaskDetected

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_bot():
    """Mock du bot Telegram"""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def sample_task():
    """Tâche exemple pour tests"""
    return TaskDetected(
        description="Envoyer le rapport médical",
        priority="high",
        due_date=datetime(2026, 2, 14, 0, 0, 0),
        confidence=0.92,
        context="Demande explicite urgente",
        priority_keywords=["urgent", "ASAP"],
    )


@pytest.fixture
def sample_tasks_multiple():
    """Multiple tâches pour tests"""
    return [
        TaskDetected(
            description="Tâche 1",
            priority="high",
            due_date=datetime(2026, 2, 14),
            confidence=0.90,
            context="Context 1",
        ),
        TaskDetected(
            description="Tâche 2",
            priority="normal",
            due_date=None,
            confidence=0.85,
            context="Context 2",
        ),
    ]


# =============================================================================
# TESTS AC3 : NOTIFICATION TOPIC ACTIONS (SINGLE TASK)
# =============================================================================


@pytest.mark.asyncio
async def test_send_task_detected_notification_single_task(mock_bot, sample_task):
    """
    AC3 : Notification single task dans topic Actions avec inline buttons

    Vérifie:
    - Message formaté avec emojis priorité
    - Inline buttons [Approve] [Reject]
    - Callback data format correct (C1 fix)
    """
    from bot.handlers.email_task_notifications import send_task_detected_notification

    # Test
    await send_task_detected_notification(
        bot=mock_bot,
        receipt_id="abc-123-def-456",
        tasks=[sample_task],
        sender_anon="[PERSON_1]",
        subject_anon="[SUBJECT_ANON]",
    )

    # Assertions
    assert mock_bot.send_message.called
    call_args = mock_bot.send_message.call_args

    # Vérifier arguments
    assert call_args.kwargs["chat_id"] is not None
    assert call_args.kwargs["message_thread_id"] is not None
    assert call_args.kwargs["parse_mode"] == "Markdown"

    # Vérifier message
    message_text = call_args.kwargs["text"]
    assert "📋 Nouvelle tâche détectée" in message_text
    assert "Envoyer le rapport médical" in message_text
    assert "🔴" in message_text  # Emoji priorité high
    assert "92%" in message_text  # Confidence

    # Vérifier inline buttons (C1 fix: format simplifié)
    keyboard = call_args.kwargs["reply_markup"]
    buttons = keyboard.inline_keyboard[0]
    assert len(buttons) == 2  # Approve + Reject (Modify SKIPPED MVP)
    assert buttons[0].callback_data == "approve_abc-123-def-456"
    assert buttons[1].callback_data == "reject_abc-123-def-456"


# =============================================================================
# TESTS AC3 : NOTIFICATION TOPIC ACTIONS (MULTIPLE TASKS)
# =============================================================================


@pytest.mark.asyncio
async def test_send_task_detected_notification_multiple_tasks(mock_bot, sample_tasks_multiple):
    """
    AC3 : Notification multiple tasks avec résumé

    Vérifie:
    - Liste tâches numérotée
    - Confidence moyenne affichée
    - Format compact (dates DD/MM)
    """
    from bot.handlers.email_task_notifications import send_task_detected_notification

    await send_task_detected_notification(
        bot=mock_bot,
        receipt_id="multi-task-receipt",
        tasks=sample_tasks_multiple,
        sender_anon="[SENDER]",
        subject_anon="[SUBJECT]",
    )

    # Assertions
    call_args = mock_bot.send_message.call_args
    message_text = call_args.kwargs["text"]

    assert "2 tâches détectées" in message_text
    assert "1. 🔴 Tâche 1" in message_text
    assert "2. 🟡 Tâche 2" in message_text
    assert "Confiance moyenne" in message_text


# =============================================================================
# TESTS AC4 : NOTIFICATION TOPIC EMAIL
# =============================================================================


@pytest.mark.asyncio
async def test_send_email_task_summary_notification(mock_bot):
    """
    AC4 : Notification résumé dans topic Email avec lien /receipt

    Vérifie:
    - Message résumé concis
    - Lien /receipt présent
    - Topic Email utilisé
    """
    from bot.handlers.email_task_notifications import send_email_task_summary_notification

    await send_email_task_summary_notification(
        bot=mock_bot,
        receipt_id="summary-receipt-123",
        tasks_count=3,
        sender_anon="[SENDER_ANON]",
        subject_anon="[SUBJECT_ANON]",
    )

    # Assertions
    assert mock_bot.send_message.called
    call_args = mock_bot.send_message.call_args

    message_text = call_args.kwargs["text"]
    assert "📧 Email traité avec" in message_text
    assert "3 tâches détectées" in message_text
    assert "/receipt summary-receipt-123" in message_text


# =============================================================================
# TESTS ERROR HANDLING
# =============================================================================


@pytest.mark.asyncio
async def test_send_notification_handles_telegram_error_gracefully(mock_bot, sample_task):
    """
    Vérifier que erreur Telegram ne crash pas le processus

    Si send_message échoue, logger error mais pas de raise
    """
    from bot.handlers.email_task_notifications import send_task_detected_notification

    # Mock erreur Telegram
    mock_bot.send_message.side_effect = Exception("Telegram API error")

    # Test - ne doit PAS raise
    await send_task_detected_notification(
        bot=mock_bot,
        receipt_id="error-test",
        tasks=[sample_task],
        sender_anon="[SENDER]",
        subject_anon="[SUBJECT]",
    )

    # Assertion: fonction complète sans raise
    assert True


# =============================================================================
# TESTS EDGE CASES
# =============================================================================


@pytest.mark.asyncio
async def test_notification_with_task_no_due_date(mock_bot):
    """Tâche sans date échéance → Affiche 'Non définie'"""
    from bot.handlers.email_task_notifications import send_task_detected_notification

    task_no_date = TaskDetected(
        description="Tâche sans deadline",
        priority="normal",
        due_date=None,
        confidence=0.80,
        context="Test",
    )

    await send_task_detected_notification(
        bot=mock_bot,
        receipt_id="no-date",
        tasks=[task_no_date],
        sender_anon="[S]",
        subject_anon="[S]",
    )

    call_args = mock_bot.send_message.call_args
    message_text = call_args.kwargs["text"]
    assert "Non définie" in message_text


@pytest.mark.asyncio
async def test_notification_priority_emojis(mock_bot):
    """Vérifier emojis priorité corrects"""
    from bot.handlers.email_task_notifications import send_task_detected_notification

    # Test priorité low
    task_low = TaskDetected(
        description="Low priority", priority="low", due_date=None, confidence=0.75, context="Test"
    )

    await send_task_detected_notification(
        bot=mock_bot,
        receipt_id="low-priority",
        tasks=[task_low],
        sender_anon="[S]",
        subject_anon="[S]",
    )

    call_args = mock_bot.send_message.call_args
    message_text = call_args.kwargs["text"]
    assert "🟢" in message_text  # Emoji low priority
