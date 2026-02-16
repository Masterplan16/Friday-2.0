"""
Callbacks modification evenement propose

Story 7.4 AC6: Menu modification champs + state machine Redis
Buttons: [Titre] [Date] [Heure] [Lieu] [Participants] [Valider]
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from bot.handlers.create_event_command import _validate_date, _validate_time
from bot.handlers.event_proposal_notifications import format_date_fr
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)

# Config
TOPIC_ACTIONS_ID = int(os.getenv("TOPIC_ACTIONS_ID", "0"))
TELEGRAM_SUPERGROUP_ID = int(os.getenv("TELEGRAM_SUPERGROUP_ID", "0"))

# State machine config
STATE_KEY_PREFIX = "state:modify_event"
STATE_TTL = 600  # 10 minutes


async def handle_event_modify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Callback [Modifier]: Affiche menu modification avec inline buttons.

    Args:
        update: Telegram Update (CallbackQuery)
        context: Bot context
    """
    query = update.callback_query
    await query.answer()

    callback_data = query.data or ""
    if not callback_data.startswith("evt_modify:"):
        return

    event_id = callback_data[len("evt_modify:") :]
    if not event_id or event_id == "none":
        await query.edit_message_text("Erreur: ID evenement manquant")
        return

    user_id = update.effective_user.id if update.effective_user else 0

    # Charger event depuis PostgreSQL
    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await query.edit_message_text("Erreur: Base de donnees non disponible")
        return

    event_data = await _load_event(db_pool, event_id)
    if not event_data:
        await query.edit_message_text("Erreur: Evenement non trouve")
        return

    # Initialiser state Redis
    redis_client = context.bot_data.get("redis_client")
    if redis_client:
        state_key = f"{STATE_KEY_PREFIX}:{user_id}"
        state_data = {
            "event_id": event_id,
            "waiting_field": None,
            "modifications": {},
            "original": event_data,
        }
        await redis_client.set(state_key, json.dumps(state_data), ex=STATE_TTL)

    # Afficher menu modification
    await _send_modification_menu(query, event_id, event_data)


