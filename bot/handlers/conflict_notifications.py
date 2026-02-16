"""
Notifications Telegram pour conflits calendrier détectés (Story 7.3 AC4, AC6)

Envoie notifications dans Topic Actions & Validations avec inline buttons
pour résolution Mainteneur (annuler/déplacer/ignorer).
"""

import os
import logging
from typing import Optional
from datetime import datetime

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from agents.src.agents.calendar.models import CalendarConflict
from agents.src.core.models import (
    Casquette,
    CASQUETTE_EMOJI_MAPPING,
    CASQUETTE_LABEL_MAPPING,
)


logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

# Emojis pour formatage message (AC4)
EMOJI_WARNING = "⚠️"
EMOJI_SEPARATOR = "⚡"
EMOJI_CALENDAR = "📅"
EMOJI_CLOCK = "🕐"
EMOJI_DURATION = "⏱️"

# Topic ID pour notifications conflits (Story 1.9)
TOPIC_ACTIONS_ID = os.getenv("TOPIC_ACTIONS_ID")
TELEGRAM_SUPERGROUP_ID = os.getenv("TELEGRAM_SUPERGROUP_ID")


# ============================================================================
# FONCTION PRINCIPALE NOTIFICATION (AC4)
# ============================================================================

async def send_conflict_alert(
    bot: Bot,
    conflict: CalendarConflict,
    conflict_id: Optional[str] = None
) -> bool:
    """
    Envoie notification conflit calendrier dans Topic Actions (AC4)

    Format message :
    ⚠️ CONFLIT CALENDRIER DÉTECTÉ

    🩺 Consultation Dr Dupont
    📅 Lundi 17 février 2026
    🕐 14h30-15h30 (1h00)

    ⚡

    🎓 Cours L2 Anatomie
    📅 Lundi 17 février 2026
    🕐 14h00-16h00 (2h00)

    ⏱️ Chevauchement : 1h00
    ⚠️ Deux casquettes différentes en conflit

    [Annuler Consultation] [Déplacer Consultation] [Annuler Cours] [Déplacer Cours] [Ignorer conflit]

    Args:
        bot: Instance Bot Telegram
        conflict: CalendarConflict Pydantic model
        conflict_id: UUID conflit DB (optionnel, pour callback Ignorer)

    Returns:
        True si notification envoyée, False sinon

    Story 7.3 AC4: Notification Telegram Topic Actions avec inline buttons
    Story 7.3 AC6: Inline buttons résolution [Annuler X] [Déplacer X] [Ignorer]
    """
    # Validation config
    if not TOPIC_ACTIONS_ID:
        logger.error(
            "conflict_notification_failed",
            reason="TOPIC_ACTIONS_ID envvar manquante"
        )
        return False

    if not TELEGRAM_SUPERGROUP_ID:
        logger.error(
            "conflict_notification_failed",
            reason="TELEGRAM_SUPERGROUP_ID envvar manquante"
        )
        return False

    try:
        # Formater message (AC4)
        message = _format_conflict_message(conflict)

        # Créer inline keyboard (AC6)
        keyboard = _create_conflict_keyboard(
            event1_id=conflict.event1.id,
            event1_title=conflict.event1.title,
            event2_id=conflict.event2.id,
            event2_title=conflict.event2.title,
            conflict_id=conflict_id
        )

        # Envoyer message dans Topic Actions
        await bot.send_message(
            chat_id=int(TELEGRAM_SUPERGROUP_ID),
            message_thread_id=int(TOPIC_ACTIONS_ID),
            text=message,
            parse_mode="HTML",
            reply_markup=keyboard
        )

        logger.info(
            "conflict_notification_sent",
            event1_id=conflict.event1.id,
            event2_id=conflict.event2.id,
            event1_title=conflict.event1.title,
            event2_title=conflict.event2.title,
            overlap_minutes=conflict.overlap_minutes,
            topic="Actions"
        )

        return True

    except TelegramError as e:
        logger.error(
            "conflict_notification_telegram_error",
            error=str(e),
            event1_id=conflict.event1.id,
            event2_id=conflict.event2.id
        )
        return False

    except Exception as e:
        logger.error(
            "conflict_notification_error",
            error=str(e),
            event1_id=conflict.event1.id,
            event2_id=conflict.event2.id,
            exc_info=True
        )
        return False


# ============================================================================
# HELPERS FORMATAGE MESSAGE
# ============================================================================

def _format_conflict_message(conflict: CalendarConflict) -> str:
    """
    Formate message conflit pour Telegram (AC4)

    Args:
        conflict: CalendarConflict Pydantic model

    Returns:
        Message HTML formaté

    Format :
    ⚠️ CONFLIT CALENDRIER DÉTECTÉ

    [Event1 avec émoji casquette + date + heure]

    ⚡

    [Event2 avec émoji casquette + date + heure]

    ⏱️ Chevauchement : Xh YYmin
    ⚠️ Deux casquettes différentes en conflit
    """
    # Header
    lines = [
        f"{EMOJI_WARNING} <b>CONFLIT CALENDRIER DÉTECTÉ</b>",
        ""
    ]

    # Événement 1
    lines.extend(_format_event_section(conflict.event1))
    lines.append("")

    # Séparateur
    lines.append(f"{EMOJI_SEPARATOR}")
    lines.append("")

    # Événement 2
    lines.extend(_format_event_section(conflict.event2))
    lines.append("")

    # Informations chevauchement
    overlap_str = _format_duration(conflict.overlap_minutes)
    lines.append(f"{EMOJI_DURATION} <b>Chevauchement :</b> {overlap_str}")

    # Avertissement casquettes différentes
    casquette1_label = CASQUETTE_LABEL_MAPPING[conflict.event1.casquette]
    casquette2_label = CASQUETTE_LABEL_MAPPING[conflict.event2.casquette]
    lines.append(
        f"{EMOJI_WARNING} <b>Deux casquettes en conflit :</b> "
        f"{casquette1_label} {EMOJI_SEPARATOR} {casquette2_label}"
    )

    return "\n".join(lines)


