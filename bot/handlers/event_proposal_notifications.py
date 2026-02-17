"""
Notifications proposition evenement avec inline buttons

Story 7.4 AC2: Notification Topic Actions avec [Creer] [Modifier] [Annuler]
"""

import os
from datetime import datetime
from typing import Optional

import structlog
from agents.src.agents.calendar.models import Event
from agents.src.core.models import CASQUETTE_EMOJI_MAPPING, CASQUETTE_LABEL_MAPPING
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

logger = structlog.get_logger(__name__)


def format_date_fr(dt: datetime) -> str:
    """
    Formate une datetime en francais.

    Args:
        dt: datetime a formater

    Returns:
        String formatee: "Mardi 18 fevrier 2026, 14h00"
    """
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    mois = [
        "",
        "janvier",
        "fevrier",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "aout",
        "septembre",
        "octobre",
        "novembre",
        "decembre",
    ]

    jour_semaine = jours[dt.weekday()]
    jour = dt.day
    mois_str = mois[dt.month]
    annee = dt.year
    heure = f"{dt.hour}h{dt.minute:02d}"

    return f"{jour_semaine} {jour} {mois_str} {annee}, {heure}"


def format_event_time_range(event: Event) -> str:
    """
    Formate plage horaire evenement.

    Args:
        event: Event Pydantic model

    Returns:
        String: "Mardi 18 fevrier 2026, 14h00-15h00"
    """
    start_str = format_date_fr(event.start_datetime)

    if event.end_datetime:
        end_heure = f"{event.end_datetime.hour}h{event.end_datetime.minute:02d}"
        return f"{start_str}-{end_heure}"

    return start_str


async def send_event_proposal_notification(
    bot: Bot,
    event: Event,
    event_id: Optional[str],
    confidence: float,
    source: str = "Message Telegram",
    supergroup_id: Optional[int] = None,
    topic_id: Optional[int] = None,
) -> Optional[int]:
    """
    Envoie notification proposition evenement avec inline buttons.

    Message Topic Actions:
    - Titre, date, lieu, participants, casquette, confidence, source
    - Inline buttons: [Creer] [Modifier] [Annuler]

    Args:
        bot: Instance Bot Telegram
        event: Event Pydantic model
        event_id: UUID entite EVENT (pour callbacks)
        confidence: Confidence extraction (0.0-1.0)
        source: Source de l'evenement
        supergroup_id: ID supergroup Telegram
        topic_id: ID topic Actions

    Returns:
        Message ID Telegram, ou None si erreur
    """
    if supergroup_id is None:
        supergroup_id = int(os.getenv("TELEGRAM_SUPERGROUP_ID", "0"))
    if topic_id is None:
        topic_id = int((os.getenv("TOPIC_ACTIONS_ID", "0") or "0").split("#")[0].strip() or "0")

    if not supergroup_id or not topic_id:
        logger.warning("Telegram supergroup_id or topic_id not configured")
        return None

    # Construire message
    casquette_emoji = CASQUETTE_EMOJI_MAPPING.get(event.casquette, "")
    casquette_label = CASQUETTE_LABEL_MAPPING.get(event.casquette, event.casquette.value)
    time_range = format_event_time_range(event)

    lines = [
        "\U0001f4c5 Nouvel evenement propose\n",
        f"\U0001f4cc Titre : {event.title}",
        f"\U0001f4c6 Date : {time_range}",
    ]

    if event.location:
        lines.append(f"\U0001f4cd Lieu : {event.location}")

    if event.participants:
        participants_str = ", ".join(event.participants)
        lines.append(f"\U0001f465 Participants : {participants_str}")

    lines.append(f"Casquette : {casquette_emoji} {casquette_label}")
    lines.append(f"\nConfiance : {confidence:.0%}")
    lines.append(f"Source : {source}")

    message_text = "\n".join(lines)

    # Inline buttons (AC2)
    event_id_str = event_id or "none"
    keyboard = [
        [
            InlineKeyboardButton("\u2705 Creer", callback_data=f"evt_create:{event_id_str}"),
            InlineKeyboardButton(
                "\u270f\ufe0f Modifier", callback_data=f"evt_modify:{event_id_str}"
            ),
            InlineKeyboardButton("\u274c Annuler", callback_data=f"evt_cancel:{event_id_str}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        message = await bot.send_message(
            chat_id=supergroup_id,
            message_thread_id=topic_id,
            text=message_text,
            reply_markup=reply_markup,
        )

        logger.info(
            "Event proposal notification sent",
            extra={
                "event_id": event_id_str,
                "message_id": message.message_id,
                "event_title": event.title,
            },
        )
        return message.message_id

    except Exception as e:
        logger.error(
            "Failed to send event proposal notification",
            extra={"error": str(e), "event_id": event_id_str},
        )
        return None
