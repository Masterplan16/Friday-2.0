"""
Notifications Telegram pour événements détectés (Story 7.1 AC3)

Envoie notifications dans Topic Actions & Validations avec inline buttons
pour validation Mainteneur (trust=propose Day 1).
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

# Emojis pour formatage message (AC3)
EMOJI_CALENDAR = "📅"
EMOJI_DATE = "📆"
EMOJI_LOCATION = "📍"
EMOJI_PARTICIPANT = "👤"
EMOJI_CASQUETTE = "🎭"
EMOJI_EMAIL = "📧"
EMOJI_CONFIDENCE = "📊"

# Mapping casquettes → labels français
CASQUETTE_LABELS = {
    "medecin": "Médecin",
    "enseignant": "Enseignant",
    "chercheur": "Chercheur",
    "personnel": "Personnel",
}


# ============================================================================
# FONCTION PRINCIPALE NOTIFICATION (AC3)
# ============================================================================

async def send_event_proposal(
    bot: Bot,
    topic_id: int,
    supergroup_id: int,
    event_data: Dict[str, Any]
) -> bool:
    """
    Envoie notification événement détecté dans Topic Actions (AC3)

    Format message :
    📅 Nouvel événement détecté

    Titre : Consultation Dr Dupont
    📆 Date : Lundi 15 février 2026, 14h30-15h00
    📍 Lieu : Cabinet Dr Dupont
    👤 Participants : Dr Dupont
    🎭 Casquette : Médecin
    📧 Source : Email de Jean (10/02/2026)

    Confiance : 92%

    [Ajouter à l'agenda] [Modifier] [Ignorer]

    Args:
        bot: Instance Bot Telegram
        topic_id: Thread ID du Topic Actions & Validations
        supergroup_id: Chat ID du supergroup Friday
        event_data: Données événement extrait

    Returns:
        True si notification envoyée, False sinon

    Story 7.1 AC3: Notification Telegram Topic Actions avec inline buttons
    """
    try:
        # Formater message (AC3)
        message = _format_event_message(event_data)

        # Créer inline keyboard (AC3)
        keyboard = _create_event_keyboard(event_data["event_id"])

        # Envoyer message dans Topic Actions
        await bot.send_message(
            chat_id=supergroup_id,
            message_thread_id=topic_id,
            text=message,
            parse_mode="HTML",
            reply_markup=keyboard
        )

        logger.info(
            "event_notification_sent",
            event_id=event_data["event_id"],
            topic="Actions",
            event_title=event_data["title"]
        )

        return True

    except TelegramError as e:
        logger.error(
            "event_notification_failed",
            event_id=event_data.get("event_id"),
            error=str(e),
            exc_info=True
        )
        return False


# ============================================================================
# FORMATAGE MESSAGE (AC3)
# ============================================================================

def _format_event_message(event_data: Dict[str, Any]) -> str:
    """
    Formate message notification événement (AC3)

    Args:
        event_data: Données événement {event_id, title, start_datetime, ...}

    Returns:
        Message HTML formaté avec émojis
    """
    # Header
    message = f"{EMOJI_CALENDAR} <b>Nouvel événement détecté</b>\n\n"

    # Titre
    message += f"<b>Titre :</b> {_html_escape(event_data['title'])}\n"

    # Date (AC3: format français lisible)
    start_dt = event_data["start_datetime"]
    end_dt = event_data.get("end_datetime")

    if isinstance(start_dt, str):
        start_dt = datetime.fromisoformat(start_dt)
    if end_dt and isinstance(end_dt, str):
        end_dt = datetime.fromisoformat(end_dt)

    # Format date lisible : "Lundi 15 février 2026, 14h30-15h00"
    date_str = _format_datetime_french(start_dt, end_dt)
    message += f"{EMOJI_DATE} <b>Date :</b> {date_str}\n"

    # Lieu (optionnel)
    location = event_data.get("location")
    if location:
        message += f"{EMOJI_LOCATION} <b>Lieu :</b> {_html_escape(location)}\n"

    # Participants (optionnel)
    participants = event_data.get("participants", [])
    if participants:
        participants_str = ", ".join(_html_escape(p) for p in participants)
        message += f"{EMOJI_PARTICIPANT} <b>Participants :</b> {participants_str}\n"

    # Casquette (AC5: médecin|enseignant|chercheur)
    casquette = event_data.get("casquette", "medecin")
    casquette_label = CASQUETTE_LABELS.get(casquette, casquette.capitalize())
    message += f"{EMOJI_CASQUETTE} <b>Casquette :</b> {casquette_label}\n"

    # Source email (optionnel)
    email_metadata = event_data.get("email_metadata", {})
    if email_metadata:
        sender = email_metadata.get("sender", "Inconnu")
        date = email_metadata.get("date", "")
        message += f"{EMOJI_EMAIL} <b>Source :</b> Email de {_html_escape(sender)}"
        if date:
            message += f" ({date})"
        message += "\n"

    # Confiance
    confidence = event_data.get("confidence", 0.0)
    confidence_pct = int(confidence * 100)
    message += f"\n{EMOJI_CONFIDENCE} <b>Confiance :</b> {confidence_pct}%"

    return message


def _format_datetime_french(start: datetime, end: Optional[datetime] = None) -> str:
    """
    Formate datetime en format français lisible

    Args:
        start: Datetime début
        end: Datetime fin (optionnel)

    Returns:
        String formaté "Lundi 15 février 2026, 14h30-15h00"
    """
    # Jours semaine français
    DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

    # Mois français
    MONTHS = [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre"
    ]

    # Format : "Lundi 15 février 2026"
    day_name = DAYS[start.weekday()]
    day_num = start.day
    month_name = MONTHS[start.month - 1]
    year = start.year

    date_str = f"{day_name} {day_num} {month_name} {year}"

    # Heure : "14h30"
    start_time = f"{start.hour}h{start.minute:02d}" if start.minute else f"{start.hour}h"

    if end:
        end_time = f"{end.hour}h{end.minute:02d}" if end.minute else f"{end.hour}h"
        date_str += f", {start_time}-{end_time}"
    else:
        date_str += f", {start_time}"

    return date_str


def _html_escape(text: str) -> str:
    """
    Echappe caractères spéciaux HTML pour Telegram parse_mode=HTML

    Args:
        text: Texte brut

    Returns:
        Texte échappé
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ============================================================================
# INLINE KEYBOARD (AC3)
# ============================================================================

def _create_event_keyboard(event_id: str) -> InlineKeyboardMarkup:
    """
    Créé inline keyboard avec 3 boutons (AC3)

    [Ajouter à l'agenda] [Modifier] [Ignorer]

    Args:
        event_id: UUID événement

    Returns:
        InlineKeyboardMarkup
    """
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Ajouter",
                callback_data=f"event_approve:{event_id}"
            ),
            InlineKeyboardButton(
                "✏️ Modifier",
                callback_data=f"event_modify:{event_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Ignorer",
                callback_data=f"event_ignore:{event_id}"
            ),
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================================
# NOTIFICATIONS GOOGLE CALENDAR SYNC (Story 7.2 Task 6)
# ============================================================================

