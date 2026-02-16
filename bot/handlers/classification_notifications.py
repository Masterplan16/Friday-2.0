"""
Notifications Telegram pour classification documents (Story 3.2 Task 5.2-5.5)

Envoie notifications dans Topic Actions & Validations avec inline buttons
pour validation Mainteneur (trust=propose Day 1).
Notifications Metrics (succès) et System (erreurs/low confidence).
"""

import logging
import os
from typing import Dict, Any, Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

EMOJI_FOLDER = "📁"
EMOJI_CATEGORY = "🏷️"
EMOJI_CONFIDENCE = "📊"
EMOJI_PATH = "📂"
EMOJI_DOC = "📄"
EMOJI_WARNING = "⚠️"
EMOJI_ERROR = "❌"
EMOJI_SUCCESS = "✅"

# Mapping catégories → labels français
CATEGORY_LABELS = {
    "pro": "Professionnel (cabinet médical)",
    "finance": "Finance",
    "universite": "Université (enseignement)",
    "recherche": "Recherche scientifique",
    "perso": "Personnel",
}

# Mapping périmètres finance → labels français
FINANCE_LABELS = {
    "selarl": "SELARL (cabinet médical)",
    "scm": "SCM (Société Civile de Moyens)",
    "sci_ravas": "SCI Ravas",
    "sci_malbosc": "SCI Malbosc",
    "personal": "Personnel",
}


# ============================================================================
# NOTIFICATION TOPIC ACTIONS (Task 5.2 - trust=propose)
# ============================================================================