def _format_event_section(event) -> list[str]:
    """
    Formate section événement individuel

    Args:
        event: CalendarEvent

    Returns:
        Liste lignes formatées HTML

    Format :
    🩺 Consultation Dr Dupont
    📅 Lundi 17 février 2026
    🕐 14h30-15h30 (1h00)
    """
    # Émoji + titre
    emoji = CASQUETTE_EMOJI_MAPPING[event.casquette]
    label = CASQUETTE_LABEL_MAPPING[event.casquette]
    lines = [
        f"{emoji} <b>{event.title}</b> ({label})"
    ]

    # Date (format français long)
    date_str = _format_date_french(event.start_datetime)
    lines.append(f"{EMOJI_CALENDAR} {date_str}")

    # Heure
    start_time = event.start_datetime.strftime("%Hh%M")
    end_time = event.end_datetime.strftime("%Hh%M")
    duration_minutes = int((event.end_datetime - event.start_datetime).total_seconds() / 60)
    duration_str = _format_duration(duration_minutes)
    lines.append(f"{EMOJI_CLOCK} {start_time}-{end_time} ({duration_str})")

    return lines


def _format_date_french(dt: datetime) -> str:
    """
    Formate date en français long

    Args:
        dt: datetime

    Returns:
        "Lundi 17 février 2026"
    """
    # Jours et mois en français
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    mois = [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre"
    ]

    jour_semaine = jours[dt.weekday()]
    jour = dt.day
    mois_nom = mois[dt.month - 1]
    annee = dt.year

    return f"{jour_semaine} {jour} {mois_nom} {annee}"


def _format_duration(minutes: int) -> str:
    """
    Formate durée en heures et minutes

    Args:
        minutes: Durée en minutes

    Returns:
        "1h30", "45min", "2h00"
    """
    if minutes < 60:
        return f"{minutes}min"

    heures = minutes // 60
    reste_minutes = minutes % 60

    if reste_minutes == 0:
        return f"{heures}h00"

    return f"{heures}h{reste_minutes:02d}"


# ============================================================================
# HELPERS INLINE KEYBOARD (AC6)
# ============================================================================

def _create_conflict_keyboard(
    event1_id: str,
    event1_title: str,
    event2_id: str,
    event2_title: str,
    conflict_id: Optional[str]
) -> InlineKeyboardMarkup:
    """
    Crée inline keyboard résolution conflit (AC6)

    Args:
        event1_id: UUID événement 1
        event1_title: Titre événement 1 (pour label bouton)
        event2_id: UUID événement 2
        event2_title: Titre événement 2
        conflict_id: UUID conflit DB (optionnel)

    Returns:
        InlineKeyboardMarkup avec boutons résolution

    Format :
    [Annuler Event1] [Déplacer Event1]
    [Annuler Event2] [Déplacer Event2]
    [Ignorer conflit]

    Callback data format :
    - conflict:cancel:<event_id>
    - conflict:move:<event_id>
    - conflict:ignore:<conflict_id>
    """
    # Tronquer titres événements pour labels boutons (max 30 caractères)
    event1_label = _truncate_title(event1_title)
    event2_label = _truncate_title(event2_title)

    # Ligne 1 : Boutons événement 1
    row1 = [
        InlineKeyboardButton(
            text=f"❌ Annuler {event1_label}",
            callback_data=f"conflict:cancel:{event1_id}"
        ),
        InlineKeyboardButton(
            text=f"📆 Déplacer {event1_label}",
            callback_data=f"conflict:move:{event1_id}"
        ),
    ]

    # Ligne 2 : Boutons événement 2
    row2 = [
        InlineKeyboardButton(
            text=f"❌ Annuler {event2_label}",
            callback_data=f"conflict:cancel:{event2_id}"
        ),
        InlineKeyboardButton(
            text=f"📆 Déplacer {event2_label}",
            callback_data=f"conflict:move:{event2_id}"
        ),
    ]

    # Ligne 3 : Ignorer conflit (si conflict_id fourni)
    rows = [row1, row2]

    if conflict_id:
        row3 = [
            InlineKeyboardButton(
                text="✅ Ignorer conflit",
                callback_data=f"conflict:ignore:{conflict_id}"
            )
        ]
        rows.append(row3)

    return InlineKeyboardMarkup(rows)


def _truncate_title(title: str, max_length: int = 20) -> str:
    """
    Tronque titre événement pour label bouton

    Args:
        title: Titre complet
        max_length: Longueur max (défaut 20)

    Returns:
        Titre tronqué avec "..." si nécessaire
    """
    if len(title) <= max_length:
        return title

    return title[:max_length - 3] + "..."