async def send_calendar_sync_success(
    bot: Bot,
    topic_id: int,
    supergroup_id: int,
    event_data: Dict[str, Any]
) -> bool:
    """
    Envoie notification après création Google Calendar réussie (AC3)

    Format message :
    ✅ Événement ajouté à Google Calendar

    Titre : Consultation cardio
    📆 Date : Mardi 17 février 2026, 14h00-15h00
    📍 Lieu : Cabinet médical
    🎭 Casquette : Médecin

    🔗 Voir dans Google Calendar

    Args:
        bot: Instance Bot Telegram
        topic_id: Thread ID du Topic Actions & Validations
        supergroup_id: Chat ID du supergroup Friday
        event_data: Données événement {event_id, title, start_datetime, ..., html_link}

    Returns:
        True si notification envoyée, False sinon

    Story 7.2 AC3: Notification Telegram après sync Google Calendar
    """
    try:
        # Formater message
        message = f"✅ <b>Événement ajouté à Google Calendar</b>\n\n"
        message += f"<b>Titre :</b> {_html_escape(event_data['title'])}\n"

        # Date
        start_dt = event_data["start_datetime"]
        end_dt = event_data.get("end_datetime")

        if isinstance(start_dt, str):
            start_dt = datetime.fromisoformat(start_dt.replace("+01:00", ""))
        if end_dt and isinstance(end_dt, str):
            end_dt = datetime.fromisoformat(end_dt.replace("+01:00", ""))

        date_str = _format_datetime_french(start_dt, end_dt)
        message += f"{EMOJI_DATE} <b>Date :</b> {date_str}\n"

        # Lieu (optionnel)
        location = event_data.get("location")
        if location:
            message += f"{EMOJI_LOCATION} <b>Lieu :</b> {_html_escape(location)}\n"

        # Casquette
        casquette = event_data.get("casquette", "medecin")
        casquette_label = CASQUETTE_LABELS.get(casquette, casquette.capitalize())
        message += f"{EMOJI_CASQUETTE} <b>Casquette :</b> {casquette_label}\n"

        # Lien Google Calendar (AC3)
        html_link = event_data.get("html_link")
        if html_link:
            message += f'\n🔗 <a href="{html_link}">Voir dans Google Calendar</a>'

        # Envoyer message dans Topic Actions
        await bot.send_message(
            chat_id=supergroup_id,
            message_thread_id=topic_id,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )

        logger.info(
            f"calendar_sync_success_notification_sent: {event_data.get('event_id')} - {event_data['title']}"
        )

        return True

    except TelegramError as e:
        logger.error(
            f"calendar_sync_success_notification_failed: {event_data.get('event_id')} - {str(e)}",
            exc_info=True
        )
        return False


