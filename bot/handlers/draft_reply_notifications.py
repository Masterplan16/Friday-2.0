"""
Notifications Telegram pour brouillons emails

Envoie notifications dans topic Actions lorsqu'un brouillon est prêt,
avec inline buttons pour validation (Approve/Reject/Edit).

Story: 2.5 Brouillon Réponse Email - Task 5 Subtask 5.1
"""

import logging
from typing import Optional
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


async def send_draft_ready_notification(
    bot: Bot,
    receipt_id: str,
    email_from_anon: str,
    subject_anon: str,
    draft_body: str,
    supergroup_id: int,
    topic_actions_id: int
) -> None:
    """
    Notifier brouillon email prêt avec inline buttons validation

    Envoie notification dans topic Actions & Validations avec 3 boutons:
    - [Approve] : Approuver et envoyer email
    - [Reject] : Rejeter brouillon
    - [Edit] : Modifier brouillon (stub MVP, fonctionnalité future)

    Args:
        bot: Instance telegram.Bot
        receipt_id: ID du receipt (core.action_receipts)
        email_from_anon: Email expéditeur anonymisé (via Presidio)
        subject_anon: Sujet email anonymisé (via Presidio)
        draft_body: Corps brouillon généré par Claude
        supergroup_id: ID du supergroup Telegram
        topic_actions_id: ID du topic Actions & Validations

    Raises:
        Exception: Si envoi Telegram échoue

    Example:
        >>> await send_draft_ready_notification(
        ...     bot=bot,
        ...     receipt_id="receipt-uuid-123",
        ...     email_from_anon="[NAME_1]@[DOMAIN_1]",
        ...     subject_anon="Question about [MEDICAL_TERM_1]",
        ...     draft_body="Bonjour,\\n\\nVoici ma réponse.\\n\\nCordialement,\\nDr. Lopez",
        ...     supergroup_id=-1001234567890,
        ...     topic_actions_id=12345
        ... )
    """

    # Truncate draft body si trop long (max 500 chars pour notification)
    draft_preview = draft_body if len(draft_body) <= 500 else draft_body[:500] + "..."

    # Format message
    message_text = f"""📝 **Brouillon réponse email prêt**

**De:** {email_from_anon}
**Sujet:** Re: {subject_anon}

**Brouillon:**
---
{draft_preview}
---

Voulez-vous envoyer ce brouillon ?
"""

    # Inline keyboard avec 3 boutons
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{receipt_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{receipt_id}"),
            InlineKeyboardButton("✏️ Edit", callback_data=f"edit_{receipt_id}")
        ]
    ])

    try:
        # Envoyer dans topic Actions & Validations
        await bot.send_message(
            chat_id=supergroup_id,
            message_thread_id=topic_actions_id,
            text=message_text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )

        logger.info(
            "draft_ready_notification_sent",
            receipt_id=receipt_id,
            topic_id=topic_actions_id
        )

    except Exception as e:
        logger.error(
            "draft_ready_notification_failed",
            receipt_id=receipt_id,
            error=str(e),
            exc_info=True
        )
        raise


async def send_draft_sent_confirmation(
    bot: Bot,
    receipt_id: str,
    subject_anon: str,
    supergroup_id: int,
    topic_email_id: int
) -> None:
    """
    Notifier email envoyé après validation Approve

    Envoie notification dans topic Email & Communications pour confirmer
    l'envoi réussi de l'email.

    Args:
        bot: Instance telegram.Bot
        receipt_id: ID du receipt
        subject_anon: Sujet email anonymisé
        supergroup_id: ID du supergroup Telegram
        topic_email_id: ID du topic Email & Communications

    Example:
        >>> await send_draft_sent_confirmation(
        ...     bot=bot,
        ...     receipt_id="receipt-uuid-123",
        ...     subject_anon="Re: Question about [MEDICAL_TERM_1]",
        ...     supergroup_id=-1001234567890,
        ...     topic_email_id=12346
        ... )
    """

    message_text = f"""✅ **Email envoyé**

**Sujet:** {subject_anon}

Le brouillon a été approuvé et envoyé avec succès.
"""

    try:
        await bot.send_message(
            chat_id=supergroup_id,
            message_thread_id=topic_email_id,
            text=message_text,
            parse_mode="Markdown"
        )

        logger.info(
            "draft_sent_confirmation_sent",
            receipt_id=receipt_id,
            topic_id=topic_email_id
        )

    except Exception as e:
        logger.error(
            "draft_sent_confirmation_failed",
            receipt_id=receipt_id,
            error=str(e),
            exc_info=True
        )
        # Ne pas raise - notification confirmation n'est pas critique


