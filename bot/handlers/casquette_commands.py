"""
Handlers Commandes Telegram - Gestion Casquettes

Story 7.3: Multi-casquettes & Conflits Calendrier (AC2)

Commandes:
- /casquette : Affiche contexte actuel + prochains événements
- /casquette medecin|enseignant|chercheur : Force contexte manuellement
- /casquette auto : Réactive détection automatique

Inline buttons: [Médecin] [Enseignant] [Chercheur] [Auto]
"""

import os
from datetime import datetime, timedelta
from typing import Optional

import asyncpg
import redis.asyncio as redis
import structlog
from agents.src.core.context_manager import ContextManager
from agents.src.core.models import (
    CASQUETTE_EMOJI_MAPPING,
    CASQUETTE_LABEL_MAPPING,
    Casquette,
    ContextSource,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)


# ============================================================================
# Handler: /casquette (affichage + changement)
# ============================================================================


async def handle_casquette_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler commande /casquette (AC2).

    Usages:
    - /casquette → Affiche contexte actuel + prochains événements
    - /casquette medecin → Force contexte médecin
    - /casquette enseignant → Force contexte enseignant
    - /casquette chercheur → Force contexte chercheur
    - /casquette auto → Réactive auto-detect

    Args:
        update: Telegram Update
        context: Telegram context
    """
    message = update.message
    if not message:
        return

    # H1 fix: Vérifier que l'utilisateur est le propriétaire
    owner_id = os.getenv("OWNER_USER_ID")
    if owner_id and str(message.from_user.id) != owner_id:
        return

    # Récupérer argument (casquette à forcer)
    args = context.args if context.args else []

    # Charger context_manager
    context_manager = await _get_context_manager(context)

    # Cas 1: /casquette <casquette> → Force contexte
    if len(args) == 1:
        await _handle_casquette_set(message, context_manager, args[0])
        return

    # Cas 2: /casquette → Affiche contexte actuel
    await _handle_casquette_display(message, context_manager)


async def _handle_casquette_display(message, context_manager: ContextManager) -> None:
    """
    Affiche contexte actuel + prochains événements (AC2).

    Format:
    ```
    🎭 Contexte actuel : Médecin

    Détection : Événement en cours (Consultation Dr Dupont)
    Prochains événements :
    • 15h00-16h00 : Réunion service (Médecin)
    • 17h00-18h00 : Séminaire labo (Chercheur)

    [Changer de casquette]
    ```
    """
    # Récupérer contexte actuel
    current_context = await context_manager.get_current_context()

    # Récupérer prochains événements (aujourd'hui + demain)
    upcoming_events = await _get_upcoming_events(context_manager.db_pool)

    # Construire message
    text = _format_context_display_message(current_context, upcoming_events)

    # Inline buttons
    keyboard = _build_casquette_buttons()

    await message.reply_text(
        text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
    )

    logger.info(
        "casquette_command_display",
        user_id=message.from_user.id,
        current_casquette=current_context.casquette.value if current_context.casquette else None,
        source=current_context.source.value,
    )


async def _handle_casquette_set(
    message, context_manager: ContextManager, casquette_arg: str
) -> None:
    """
    Force contexte casquette manuellement (AC2).

    Args:
        message: Telegram message
        context_manager: ContextManager instance
        casquette_arg: 'medecin', 'enseignant', 'chercheur', ou 'auto'
    """
    casquette_arg_lower = casquette_arg.lower()

    # Cas 1: /casquette auto → Réactive auto-detect
    if casquette_arg_lower == "auto":
        await context_manager.set_context(casquette=None, source="system")

        await message.reply_text(
            "✅ Détection automatique réactivée\n\n"
            "Friday déterminera votre contexte selon vos événements et l'heure de la journée.",
            parse_mode="HTML",
        )

        logger.info("casquette_auto_detect_enabled", user_id=message.from_user.id)
        return

    # Cas 2: /casquette <casquette> → Force contexte
    try:
        casquette = Casquette(casquette_arg_lower)
    except ValueError:
        # Casquette invalide
        await message.reply_text(
            "❌ Casquette invalide.\n\n"
            "Casquettes disponibles: <code>medecin</code>, <code>enseignant</code>, <code>chercheur</code>, <code>auto</code>\n\n"
            "Exemple: <code>/casquette medecin</code>",
            parse_mode="HTML",
        )
        logger.warning("casquette_invalid_argument", argument=casquette_arg)
        return

    # Force contexte
    await context_manager.set_context(casquette=casquette, source="manual")

    emoji = CASQUETTE_EMOJI_MAPPING[casquette]
    label = CASQUETTE_LABEL_MAPPING[casquette]

    await message.reply_text(
        f"✅ Contexte changé → {emoji} <b>{label}</b>\n\n"
        "Ce contexte restera actif jusqu'à ce que vous le changiez à nouveau.",
        parse_mode="HTML",
    )

    logger.info("casquette_set_manual", user_id=message.from_user.id, casquette=casquette.value)


# ============================================================================
# Helpers
# ============================================================================


def _format_context_display_message(current_context, upcoming_events: list) -> str:
    """
    Formate message affichage contexte actuel (AC2).

    Args:
        current_context: UserContext
        upcoming_events: Liste événements prochains

    Returns:
        Message formaté HTML
    """
    # Header
    if current_context.casquette:
        emoji = CASQUETTE_EMOJI_MAPPING[current_context.casquette]
        label = CASQUETTE_LABEL_MAPPING[current_context.casquette]
        header = f"🎭 <b>Contexte actuel</b> : {emoji} {label}"
    else:
        header = "🎭 <b>Contexte actuel</b> : Auto-détection"

    # Source détection
    source_map = {
        ContextSource.MANUAL: "Manuel (commande Telegram)",
        ContextSource.EVENT: "Événement en cours",
        ContextSource.TIME: "Heure de la journée",
        ContextSource.LAST_EVENT: "Dernier événement",
        ContextSource.DEFAULT: "Aucun événement",
    }
    source_label = source_map.get(current_context.source, current_context.source.value)

    lines = [header, "", f"<b>Détection</b> : {source_label}", ""]

    # Prochains événements
    if upcoming_events:
        lines.append("<b>Prochains événements</b> :")
        for event in upcoming_events:
            emoji = CASQUETTE_EMOJI_MAPPING.get(event["casquette"], "")
            label = CASQUETTE_LABEL_MAPPING.get(event["casquette"], event["casquette"])
            time_range = f"{event['start_time']}-{event['end_time']}"
            lines.append(f"• {time_range} : {event['title']} ({emoji} {label})")
    else:
        lines.append("<i>Aucun événement à venir</i>")

    lines.append("")
    lines.append("<i>Utilisez les boutons ci-dessous pour changer de casquette</i>")

    return "\n".join(lines)


def _build_casquette_buttons() -> list:
    """
    Construit inline buttons changement casquette (AC2).

    Returns:
        Liste de listes InlineKeyboardButton
    """
    return [
        [
            InlineKeyboardButton(
                text=f"{CASQUETTE_EMOJI_MAPPING[Casquette.MEDECIN]} Médecin",
                callback_data="casquette:medecin",
            ),
            InlineKeyboardButton(
                text=f"{CASQUETTE_EMOJI_MAPPING[Casquette.ENSEIGNANT]} Enseignant",
                callback_data="casquette:enseignant",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"{CASQUETTE_EMOJI_MAPPING[Casquette.CHERCHEUR]} Chercheur",
                callback_data="casquette:chercheur",
            ),
            InlineKeyboardButton(text="🔄 Auto", callback_data="casquette:auto"),
        ],
    ]


async def _get_upcoming_events(db_pool: asyncpg.Pool, limit: int = 5) -> list:
    """
    Récupère prochains événements (aujourd'hui + demain).

    Args:
        db_pool: Pool PostgreSQL
        limit: Nombre max événements

    Returns:
        Liste événements avec format {casquette, title, start_time, end_time}
    """
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                properties->>'casquette' AS casquette,
                properties->>'title' AS title,
                (properties->>'start_datetime')::timestamptz AS start_datetime,
                (properties->>'end_datetime')::timestamptz AS end_datetime
            FROM knowledge.entities
            WHERE entity_type = 'EVENT'
              AND (properties->>'status') = 'confirmed'
              AND (properties->>'start_datetime')::timestamptz >= NOW()
              AND (properties->>'start_datetime')::timestamptz < NOW() + INTERVAL '2 days'
              AND properties->>'casquette' IS NOT NULL
            ORDER BY (properties->>'start_datetime')::timestamptz ASC
            LIMIT $1
        """,
            limit,
        )

    events = []
    for row in rows:
        casquette_value = row["casquette"]

        # Convertir en Enum Casquette
        try:
            casquette = Casquette(casquette_value)
        except ValueError:
            # Casquette invalide → skip
            continue

        events.append(
            {
                "casquette": casquette,
                "title": row["title"],
                "start_time": row["start_datetime"].strftime("%Hh%M"),
                "end_time": row["end_datetime"].strftime("%Hh%M"),
            }
        )

    return events


async def _get_context_manager(context: ContextTypes.DEFAULT_TYPE) -> ContextManager:
    """
    Récupère instance ContextManager depuis Telegram context.

    Args:
        context: Telegram context

    Returns:
        ContextManager instance
    """
    # Supposé que bot_data contient db_pool et redis_client
    db_pool = context.bot_data.get("db_pool")
    redis_client = context.bot_data.get("redis_client")

    if not db_pool or not redis_client:
        raise RuntimeError("db_pool ou redis_client non initialisé dans bot_data")

    return ContextManager(db_pool=db_pool, redis_client=redis_client, cache_ttl=300)
