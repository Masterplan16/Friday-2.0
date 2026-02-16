"""
Helper Telegram pour envoi notifications Heartbeat (Story 4.1 Task 7)

Fonctions utilitaires pour envoyer messages Telegram aux topics Friday.
Utilisé par HeartbeatEngine et CheckExecutor.
"""

import os
from typing import Optional

import structlog
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

logger = structlog.get_logger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Singleton Bot Telegram
_telegram_bot: Optional[Bot] = None

def _get_supergroup_id() -> Optional[str]:
    return os.getenv("TELEGRAM_SUPERGROUP_ID")

def _get_topic_chat_proactive_id() -> Optional[str]:
    return os.getenv("TOPIC_CHAT_PROACTIVE_ID")

def _get_topic_system_id() -> Optional[str]:
    return os.getenv("TOPIC_SYSTEM_ID")


# ============================================================================
# BOT TELEGRAM SINGLETON
# ============================================================================

def get_telegram_bot() -> Optional[Bot]:
    """
    Retourne instance Bot Telegram (singleton).

    Returns:
        Bot Telegram ou None si TELEGRAM_BOT_TOKEN non défini
    """
    global _telegram_bot

    if _telegram_bot is not None:
        return _telegram_bot

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set - notifications disabled")
        return None

    _telegram_bot = Bot(token=token)
    logger.info("Telegram bot initialized")

    return _telegram_bot


# ============================================================================
# ENVOI NOTIFICATIONS
# ============================================================================

async def send_to_chat_proactive(
    message: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML"
) -> bool:
    """
    Envoie notification au Topic Chat & Proactive (DEFAULT).

    Args:
        message: Message à envoyer
        keyboard: Inline keyboard (optionnel)
        parse_mode: Mode formatage (HTML ou Markdown)

    Returns:
        True si envoyé, False sinon
    """
    bot = get_telegram_bot()
    if bot is None:
        logger.debug("Telegram bot not available - notification skipped")
        return False

    supergroup_id = _get_supergroup_id()
    topic_id = _get_topic_chat_proactive_id()

    if not supergroup_id or not topic_id:
        logger.warning(
            "TELEGRAM_SUPERGROUP_ID or TOPIC_CHAT_PROACTIVE_ID not set - notification skipped"
        )
        return False

    try:
        await bot.send_message(
            chat_id=int(supergroup_id),
            message_thread_id=int(topic_id),
            text=message,
            parse_mode=parse_mode,
            reply_markup=keyboard
        )

        logger.info(
            "Heartbeat notification sent",
            topic="Chat & Proactive",
            message_preview=message[:50]
        )

        return True

    except TelegramError as e:
        logger.error(
            "Failed to send Heartbeat notification",
            topic="Chat & Proactive",
            error=str(e)
        )
        return False


async def send_to_system_alerts(
    message: str,
    parse_mode: str = "HTML"
) -> bool:
    """
    Envoie alerte au Topic System & Alerts.

    Args:
        message: Message alerte
        parse_mode: Mode formatage (HTML ou Markdown)

    Returns:
        True si envoyé, False sinon
    """
    bot = get_telegram_bot()
    if bot is None:
        logger.debug("Telegram bot not available - alert skipped")
        return False

    supergroup_id = _get_supergroup_id()
    system_topic_id = _get_topic_system_id()

    if not supergroup_id or not system_topic_id:
        logger.warning(
            "TELEGRAM_SUPERGROUP_ID or TOPIC_SYSTEM_ID not set - alert skipped"
        )
        return False

    try:
        await bot.send_message(
            chat_id=int(supergroup_id),
            message_thread_id=int(system_topic_id),
            text=message,
            parse_mode=parse_mode
        )

        logger.info(
            "System alert sent",
            topic="System & Alerts",
            message_preview=message[:50]
        )

        return True

    except TelegramError as e:
        logger.error(
            "Failed to send System alert",
            topic="System & Alerts",
            error=str(e)
        )
        return False


# ============================================================================
# FORMATAGE MESSAGES HEARTBEAT
# ============================================================================

def format_heartbeat_message(
    check_id: str,
    message: str,
    emoji: str = "🔔"
) -> str:
    """
    Formate message notification Heartbeat.

    Format: [Heartbeat] <emoji> <check_id> : <message>

    Args:
        check_id: Identifiant check
        message: Message du check
        emoji: Emoji associé

    Returns:
        Message HTML formaté
    """
    # Nettoyer check_id pour affichage (remove "check_" prefix)
    display_name = check_id.replace("check_", "").replace("_", " ").title()

    return (
        f"[<b>Heartbeat</b>] {emoji} <b>{_html_escape(display_name)}</b>\n\n"
        f"{_html_escape(message)}"
    )


def create_action_keyboard(action: str, check_id: str) -> InlineKeyboardMarkup:
    """
    Crée inline keyboard pour actions Heartbeat.

    Args:
        action: Type d'action (ex: "view_urgent_emails")
        check_id: Identifiant check

    Returns:
        InlineKeyboardMarkup avec boutons d'action
    """
    # Mapping actions → boutons
    action_buttons = {
        "view_urgent_emails": [
            InlineKeyboardButton(
                "📬 Voir emails urgents",
                callback_data=f"heartbeat_action:{action}:{check_id}"
            )
        ],
        "view_financial_alerts": [
            InlineKeyboardButton(
                "💰 Voir alertes finance",
                callback_data=f"heartbeat_action:{action}:{check_id}"
            )
        ],
        "view_thesis_reminders": [
            InlineKeyboardButton(
                "🎓 Voir thésards",
                callback_data=f"heartbeat_action:{action}:{check_id}"
            )
        ],
    }

    buttons = action_buttons.get(action, [])

    if not buttons:
        # Action inconnue → bouton générique
        buttons = [
            InlineKeyboardButton(
                "🔍 Détails",
                callback_data=f"heartbeat_action:{action}:{check_id}"
            )
        ]

    return InlineKeyboardMarkup([buttons])


def _html_escape(text: str) -> str:
    """Echappe caractères spéciaux HTML pour Telegram parse_mode=HTML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