# =============================================================================
# Story 2.6 - Nouvelles fonctions de notification
# =============================================================================

async def send_email_confirmation_notification(
    bot: Bot,
    receipt_id: str,
    recipient_anon: str,
    subject_anon: str,
    account_name: str,
    sent_at
) -> None:
    """
    Notifier envoi email réussi dans topic Email & Communications

    Envoie notification détaillée après envoi EmailEngine réussi,
    conforme au AC3 Story 2.6.

    Args:
        bot: Instance telegram.Bot
        receipt_id: ID du receipt (core.action_receipts)
        recipient_anon: Email destinataire anonymisé (via Presidio)
        subject_anon: Sujet email anonymisé (via Presidio)
        account_name: Nom du compte IMAP (professional/medical/academic/personal)
        sent_at: Timestamp envoi (datetime)

    Example:
        >>> from datetime import datetime
        >>> await send_email_confirmation_notification(
        ...     bot=bot,
        ...     receipt_id="uuid-123",
        ...     recipient_anon="[NAME_1]@[DOMAIN_1]",
        ...     subject_anon="Re: Question about [MEDICAL_TERM_1]",
        ...     account_name="professional",
        ...     sent_at=datetime(2026, 2, 11, 14, 30, 0)
        ... )
    """
    import os

    # Get env vars
    supergroup_id = int(os.getenv("TELEGRAM_SUPERGROUP_ID", "-1001234567890"))
    topic_email_id = int(os.getenv("TOPIC_EMAIL_ID", "12346"))

    # Format timestamp
    timestamp_str = sent_at.strftime('%Y-%m-%d %H:%M:%S')

    # Format message conforme AC3
    message_text = f"""✅ Email envoyé avec succès

Destinataire: {recipient_anon}
Sujet: Re: {subject_anon}

📨 Compte: {account_name}
⏱️  Envoyé le: {timestamp_str}
"""

    # Inline button optionnel [Voir dans /journal]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📋 Voir dans /journal",
            callback_data=f"receipt_{receipt_id}"
        )]
    ])

    try:
        await bot.send_message(
            chat_id=supergroup_id,
            message_thread_id=topic_email_id,
            text=message_text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )

        logger.info(
            "email_confirmation_notification_sent",
            receipt_id=receipt_id,
            topic="Email"
        )

    except Exception as e:
        # Échec notification ne bloque pas workflow (AC3)
        logger.warning(
            "email_confirmation_notification_failed",
            receipt_id=receipt_id,
            error=str(e)
        )
        # Ne PAS raise - notification = best effort
        pass  # Explicite: ne rien faire, continuer


async def send_email_failure_notification(
    bot: Bot,
    receipt_id: str,
    error_message: str,
    recipient_anon: str
) -> None:
    """
    Notifier échec envoi email dans topic System & Alerts

    Envoie alerte System si EmailEngine échoue après retries,
    conforme au AC5 Story 2.6.

    Args:
        bot: Instance telegram.Bot
        receipt_id: ID du receipt
        error_message: Message erreur EmailEngine
        recipient_anon: Email destinataire anonymisé

    Example:
        >>> await send_email_failure_notification(
        ...     bot=bot,
        ...     receipt_id="uuid-fail",
        ...     error_message="EmailEngine send failed: 500 Internal Server Error",
        ...     recipient_anon="[NAME_1]@[DOMAIN_1]"
        ... )
    """
    import os

    # Get env vars
    supergroup_id = int(os.getenv("TELEGRAM_SUPERGROUP_ID", "-1001234567890"))
    topic_system_id = int(os.getenv("TOPIC_SYSTEM_ID", "12347"))

    # Truncate error message si trop long (max 200 chars)
    error_truncated = error_message[:200] if len(error_message) > 200 else error_message

    # Format message conforme AC5
    message_text = f"""⚠️ Échec envoi email

Destinataire: {recipient_anon}
Erreur: {error_truncated}

Action requise: Vérifier EmailEngine + compte IMAP
Receipt ID: {receipt_id}
"""

    try:
        await bot.send_message(
            chat_id=supergroup_id,
            message_thread_id=topic_system_id,
            text=message_text,
            parse_mode="Markdown"
        )

        logger.error(
            "email_failure_notification_sent",
            receipt_id=receipt_id,
            topic="System"
        )

    except Exception as e:
        # Log error mais ne raise pas (notification = best effort)
        logger.error(
            "email_failure_notification_failed",
            receipt_id=receipt_id,
            error=str(e)
        )
        pass  # Explicite: ne rien faire, continuer
