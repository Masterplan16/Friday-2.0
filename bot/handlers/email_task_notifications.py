"""
Notifications Telegram pour tâches détectées depuis emails (Story 2.7)

AC3 : Notification topic Actions avec inline buttons
AC4 : Notification topic Email avec lien receipt
"""

import logging
import os
from datetime import datetime
from typing import List

from agents.src.agents.email.models import TaskDetected
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

# Env vars Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_SUPERGROUP_ID = os.environ.get("TELEGRAM_SUPERGROUP_ID")

# H3 fix: Validation topic IDs au démarrage (fail-fast)
_TOPIC_ACTIONS_ID_STR = os.environ.get("TOPIC_ACTIONS_ID")
_TOPIC_EMAIL_ID_STR = os.environ.get("TOPIC_EMAIL_ID")

if not _TOPIC_ACTIONS_ID_STR or _TOPIC_ACTIONS_ID_STR == "0":
    raise ValueError(
        "TOPIC_ACTIONS_ID environment variable is required and must be non-zero. "
        "Extract thread IDs using scripts/extract_telegram_thread_ids.py"
    )

if not _TOPIC_EMAIL_ID_STR or _TOPIC_EMAIL_ID_STR == "0":
    raise ValueError(
        "TOPIC_EMAIL_ID environment variable is required and must be non-zero. "
        "Extract thread IDs using scripts/extract_telegram_thread_ids.py"
    )

TOPIC_ACTIONS_ID = int(_TOPIC_ACTIONS_ID_STR)
TOPIC_EMAIL_ID = int(_TOPIC_EMAIL_ID_STR)


async def send_task_detected_notification(
    bot,  # C2 fix: Bot async passé en paramètre
    receipt_id: str,
    tasks: List[TaskDetected],
    sender_anon: str,
    subject_anon: str,
) -> None:
    """
    Envoyer notification tâche(s) détectée(s) dans topic Actions avec inline buttons

    AC3 : Trust level propose + validation Telegram

    Args:
        bot: Instance Bot Telegram async (from context.bot)
        receipt_id: UUID receipt (core.action_receipts)
        tasks: Liste tâches détectées (1-N)
        sender_anon: Sender anonymisé via Presidio
        subject_anon: Subject anonymisé via Presidio

    Notes:
        - Topic Actions (Actions & Validations)
        - Inline buttons : Approve / Reject (Modify SKIPPED MVP)
        - Anonymisation déjà appliquée (sender + subject)
    """

    # Formater priorité emoji
    priority_emoji = {"high": "🔴", "normal": "🟡", "low": "🟢"}

    # Construire message
    if len(tasks) == 1:
        # Single task
        task = tasks[0]
        emoji = priority_emoji.get(task.priority, "🟡")
        due_date_str = task.due_date.strftime("%d %B") if task.due_date else "Non définie"

        message_text = f"""📋 Nouvelle tâche détectée depuis email

📧 Email : {sender_anon}
📄 Sujet : {subject_anon}

✅ **Tâche** : {task.description}
📅 Échéance : {due_date_str}
{emoji} Priorité : {task.priority.capitalize()}
🤖 Confiance : {int(task.confidence * 100)}%"""

    else:
        # Multiple tasks
        message_text = f"""📋 {len(tasks)} tâches détectées depuis email

📧 Email : {sender_anon}
📄 Sujet : {subject_anon}

**Tâches détectées** :
"""
        for i, task in enumerate(tasks, 1):
            emoji = priority_emoji.get(task.priority, "🟡")
            due_date_str = task.due_date.strftime("%d/%m") if task.due_date else "—"
            message_text += f"\n{i}. {emoji} {task.description} (échéance: {due_date_str})"

        # Confidence moyenne
        confidence_avg = sum(t.confidence for t in tasks) / len(tasks)
        message_text += f"\n\n🤖 Confiance moyenne : {int(confidence_avg * 100)}%"

    # Inline buttons (C1 fix: Utiliser pattern générique compatible Story 1.10)
    # Pattern callbacks.py: ^approve_[uuid]$ et ^reject_[uuid]$
    # Note: [Modifier] n'est pas implémenté MVP (Task 4 SKIPPED)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Créer tâche(s)", callback_data=f"approve_{receipt_id}"),
            InlineKeyboardButton("❌ Ignorer", callback_data=f"reject_{receipt_id}")
        ]
    ])

    # Send to topic Actions
    try:
        await bot.send_message(
            chat_id=TELEGRAM_SUPERGROUP_ID,
            message_thread_id=TOPIC_ACTIONS_ID,
            text=message_text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        logger.info(
            "task_notification_sent_actions",
            receipt_id=receipt_id,
            tasks_count=len(tasks),
            topic="Actions"
        )
    except Exception as e:
        logger.error(
            "task_notification_failed_actions",
            receipt_id=receipt_id,
            error=str(e),
            exc_info=True
        )


async def send_email_task_summary_notification(
    bot,  # C2 fix: Bot async passé en paramètre
    receipt_id: str,
    tasks_count: int,
    sender_anon: str,
    subject_anon: str,
) -> None:
    """
    Envoyer notification résumé email avec tâche(s) dans topic Email

    AC4 : Notification topic Email + lien receipt

    Args:
        bot: Instance Bot Telegram async (from context.bot)
        receipt_id: UUID receipt (core.action_receipts)
        tasks_count: Nombre de tâches détectées
        sender_anon: Sender anonymisé
        subject_anon: Subject anonymisé

    Notes:
        - Topic Email (Email & Communications)
        - Lien vers /receipt pour détails complets
    """

    # L2 fix: Pluriels français corrects
    task_word = "tâches détectées" if tasks_count > 1 else "tâche détectée"

    message_text = f"""📧 Email traité avec {task_word}

De : {sender_anon}
Sujet : {subject_anon}

📋 {tasks_count} {task_word}
🔗 Voir détails : `/receipt {receipt_id}`"""

    # Send to topic Email
    try:
        await bot.send_message(
            chat_id=TELEGRAM_SUPERGROUP_ID,
            message_thread_id=TOPIC_EMAIL_ID,
            text=message_text,
            parse_mode="Markdown"
        )
        logger.info(
            "task_notification_sent_email",
            receipt_id=receipt_id,
            tasks_count=tasks_count,
            topic="Email"
        )
    except Exception as e:
        logger.error(
            "task_notification_failed_email",
            receipt_id=receipt_id,
            error=str(e),
            exc_info=True
        )
