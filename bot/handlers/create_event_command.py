"""
Commande /creer_event - Creation evenement guidee en 6 etapes

Story 7.4 AC4: Dialogue multi-etapes via state machine Redis
Steps: Titre -> Date -> Heure debut -> Heure fin -> Lieu -> Participants -> Resume
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from agents.src.core.models import CASQUETTE_EMOJI_MAPPING, CASQUETTE_LABEL_MAPPING, Casquette
from bot.handlers.event_proposal_notifications import format_date_fr
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)

# Config
OWNER_USER_ID = int(os.getenv("OWNER_USER_ID", "0"))
TOPIC_ACTIONS_ID = int(os.getenv("TOPIC_ACTIONS_ID", "0"))
TELEGRAM_SUPERGROUP_ID = int(os.getenv("TELEGRAM_SUPERGROUP_ID", "0"))

# State machine config
STATE_KEY_PREFIX = "state:create_event"
STATE_TTL = 600  # 10 minutes timeout

# Steps dialogue
STEPS = {
    1: {"field": "title", "question": "Etape 1/6 : Quel est le titre de l'evenement ?"},
    2: {"field": "date", "question": "Etape 2/6 : Quelle date ? (format: JJ/MM/AAAA ou JJ/MM)"},
    3: {"field": "start_time", "question": "Etape 3/6 : Heure de debut ? (format: HH:MM)"},
    4: {
        "field": "end_time",
        "question": "Etape 4/6 : Heure de fin ? (format: HH:MM, ou '.' pour passer)",
    },
    5: {"field": "location", "question": "Etape 5/6 : Lieu ? (ou '.' pour passer)"},
    6: {
        "field": "participants",
        "question": "Etape 6/6 : Participants ? (separes par virgule, ou '.' pour passer)",
    },
}


async def handle_create_event_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    CommandHandler /creer_event : Lance dialogue guidee creation evenement.

    Initialise state machine Redis avec TTL 10 min.

    Args:
        update: Telegram Update
        context: Bot context
    """
    user_id = update.effective_user.id if update.effective_user else 0
    if OWNER_USER_ID and user_id != OWNER_USER_ID:
        return

    redis_client = context.bot_data.get("redis_client")
    if not redis_client:
        await update.message.reply_text("Erreur: Redis non disponible")
        return

    # Initialiser state machine
    state_key = f"{STATE_KEY_PREFIX}:{user_id}"
    state_data = {
        "step": 1,
        "data": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    await redis_client.set(state_key, json.dumps(state_data), ex=STATE_TTL)

    msg = "Creation d'evenement guidee\n\n" + STEPS[1]["question"]
    await update.message.reply_text(msg)

    logger.info(
        "Create event dialog started",
        extra={"user_id": user_id},
    )


async def handle_create_event_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handler pour les reponses du dialogue /creer_event.

    Verifie si un state Redis actif existe, parse la reponse, avance au step suivant.
    Appele depuis le handler message principal (priority check).

    Args:
        update: Telegram Update
        context: Bot context

    Returns:
        True si message traite (dialogue actif), False sinon
    """
    user_id = update.effective_user.id if update.effective_user else 0

    redis_client = context.bot_data.get("redis_client")
    if not redis_client:
        return False

    state_key = f"{STATE_KEY_PREFIX}:{user_id}"
    state_json = await redis_client.get(state_key)

    if not state_json:
        return False

    state = json.loads(state_json)
    current_step = state.get("step", 0)

    if current_step < 1 or current_step > 6:
        await redis_client.delete(state_key)
        return False

    message_text = update.message.text.strip() if update.message and update.message.text else ""
    if not message_text:
        return False

    # Valider et stocker reponse
    step_info = STEPS[current_step]
    field = step_info["field"]

    # Validation selon le champ
    validation_result = _validate_step_input(field, message_text)
    if validation_result is not None:
        # Erreur de validation
        await update.message.reply_text(f"{validation_result}\n\n{step_info['question']}")
        return True

    # Skip avec "."
    if message_text == "." and field in ("end_time", "location", "participants"):
        state["data"][field] = None
    else:
        state["data"][field] = message_text

    # Avancer au step suivant
    next_step = current_step + 1

    if next_step > 6:
        # Dialogue termine -> afficher resume
        await redis_client.delete(state_key)
        await _send_event_summary(update, context, state["data"])
        return True

    state["step"] = next_step
    await redis_client.set(state_key, json.dumps(state), ex=STATE_TTL)

    # Envoyer question suivante
    await update.message.reply_text(STEPS[next_step]["question"])
    return True


def _validate_step_input(field: str, value: str) -> Optional[str]:
    """
    Valide input selon le champ.

    Args:
        field: Nom du champ (title, date, start_time, etc.)
        value: Valeur saisie par l'utilisateur

    Returns:
        Message d'erreur si invalide, None si OK
    """
    if value == "." and field in ("end_time", "location", "participants"):
        return None

    if field == "title":
        if len(value) < 2:
            return "Le titre doit contenir au moins 2 caracteres."
        if len(value) > 200:
            return "Le titre ne doit pas depasser 200 caracteres."
        return None

    if field == "date":
        return _validate_date(value)

    if field in ("start_time", "end_time"):
        return _validate_time(value)

    # location et participants : pas de validation stricte
    return None


def _validate_date(date_str: str) -> Optional[str]:
    """
    Valide format date JJ/MM/AAAA ou JJ/MM (annee courante).

    Returns:
        Message d'erreur si invalide, None si OK
    """
    # Format JJ/MM/AAAA
    if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", date_str):
        try:
            datetime.strptime(date_str, "%d/%m/%Y")
            return None
        except ValueError:
            return "Date invalide. Utilisez le format JJ/MM/AAAA (ex: 17/02/2026)."

    # Format JJ/MM (annee courante)
    if re.match(r"^\d{1,2}/\d{1,2}$", date_str):
        try:
            current_year = datetime.now().year
            datetime.strptime(f"{date_str}/{current_year}", "%d/%m/%Y")
            return None
        except ValueError:
            return "Date invalide. Utilisez le format JJ/MM (ex: 17/02)."

    return "Format de date non reconnu. Utilisez JJ/MM/AAAA ou JJ/MM."


def _validate_time(time_str: str) -> Optional[str]:
    """
    Valide format heure HH:MM ou HHhMM.

    Returns:
        Message d'erreur si invalide, None si OK
    """
    # Format HH:MM
    if re.match(r"^\d{1,2}:\d{2}$", time_str):
        try:
            parts = time_str.split(":")
            hour, minute = int(parts[0]), int(parts[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return None
        except (ValueError, IndexError):
            pass
        return "Heure invalide. Utilisez le format HH:MM (ex: 14:30)."

    # Format HHhMM ou HHh
    if re.match(r"^\d{1,2}h(\d{2})?$", time_str):
        try:
            parts = time_str.replace("h", ":").split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 and parts[1] else 0
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return None
        except (ValueError, IndexError):
            pass
        return "Heure invalide. Utilisez le format HH:MM ou HHh (ex: 14:30 ou 14h30)."

    return "Format d'heure non reconnu. Utilisez HH:MM ou HHhMM (ex: 14:30 ou 14h30)."


async def _send_event_summary(
    update: Update, context: ContextTypes.DEFAULT_TYPE, data: dict
) -> None:
    """
    Envoie resume evenement apres dialogue complet + inline buttons.

    Args:
        update: Telegram Update
        context: Bot context
        data: Donnees collectees (title, date, start_time, etc.)
    """
    title = data.get("title", "")
    date_str = data.get("date", "")
    start_time = data.get("start_time", "")
    end_time = data.get("end_time")
    location = data.get("location")
    participants_str = data.get("participants")

    # Construire datetime ISO
    start_dt = _build_datetime(date_str, start_time)
    end_dt = _build_datetime(date_str, end_time) if end_time else None

    # Format resume
    lines = [
        "Resume de l'evenement\n",
        f"Titre : {title}",
    ]
    if start_dt:
        lines.append(f"Date : {format_date_fr(start_dt)}")
    else:
        lines.append(f"Date : {date_str} {start_time}")

    if end_time:
        lines.append(f"Fin : {end_time}")
    if location:
        lines.append(f"Lieu : {location}")
    if participants_str:
        lines.append(f"Participants : {participants_str}")

    # Creer entite EVENT proposed dans PostgreSQL
    db_pool = context.bot_data.get("db_pool")
    event_id = None
    if db_pool:
        event_id = await _create_guided_event_entity(
            db_pool, title, start_dt, end_dt, location, participants_str
        )

    # Inline buttons
    eid = event_id or "none"
    keyboard = [
        [
            InlineKeyboardButton("Creer", callback_data=f"evt_create:{eid}"),
            InlineKeyboardButton("Recommencer", callback_data="evt_restart"),
            InlineKeyboardButton("Annuler", callback_data=f"evt_cancel:{eid}"),
        ]
    ]

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    logger.info(
        "Guided event creation summary sent",
        extra={"event_id": event_id, "title": title},
    )


def _build_datetime(date_str: str, time_str: Optional[str]) -> Optional[datetime]:
    """
    Construit datetime depuis date_str (JJ/MM ou JJ/MM/AAAA) + time_str (HH:MM ou HHhMM).

    Returns:
        datetime ou None si parsing echoue
    """
    if not date_str or not time_str:
        return None

    try:
        # Normaliser time
        normalized_time = time_str.replace("h", ":")
        if normalized_time.endswith(":"):
            normalized_time += "00"

        # Parse date
        if len(date_str.split("/")) == 3:
            date_part = datetime.strptime(date_str, "%d/%m/%Y").date()
        else:
            current_year = datetime.now().year
            date_part = datetime.strptime(f"{date_str}/{current_year}", "%d/%m/%Y").date()

        # Parse time
        parts = normalized_time.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0

        return datetime(date_part.year, date_part.month, date_part.day, hour, minute)
    except (ValueError, IndexError):
        return None


async def _create_guided_event_entity(
    db_pool,
    title: str,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    location: Optional[str],
    participants_str: Optional[str],
) -> Optional[str]:
    """
    Cree entite EVENT proposed dans knowledge.entities.

    Returns:
        UUID string de l'entite creee ou None si erreur
    """
    event_id = str(uuid.uuid4())

    properties = {
        "status": "proposed",
        "source": "guided_command",
        "casquette": "personnel",  # Default, modifiable avant creation
    }
    if start_dt:
        properties["start_datetime"] = start_dt.isoformat()
    if end_dt:
        properties["end_datetime"] = end_dt.isoformat()
    if location:
        properties["location"] = location
    if participants_str:
        properties["participants"] = [p.strip() for p in participants_str.split(",") if p.strip()]

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge.entities (id, name, entity_type, properties, created_at, updated_at)
                VALUES ($1, $2, 'EVENT', $3, $4, $4)
                """,
                uuid.UUID(event_id),
                title,
                json.dumps(properties),
                datetime.now(timezone.utc),
            )
        logger.info(
            "Guided event entity created",
            extra={"event_id": event_id, "title": title},
        )
        return event_id
    except Exception as e:
        logger.error(
            "Failed to create guided event entity",
            extra={"error": str(e)},
        )
        return None


async def handle_restart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Callback [Recommencer]: Relance dialogue creation.

    Args:
        update: Telegram Update (CallbackQuery)
        context: Bot context
    """
    query = update.callback_query
    await query.answer()

    callback_data = query.data or ""
    if callback_data != "evt_restart":
        return

    user_id = update.effective_user.id if update.effective_user else 0
    redis_client = context.bot_data.get("redis_client")

    if redis_client:
        state_key = f"{STATE_KEY_PREFIX}:{user_id}"
        state_data = {
            "step": 1,
            "data": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.set(state_key, json.dumps(state_data), ex=STATE_TTL)

    await query.edit_message_text("Creation d'evenement guidee\n\n" + STEPS[1]["question"])


def register_create_event_command(application, db_pool) -> None:
    """
    Enregistre le CommandHandler /creer_event et le callback Recommencer.

    Args:
        application: Telegram Application
        db_pool: Pool asyncpg
    """
    from telegram.ext import CallbackQueryHandler, CommandHandler

    application.add_handler(CommandHandler("creer_event", handle_create_event_command))
    application.add_handler(
        CallbackQueryHandler(
            handle_restart_callback,
            pattern=r"^evt_restart$",
        )
    )

    logger.info("Story 7.4 /creer_event command handler registered")