async def send_classification_proposal(
    bot: Bot, topic_id: int, supergroup_id: int, classification_data: Dict[str, Any]
) -> bool:
    """
    Envoie notification classification dans Topic Actions avec inline buttons.

    Format message :
    📁 Document classifié (validation requise)

    📄 Document : doc-123
    🏷️ Catégorie : Finance > SELARL
    📂 Destination : finance/selarl
    📊 Confiance : 94%

    [Approuver] [Corriger destination] [Rejeter]

    Args:
        bot: Instance Bot Telegram
        topic_id: Thread ID du Topic Actions & Validations
        supergroup_id: Chat ID du supergroup Friday
        classification_data: Données classification (document_id, category, subcategory,
                           path, confidence, reasoning, receipt_id)

    Returns:
        True si notification envoyée, False sinon

    Story 3.2 Task 5.2: Notification Topic Actions avec inline buttons
    """
    try:
        message = _format_classification_message(classification_data)
        receipt_id = classification_data.get("receipt_id", classification_data["document_id"])
        keyboard = _create_classification_keyboard(receipt_id)

        await bot.send_message(
            chat_id=supergroup_id,
            message_thread_id=topic_id,
            text=message,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        logger.info(
            "classification_notification_sent",
            document_id=classification_data["document_id"],
            topic="Actions",
            category=classification_data["category"],
        )

        return True

    except TelegramError as e:
        logger.error(
            "classification_notification_failed",
            document_id=classification_data.get("document_id"),
            error=str(e),
            exc_info=True,
        )
        return False


# ============================================================================
# NOTIFICATION TOPIC METRICS (Task 5.4 - classification succès)
# ============================================================================


async def send_classification_success(
    bot: Bot,
    topic_id: int,
    supergroup_id: int,
    classification_data: Dict[str, Any],
    latency_ms: Optional[float] = None,
) -> bool:
    """
    Envoie notification succès classification dans Topic Metrics.

    Args:
        bot: Instance Bot Telegram
        topic_id: Thread ID du Topic Metrics & Logs
        supergroup_id: Chat ID du supergroup Friday
        classification_data: Données classification
        latency_ms: Latence totale en ms (optionnel)

    Returns:
        True si envoyé, False sinon

    Story 3.2 Task 5.4: Notification Topic Metrics
    """
    try:
        category = classification_data["category"]
        subcategory = classification_data.get("subcategory")
        confidence = classification_data.get("confidence", 0.0)
        document_id = classification_data["document_id"]
        confidence_pct = int(confidence * 100)

        cat_display = CATEGORY_LABELS.get(category, category)
        if subcategory and category == "finance":
            cat_display += f" > {FINANCE_LABELS.get(subcategory, subcategory)}"

        message = (
            f"{EMOJI_SUCCESS} <b>Document classifié</b>\n\n"
            f"{EMOJI_DOC} {_html_escape(document_id[:20])}\n"
            f"{EMOJI_CATEGORY} {_html_escape(cat_display)}\n"
            f"{EMOJI_CONFIDENCE} Confiance : {confidence_pct}%"
        )

        if latency_ms is not None:
            message += f"\nLatence : {latency_ms:.0f}ms"

        await bot.send_message(
            chat_id=supergroup_id, message_thread_id=topic_id, text=message, parse_mode="HTML"
        )

        return True

    except TelegramError as e:
        logger.error("classification_success_notification_failed", error=str(e))
        return False


# ============================================================================
# NOTIFICATION TOPIC SYSTEM (Task 5.5 - erreurs classification)
# ============================================================================


async def send_classification_error(
    bot: Bot,
    topic_id: int,
    supergroup_id: int,
    document_id: str,
    error_type: str,
    error_detail: str,
) -> bool:
    """
    Envoie notification erreur classification dans Topic System.

    Args:
        bot: Instance Bot Telegram
        topic_id: Thread ID du Topic System & Alerts
        supergroup_id: Chat ID du supergroup Friday
        document_id: ID du document
        error_type: Type d'erreur (low_confidence, invalid_perimeter, timeout, failure)
        error_detail: Détail de l'erreur

    Returns:
        True si envoyé, False sinon

    Story 3.2 Task 5.5: Notification Topic System
    """
    try:
        if error_type == "low_confidence":
            emoji = EMOJI_WARNING
            title = "Confidence faible"
        elif error_type == "invalid_perimeter":
            emoji = EMOJI_ERROR
            title = "Périmètre finance invalide"
        else:
            emoji = EMOJI_ERROR
            title = "Erreur classification"

        message = (
            f"{emoji} <b>{_html_escape(title)}</b>\n\n"
            f"{EMOJI_DOC} Document : {_html_escape(document_id[:30])}\n"
            f"Détail : {_html_escape(error_detail[:200])}"
        )

        await bot.send_message(
            chat_id=supergroup_id, message_thread_id=topic_id, text=message, parse_mode="HTML"
        )

        return True

    except TelegramError as e:
        logger.error("classification_error_notification_failed", error=str(e))
        return False


# ============================================================================
# FORMATAGE MESSAGE (Task 5.2)
# ============================================================================


def _format_classification_message(classification_data: Dict[str, Any]) -> str:
    """
    Formate message notification classification (Task 5.2).

    Args:
        classification_data: Données classification

    Returns:
        Message HTML formaté
    """
    document_id = classification_data["document_id"]
    category = classification_data["category"]
    subcategory = classification_data.get("subcategory")
    path = classification_data.get("path", "")
    confidence = classification_data.get("confidence", 0.0)
    reasoning = classification_data.get("reasoning", "")

    # Header
    message = f"{EMOJI_FOLDER} <b>Document classifié (validation requise)</b>\n\n"

    # Document ID
    message += f"{EMOJI_DOC} <b>Document :</b> {_html_escape(document_id[:30])}\n"

    # Catégorie avec label français
    cat_display = CATEGORY_LABELS.get(category, category)
    if subcategory and category == "finance":
        finance_label = FINANCE_LABELS.get(subcategory, subcategory)
        message += f"{EMOJI_CATEGORY} <b>Catégorie :</b> {_html_escape(cat_display)} &gt; {_html_escape(finance_label)}\n"
    elif subcategory:
        message += f"{EMOJI_CATEGORY} <b>Catégorie :</b> {_html_escape(cat_display)} &gt; {_html_escape(subcategory)}\n"
    else:
        message += f"{EMOJI_CATEGORY} <b>Catégorie :</b> {_html_escape(cat_display)}\n"

    # Destination
    if path:
        message += f"{EMOJI_PATH} <b>Destination :</b> {_html_escape(path)}\n"

    # Confiance
    confidence_pct = int(confidence * 100)
    message += f"\n{EMOJI_CONFIDENCE} <b>Confiance :</b> {confidence_pct}%"

    # Reasoning
    if reasoning:
        message += f"\n<i>{_html_escape(reasoning[:150])}</i>"

    return message


def _html_escape(text: str) -> str:
    """Echappe caractères spéciaux HTML pour Telegram parse_mode=HTML."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# ============================================================================
# INLINE KEYBOARD (Task 5.2)
# ============================================================================


def _create_classification_keyboard(receipt_id: str) -> InlineKeyboardMarkup:
    """
    Crée inline keyboard avec 3 boutons (Task 5.2).

    [Approuver] [Corriger destination] [Rejeter]

    Args:
        receipt_id: ID du receipt ou document pour callbacks

    Returns:
        InlineKeyboardMarkup
    """
    keyboard = [
        [
            InlineKeyboardButton("✅ Approuver", callback_data=f"classify_approve:{receipt_id}"),
            InlineKeyboardButton("📂 Corriger", callback_data=f"classify_correct:{receipt_id}"),
        ],
        [
            InlineKeyboardButton("❌ Rejeter", callback_data=f"classify_reject:{receipt_id}"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def _create_correction_keyboard(receipt_id: str) -> InlineKeyboardMarkup:
    """
    Crée inline keyboard pour correction destination (Task 5.3).

    Liste des catégories disponibles pour réassigner.

    Args:
        receipt_id: ID du receipt pour callbacks

    Returns:
        InlineKeyboardMarkup avec catégories
    """
    keyboard = [
        [
            InlineKeyboardButton("Pro", callback_data=f"classify_reclassify:{receipt_id}:pro"),
            InlineKeyboardButton(
                "Finance", callback_data=f"classify_reclassify:{receipt_id}:finance"
            ),
        ],
        [
            InlineKeyboardButton(
                "Université", callback_data=f"classify_reclassify:{receipt_id}:universite"
            ),
            InlineKeyboardButton(
                "Recherche", callback_data=f"classify_reclassify:{receipt_id}:recherche"
            ),
        ],
        [
            InlineKeyboardButton("Perso", callback_data=f"classify_reclassify:{receipt_id}:perso"),
        ],
        [
            InlineKeyboardButton("🔙 Retour", callback_data=f"classify_back:{receipt_id}"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def _create_finance_perimeter_keyboard(receipt_id: str) -> InlineKeyboardMarkup:
    """
    Crée inline keyboard pour sélection périmètre finance (Task 5.3).

    Args:
        receipt_id: ID du receipt

    Returns:
        InlineKeyboardMarkup avec 5 périmètres
    """
    keyboard = [
        [
            InlineKeyboardButton("SELARL", callback_data=f"classify_finance:{receipt_id}:selarl"),
            InlineKeyboardButton("SCM", callback_data=f"classify_finance:{receipt_id}:scm"),
        ],
        [
            InlineKeyboardButton(
                "SCI Ravas", callback_data=f"classify_finance:{receipt_id}:sci_ravas"
            ),
            InlineKeyboardButton(
                "SCI Malbosc", callback_data=f"classify_finance:{receipt_id}:sci_malbosc"
            ),
        ],
        [
            InlineKeyboardButton(
                "Personnel", callback_data=f"classify_finance:{receipt_id}:personal"
            ),
        ],
        [
            InlineKeyboardButton("🔙 Retour", callback_data=f"classify_back:{receipt_id}"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)