async def send_calendar_modification_detected(
    bot: Bot,
    topic_id: int,
    supergroup_id: int,
    modification_data: Dict[str, Any]
) -> bool:
    """
    Envoie notification modification détectée dans Google Calendar (AC4)

    Format message :
    🔄 Événement modifié dans Google Calendar

    Modifications détectées :

    Titre :
    ❌ Réunion pédagogique
    ✅ Réunion pédagogique - URGENT

    Heure :
    ❌ Mardi 18 février 2026, 14h00-15h00
    ✅ Mardi 18 février 2026, 15h00-16h00

    Lieu :
    ❌ Salle A
    ✅ Salle B

    🔗 Voir dans Google Calendar

    Args:
        bot: Instance Bot Telegram
        topic_id: Thread ID du Topic Email & Communications
        supergroup_id: Chat ID du supergroup Friday
        modification_data: {event_id, old_data, new_data, html_link}

    Returns:
        True si notification envoyée, False sinon

    Story 7.2 AC4: Notification modification bidirectionnelle
    """
    try:
        old_data = modification_data["old_data"]
        new_data = modification_data["new_data"]

        # Header
        message = f"🔄 <b>Événement modifié dans Google Calendar</b>\n\n"
        message += "<b>Modifications détectées :</b>\n\n"

        # Diff Titre
        if old_data.get("title") != new_data.get("title"):
            message += "<b>Titre :</b>\n"
            message += f"❌ {_html_escape(old_data['title'])}\n"
            message += f"✅ {_html_escape(new_data['title'])}\n\n"

        # Diff Heure
        old_start = old_data.get("start_datetime")
        new_start = new_data.get("start_datetime")
        old_end = old_data.get("end_datetime")
        new_end = new_data.get("end_datetime")

        if old_start != new_start or old_end != new_end:
            # Parse datetimes
            if isinstance(old_start, str):
                old_start = datetime.fromisoformat(old_start.replace("+01:00", ""))
            if isinstance(new_start, str):
                new_start = datetime.fromisoformat(new_start.replace("+01:00", ""))
            if old_end and isinstance(old_end, str):
                old_end = datetime.fromisoformat(old_end.replace("+01:00", ""))
            if new_end and isinstance(new_end, str):
                new_end = datetime.fromisoformat(new_end.replace("+01:00", ""))

            old_date_str = _format_datetime_french(old_start, old_end)
            new_date_str = _format_datetime_french(new_start, new_end)

            message += "<b>Heure :</b>\n"
            message += f"❌ {old_date_str}\n"
            message += f"✅ {new_date_str}\n\n"

        # Diff Lieu
        old_location = old_data.get("location", "")
        new_location = new_data.get("location", "")
        if old_location != new_location:
            message += "<b>Lieu :</b>\n"
            message += f"❌ {_html_escape(old_location) if old_location else '(aucun)'}\n"
            message += f"✅ {_html_escape(new_location) if new_location else '(aucun)'}\n\n"

        # Lien Google Calendar (AC4)
        html_link = modification_data.get("html_link")
        if html_link:
            message += f'🔗 <a href="{html_link}">Voir dans Google Calendar</a>'

        # Envoyer message dans Topic Email & Communications
        await bot.send_message(
            chat_id=supergroup_id,
            message_thread_id=topic_id,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )

        logger.info(
            f"calendar_modification_notification_sent: {modification_data.get('event_id')} - "
            f"{old_data.get('title')} → {new_data.get('title')}"
        )

        return True

    except TelegramError as e:
        logger.error(
            f"calendar_modification_notification_failed: {modification_data.get('event_id')} - {str(e)}",
            exc_info=True
        )
        return False
