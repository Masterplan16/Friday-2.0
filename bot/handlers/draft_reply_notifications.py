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