async def _send_modification_menu(query, event_id: str, event_data: dict) -> None:
    """
    Envoie le menu modification avec inline buttons navigation.

    Args:
        query: CallbackQuery Telegram
        event_id: UUID evenement
        event_data: Donnees event actuelles
    """
    properties = event_data.get("properties", {})
    name = event_data.get("name", "")

    lines = [
        "Modification evenement\n",
        f"Titre : {name}",
    ]

    start_dt_str = properties.get("start_datetime", "")
    if start_dt_str:
        try:
            start_dt = datetime.fromisoformat(start_dt_str)
            lines.append(f"Date : {format_date_fr(start_dt)}")
        except (ValueError, TypeError):
            lines.append(f"Date : {start_dt_str}")

    end_dt_str = properties.get("end_datetime", "")
    if end_dt_str:
        try:
            end_dt = datetime.fromisoformat(end_dt_str)
            lines.append(f"Fin : {end_dt.strftime('%H:%M')}")
        except (ValueError, TypeError):
            pass

    location = properties.get("location", "")
    if location:
        lines.append(f"Lieu : {location}")

    participants = properties.get("participants", [])
    if participants:
        lines.append(f"Participants : {', '.join(participants)}")

    lines.append("\nQuel champ modifier ?")

    keyboard = [
        [
            InlineKeyboardButton("Titre", callback_data=f"evt_mod_title:{event_id}"),
            InlineKeyboardButton("Date", callback_data=f"evt_mod_date:{event_id}"),
            InlineKeyboardButton("Heure", callback_data=f"evt_mod_time:{event_id}"),
        ],
        [
            InlineKeyboardButton("Lieu", callback_data=f"evt_mod_loc:{event_id}"),
            InlineKeyboardButton("Participants", callback_data=f"evt_mod_part:{event_id}"),
        ],
        [
            InlineKeyboardButton("Valider", callback_data=f"evt_mod_validate:{event_id}"),
            InlineKeyboardButton("Annuler", callback_data=f"evt_cancel:{event_id}"),
        ],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_modify_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Callback champs specifiques: Demande nouvelle valeur.

    Patterns: evt_mod_title:, evt_mod_date:, evt_mod_time:, evt_mod_loc:, evt_mod_part:
    """
    query = update.callback_query
    await query.answer()

    callback_data = query.data or ""

    # Determiner le champ
    field_map = {
        "evt_mod_title:": ("title", "Entrez le nouveau titre :"),
        "evt_mod_date:": ("date", "Entrez la nouvelle date (JJ/MM/AAAA ou JJ/MM) :"),
        "evt_mod_time:": ("time", "Entrez la nouvelle heure de debut (HH:MM) :"),
        "evt_mod_loc:": ("location", "Entrez le nouveau lieu :"),
        "evt_mod_part:": ("participants", "Entrez les participants (separes par virgule) :"),
    }

    matched_field = None
    event_id = None
    prompt = None

    for prefix, (field, question) in field_map.items():
        if callback_data.startswith(prefix):
            matched_field = field
            event_id = callback_data[len(prefix) :]
            prompt = question
            break

    if not matched_field:
        return

    user_id = update.effective_user.id if update.effective_user else 0
    redis_client = context.bot_data.get("redis_client")

    if redis_client:
        state_key = f"{STATE_KEY_PREFIX}:{user_id}"
        state_json = await redis_client.get(state_key)

        if state_json:
            state = json.loads(state_json)
            state["waiting_field"] = matched_field
            await redis_client.set(state_key, json.dumps(state), ex=STATE_TTL)

    await query.edit_message_text(prompt)


async def handle_modify_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handler message reponse modification.

    Verifie si state Redis attente modification.
    Appele depuis handler message principal.

    Returns:
        True si message traite, False sinon
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
    waiting_field = state.get("waiting_field")

    if not waiting_field:
        return False

    message_text = update.message.text.strip() if update.message and update.message.text else ""
    if not message_text:
        return False

    # Validation selon le champ
    error = _validate_modification(waiting_field, message_text)
    if error:
        await update.message.reply_text(error)
        return True

    # Enregistrer modification
    state["modifications"][waiting_field] = message_text
    state["waiting_field"] = None
    await redis_client.set(state_key, json.dumps(state), ex=STATE_TTL)

    # Re-afficher menu modification via message
    event_id = state.get("event_id", "none")
    original = state.get("original", {})

    # Appliquer modifications sur copie
    modified_data = _apply_modifications(original, state["modifications"])

    await update.message.reply_text(
        f"Champ modifie. Autre modification ou validez.",
    )

    return True


async def handle_modify_validate_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Callback [Valider]: Applique modifications en PostgreSQL et renvoi proposition.

    Args:
        update: Telegram Update (CallbackQuery)
        context: Bot context
    """
    query = update.callback_query
    await query.answer()

    callback_data = query.data or ""
    if not callback_data.startswith("evt_mod_validate:"):
        return

    event_id = callback_data[len("evt_mod_validate:") :]
    user_id = update.effective_user.id if update.effective_user else 0

    redis_client = context.bot_data.get("redis_client")
    if not redis_client:
        await query.edit_message_text("Erreur: Redis non disponible")
        return

    state_key = f"{STATE_KEY_PREFIX}:{user_id}"
    state_json = await redis_client.get(state_key)

    if not state_json:
        await query.edit_message_text("Erreur: Session expiree")
        return

    state = json.loads(state_json)
    modifications = state.get("modifications", {})

    if not modifications:
        await query.edit_message_text("Aucune modification effectuee")
        return

    # Appliquer modifications en PostgreSQL
    db_pool = context.bot_data.get("db_pool")
    if db_pool:
        await _apply_modifications_db(db_pool, event_id, modifications)

    # Supprimer state Redis
    await redis_client.delete(state_key)

    # Renvoi notification proposition avec inline buttons
    eid = event_id
    keyboard = [
        [
            InlineKeyboardButton("Creer", callback_data=f"evt_create:{eid}"),
            InlineKeyboardButton("Modifier", callback_data=f"evt_modify:{eid}"),
            InlineKeyboardButton("Annuler", callback_data=f"evt_cancel:{eid}"),
        ]
    ]

    lines = ["Evenement modifie\n"]
    for field, value in modifications.items():
        lines.append(f"  {field}: {value}")
    lines.append("\nConfirmer la creation ?")

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    logger.info(
        "Event modifications applied",
        extra={"event_id": event_id, "fields_modified": list(modifications.keys())},
    )


def _validate_modification(field: str, value: str) -> Optional[str]:
    """Valide input modification."""
    if field == "title":
        if len(value) < 2:
            return "Le titre doit contenir au moins 2 caracteres."
        return None
    if field == "date":
        return _validate_date(value)
    if field == "time":
        return _validate_time(value)
    return None


def _apply_modifications(original: dict, modifications: dict) -> dict:
    """Applique modifications sur copie des donnees."""
    modified = json.loads(json.dumps(original))  # Deep copy
    properties = modified.get("properties", {})

    for field, value in modifications.items():
        if field == "title":
            modified["name"] = value
        elif field == "date":
            # Mettre a jour start_datetime date part
            properties["date_override"] = value
        elif field == "time":
            properties["time_override"] = value
        elif field == "location":
            properties["location"] = value
        elif field == "participants":
            properties["participants"] = [p.strip() for p in value.split(",") if p.strip()]

    modified["properties"] = properties
    return modified


async def _apply_modifications_db(db_pool, event_id: str, modifications: dict) -> None:
    """Applique modifications dans PostgreSQL."""
    try:
        async with db_pool.acquire() as conn:
            for field, value in modifications.items():
                if field == "title":
                    await conn.execute(
                        "UPDATE knowledge.entities SET name = $2 WHERE id = $1",
                        uuid.UUID(event_id),
                        value,
                    )
                elif field == "location":
                    await conn.execute(
                        """
                        UPDATE knowledge.entities
                        SET properties = jsonb_set(properties, '{location}', to_jsonb($2::text))
                        WHERE id = $1
                        """,
                        uuid.UUID(event_id),
                        value,
                    )
                elif field == "participants":
                    parts = [p.strip() for p in value.split(",") if p.strip()]
                    await conn.execute(
                        """
                        UPDATE knowledge.entities
                        SET properties = jsonb_set(properties, '{participants}', $2::jsonb)
                        WHERE id = $1
                        """,
                        uuid.UUID(event_id),
                        json.dumps(parts),
                    )

        logger.info(
            "Modifications applied to DB",
            extra={"event_id": event_id, "fields": list(modifications.keys())},
        )
    except Exception as e:
        logger.error(
            "Failed to apply modifications",
            extra={"event_id": event_id, "error": str(e)},
        )


async def _load_event(db_pool, event_id: str) -> Optional[dict]:
    """Charge event depuis knowledge.entities."""
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, entity_type, properties
                FROM knowledge.entities
                WHERE id = $1 AND entity_type = 'EVENT'
                """,
                uuid.UUID(event_id),
            )

            if not row:
                return None

            return {
                "id": str(row["id"]),
                "name": row["name"],
                "properties": (
                    json.loads(row["properties"])
                    if isinstance(row["properties"], str)
                    else row["properties"]
                ),
            }
    except Exception as e:
        logger.error(
            "Failed to load event",
            extra={"event_id": event_id, "error": str(e)},
        )
        return None


def register_event_modification_callbacks(application, db_pool) -> None:
    """
    Enregistre tous les callback handlers modification.

    Args:
        application: Telegram Application
        db_pool: Pool asyncpg
    """
    from telegram.ext import CallbackQueryHandler

    # Menu modification
    application.add_handler(
        CallbackQueryHandler(
            handle_event_modify_callback,
            pattern=r"^evt_modify:",
        )
    )

    # Champs specifiques
    for prefix in [
        "evt_mod_title:",
        "evt_mod_date:",
        "evt_mod_time:",
        "evt_mod_loc:",
        "evt_mod_part:",
    ]:
        application.add_handler(
            CallbackQueryHandler(
                handle_modify_field_callback,
                pattern=f"^{prefix.replace(':', ':')}",
            )
        )

    # Validation
    application.add_handler(
        CallbackQueryHandler(
            handle_modify_validate_callback,
            pattern=r"^evt_mod_validate:",
        )
    )

    logger.info("Story 7.4 event modification callback handlers registered")
