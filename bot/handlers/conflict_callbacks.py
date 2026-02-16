"""
Callbacks inline buttons résolution conflits calendrier (Story 7.3 AC6)

Gère les actions :
- Cancel : Annuler événement (DB + Google Calendar)
- Move : Dialogue déplacement multi-étapes (date puis heure)
- Ignore : Marquer conflit résolu

State machine Redis pour dialogue déplacement :
- state:conflict:move:{user_id} = {"event_id": "...", "step": "waiting_date" | "waiting_time", "new_date": "..."}
"""

import os
import json
import uuid
from datetime import datetime, date, time, timedelta, timezone

import structlog
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import asyncpg
import redis.asyncio as redis

from agents.src.agents.calendar.models import ResolutionAction, ConflictResolution

logger = structlog.get_logger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

# TTL état Redis pour dialogue déplacement (5 minutes)
MOVE_STATE_TTL = 300

# ============================================================================
# ROUTER PRINCIPAL (AC6)
# ============================================================================


async def handle_conflict_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Router principal callbacks conflits (AC6)

    Callback data format :
    - conflict:cancel:<event_id>
    - conflict:move:<event_id>
    - conflict:ignore:<conflict_id>

    Args:
        update: Update Telegram
        context: Context Telegram

    Story 7.3 AC6: Résolution conflits via inline buttons
    """
    query = update.callback_query
    if not query:
        return

    # H1 fix: Vérifier que l'utilisateur est le propriétaire
    owner_id = os.getenv("OWNER_USER_ID")
    if owner_id and str(query.from_user.id) != owner_id:
        return

    await query.answer()

    # Parser callback_data
    if not query.data or not query.data.startswith("conflict:"):
        logger.error("Invalid callback_data", callback_data=query.data)
        await query.edit_message_text("❌ Erreur : callback invalide")
        return

    parts = query.data.split(":")
    if len(parts) < 3:
        logger.error("Invalid callback_data format", callback_data=query.data)
        await query.edit_message_text("❌ Erreur : format callback invalide")
        return

    action = parts[1]
    param = parts[2]

    # Récupérer dépendances
    db_pool = context.bot_data.get("db_pool")
    redis_client = context.bot_data.get("redis_client")

    if not db_pool or not redis_client:
        logger.error("db_pool ou redis_client non initialisé dans bot_data")
        await query.edit_message_text("❌ Erreur système : configuration manquante")
        return

    # Router vers handlers spécifiques
    if action == "cancel":
        await handle_conflict_cancel(
            query=query, event_id=param, db_pool=db_pool, redis_client=redis_client, context=context
        )
    elif action == "move":
        await handle_conflict_move(
            query=query,
            event_id=param,
            user_id=query.from_user.id,
            db_pool=db_pool,
            redis_client=redis_client,
        )
    elif action == "ignore":
        await handle_conflict_ignore(query=query, conflict_id=param, db_pool=db_pool)
    else:
        logger.error("Unknown conflict action", action=action)
        await query.edit_message_text(f"❌ Action inconnue : {action}")


# ============================================================================
# CALLBACK CANCEL - Annuler événement (AC6)
# ============================================================================


async def handle_conflict_cancel(
    query,
    event_id: str,
    db_pool: asyncpg.Pool,
    redis_client: redis.Redis,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Callback button [Annuler X]

    Actions :
    1. UPDATE knowledge.entities status='cancelled'
    2. DELETE événement Google Calendar (via sync_manager)
    3. Marquer conflits liés résolu (resolved=true)
    4. Publier Redis Streams calendar.conflict.resolved
    5. Éditer message Telegram : ✅ Événement annulé

    Args:
        query: CallbackQuery
        event_id: UUID événement à annuler
        db_pool: Pool PostgreSQL
        redis_client: Client Redis
        context: Context Telegram

    Story 7.3 AC6: Annulation événement résout conflit
    """
    try:
        event_uuid = uuid.UUID(event_id)

        # 1. UPDATE status='cancelled' dans DB
        async with db_pool.acquire() as conn:
            # Récupérer données événement avant update
            event_row = await conn.fetchrow(
                """
                SELECT name, properties
                FROM knowledge.entities
                WHERE id = $1 AND entity_type = 'EVENT'
                """,
                event_uuid,
            )

            if not event_row:
                logger.warning("Event not found", event_id=event_id)
                await query.edit_message_text("❌ Événement introuvable")
                return

            event_name = event_row["name"]
            event_props = event_row["properties"]
            google_event_id = event_props.get("google_event_id")

            # UPDATE status
            result = await conn.execute(
                """
                UPDATE knowledge.entities
                SET properties = jsonb_set(properties, '{status}', '"cancelled"')
                WHERE id = $1 AND entity_type = 'EVENT'
                """,
                event_uuid,
            )

            if result == "UPDATE 0":
                await query.edit_message_text("❌ Échec mise à jour événement")
                return

            # 2. DELETE Google Calendar
            sync_manager = context.bot_data.get("google_calendar_sync")
            if sync_manager and google_event_id:
                try:
                    casquette = event_props.get("casquette", "medecin")
                    await sync_manager.delete_event_from_google(
                        google_event_id=google_event_id, casquette=casquette
                    )
                    logger.info(
                        "event_deleted_from_google",
                        event_id=event_id,
                        google_event_id=google_event_id,
                    )
                except Exception as e:
                    logger.error(
                        "google_calendar_delete_failed",
                        event_id=event_id,
                        error=str(e),
                        exc_info=True,
                    )
                    # Continue même si delete Google Calendar échoue

            # 3. Marquer conflits liés résolu
            updated_conflicts = await conn.execute(
                """
                UPDATE knowledge.calendar_conflicts
                SET resolved = true,
                    resolution_action = 'cancel',
                    resolved_at = NOW()
                WHERE (event1_id = $1 OR event2_id = $1)
                  AND resolved = false
                """,
                event_uuid,
            )

            logger.info(
                "event_cancelled",
                event_id=event_id,
                event_name=event_name,
                user_id=query.from_user.id,
                conflicts_resolved=updated_conflicts,
            )

        # 4. Publier Redis Streams calendar.conflict.resolved
        await redis_client.xadd(
            "calendar:conflict.resolved",
            {
                "event_id": event_id,
                "action": "cancel",
                "resolved_at": datetime.now(timezone.utc).isoformat(),
                "resolved_by": str(query.from_user.id),
            },
        )

        # 5. Éditer message Telegram
        message = (
            f"✅ <b>Événement annulé</b>\n\n"
            f"<b>{event_name}</b>\n\n"
            f"<i>Tous les conflits liés ont été marqués résolus.</i>\n\n"
            f"<i>Annulé par {query.from_user.first_name}</i>"
        )

        await query.edit_message_text(message, parse_mode="HTML")

    except ValueError:
        logger.error("Invalid UUID format", event_id=event_id)
        await query.edit_message_text("❌ UUID événement invalide")

    except Exception as e:
        logger.error("conflict_cancel_error", event_id=event_id, error=str(e), exc_info=True)
        await query.edit_message_text("❌ Erreur lors de l'annulation événement")


# ============================================================================
# CALLBACK MOVE - Dialogue déplacement événement (AC6)
# ============================================================================


async def handle_conflict_move(
    query, event_id: str, user_id: int, db_pool: asyncpg.Pool, redis_client: redis.Redis
) -> None:
    """
    Callback button [Déplacer X] - Step 1: Demande nouvelle date

    Démarre dialogue multi-étapes pour déplacer événement :
    1. [Button click] → Demande nouvelle date (JJ/MM/AAAA)
    2. [User répond date] → Validation date → Demande nouvelle heure (HH:MM)
    3. [User répond heure] → Validation heure → UPDATE DB + PATCH Google Calendar

    State machine Redis :
    - state:conflict:move:{user_id} = {
        "event_id": "...",
        "step": "waiting_date",
        "event_name": "...",
        "original_start": "..."
      }

    Args:
        query: CallbackQuery
        event_id: UUID événement à déplacer
        user_id: ID utilisateur Telegram
        db_pool: Pool PostgreSQL
        redis_client: Client Redis

    Story 7.3 AC6: Déplacement événement via dialogue multi-étapes
    """
    try:
        event_uuid = uuid.UUID(event_id)

        # Récupérer données événement
        async with db_pool.acquire() as conn:
            event_row = await conn.fetchrow(
                """
                SELECT name, properties
                FROM knowledge.entities
                WHERE id = $1 AND entity_type = 'EVENT'
                """,
                event_uuid,
            )

            if not event_row:
                logger.warning("Event not found", event_id=event_id)
                await query.edit_message_text("❌ Événement introuvable")
                return

            event_name = event_row["name"]
            event_props = event_row["properties"]
            original_start = event_props.get("start_datetime")

        # Stocker état dans Redis (step 1: waiting_date)
        state_key = f"state:conflict:move:{user_id}"
        state_data = {
            "event_id": event_id,
            "step": "waiting_date",
            "event_name": event_name,
            "original_start": original_start,
        }

        await redis_client.set(state_key, json.dumps(state_data), ex=MOVE_STATE_TTL)

        logger.info(
            "conflict_move_started", event_id=event_id, user_id=user_id, step="waiting_date"
        )

        # Éditer message + demande nouvelle date
        message = (
            f"📆 <b>Déplacement événement</b>\n\n"
            f"<b>{event_name}</b>\n"
            f"Date actuelle : {original_start}\n\n"
            f"🔹 <b>Étape 1/2 :</b> Envoyez la nouvelle date\n\n"
            f"Format : <code>JJ/MM/AAAA</code>\n"
            f"Exemple : <code>20/02/2026</code>\n\n"
            f"<i>Répondez dans les 5 minutes</i>"
        )

        await query.edit_message_text(message, parse_mode="HTML")

    except ValueError:
        logger.error("Invalid UUID format", event_id=event_id)
        await query.edit_message_text("❌ UUID événement invalide")

    except Exception as e:
        logger.error("conflict_move_start_error", event_id=event_id, error=str(e), exc_info=True)
        await query.edit_message_text("❌ Erreur lors du démarrage déplacement")


async def handle_move_date_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handler réponse utilisateur pour nouvelle date (Step 2)

    Appelé par message handler principal bot/main.py.
    Vérifie si utilisateur est dans état "waiting_date" pour déplacement.

    Args:
        update: Update Telegram
        context: Context Telegram

    Returns:
        True si message traité (état move actif), False sinon

    Story 7.3 AC6: Validation date + transition step 2 (waiting_time)
    """
    user_id = update.message.from_user.id
    message_text = update.message.text.strip()

    redis_client = context.bot_data.get("redis_client")
    if not redis_client:
        return False

    # Vérifier état Redis
    state_key = f"state:conflict:move:{user_id}"
    state_json = await redis_client.get(state_key)

    if not state_json:
        return False  # Pas en cours de déplacement

    state = json.loads(state_json)

    if state.get("step") != "waiting_date":
        return False  # Pas dans le bon step

    # Valider format date JJ/MM/AAAA
    try:
        new_date = datetime.strptime(message_text, "%d/%m/%Y").date()
    except ValueError:
        await update.message.reply_text(
            "❌ <b>Date invalide</b>\n\n"
            "Format attendu : <code>JJ/MM/AAAA</code>\n"
            "Exemple : <code>20/02/2026</code>",
            parse_mode="HTML",
        )
        return True  # Message traité (erreur)

    # Valider date future ou aujourd'hui
    if new_date < date.today():
        await update.message.reply_text(
            "❌ <b>Date passée</b>\n\n" "La nouvelle date doit être aujourd'hui ou dans le futur.",
            parse_mode="HTML",
        )
        return True

    # Transition step 2: waiting_time
    state["step"] = "waiting_time"
    state["new_date"] = message_text  # Stocker format original

    await redis_client.set(state_key, json.dumps(state), ex=MOVE_STATE_TTL)

    logger.info(
        "conflict_move_date_validated",
        event_id=state["event_id"],
        user_id=user_id,
        new_date=message_text,
    )

    # Demander nouvelle heure
    message = (
        f"✅ <b>Date validée :</b> {message_text}\n\n"
        f"🔹 <b>Étape 2/2 :</b> Envoyez la nouvelle heure\n\n"
        f"Format : <code>HH:MM</code>\n"
        f"Exemple : <code>14:30</code>\n\n"
        f"<i>Répondez dans les 5 minutes</i>"
    )

    await update.message.reply_text(message, parse_mode="HTML")

    return True


async def handle_move_time_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handler réponse utilisateur pour nouvelle heure (Step 3)

    Appelé par message handler principal bot/main.py.
    Vérifie si utilisateur est dans état "waiting_time" pour déplacement.

    Finalise déplacement :
    - Validation heure
    - UPDATE DB knowledge.entities
    - PATCH Google Calendar
    - Marquer conflits résolu
    - Notification succès

    Args:
        update: Update Telegram
        context: Context Telegram

    Returns:
        True si message traité, False sinon

    Story 7.3 AC6: Finalisation déplacement événement
    """
    user_id = update.message.from_user.id
    message_text = update.message.text.strip()

    redis_client = context.bot_data.get("redis_client")
    db_pool = context.bot_data.get("db_pool")

    if not redis_client or not db_pool:
        return False

    # Vérifier état Redis
    state_key = f"state:conflict:move:{user_id}"
    state_json = await redis_client.get(state_key)

    if not state_json:
        return False

    state = json.loads(state_json)

    if state.get("step") != "waiting_time":
        return False

    # Valider format heure HH:MM
    try:
        new_time = datetime.strptime(message_text, "%H:%M").time()
    except ValueError:
        await update.message.reply_text(
            "❌ <b>Heure invalide</b>\n\n"
            "Format attendu : <code>HH:MM</code>\n"
            "Exemple : <code>14:30</code>",
            parse_mode="HTML",
        )
        return True

    # Construire nouveau datetime
    new_date_str = state["new_date"]
    new_date = datetime.strptime(new_date_str, "%d/%m/%Y").date()
    new_datetime = datetime.combine(new_date, new_time)

    event_id = state["event_id"]
    event_uuid = uuid.UUID(event_id)

    try:
        # UPDATE DB + Google Calendar
        async with db_pool.acquire() as conn:
            # Récupérer événement complet
            event_row = await conn.fetchrow(
                """
                SELECT name, properties
                FROM knowledge.entities
                WHERE id = $1 AND entity_type = 'EVENT'
                """,
                event_uuid,
            )

            if not event_row:
                await update.message.reply_text("❌ Événement introuvable")
                await redis_client.delete(state_key)
                return True

            event_name = event_row["name"]
            event_props = event_row["properties"]

            # Calculer nouvelle end_datetime (même durée)
            original_start = datetime.fromisoformat(event_props["start_datetime"])
            original_end = datetime.fromisoformat(event_props["end_datetime"])
            duration = original_end - original_start
            new_end_datetime = new_datetime + duration

            # UPDATE PostgreSQL
            await conn.execute(
                """
                UPDATE knowledge.entities
                SET properties = jsonb_set(
                    jsonb_set(properties, '{start_datetime}', $2::jsonb),
                    '{end_datetime}',
                    $3::jsonb
                )
                WHERE id = $1
                """,
                event_uuid,
                json.dumps(new_datetime.isoformat()),
                json.dumps(new_end_datetime.isoformat()),
            )

            # PATCH Google Calendar
            google_event_id = event_props.get("google_event_id")
            sync_manager = context.bot_data.get("google_calendar_sync")

            if sync_manager and google_event_id:
                try:
                    casquette = event_props.get("casquette", "medecin")
                    await sync_manager.update_event_in_google(
                        google_event_id=google_event_id,
                        casquette=casquette,
                        updates={
                            "start_datetime": new_datetime.isoformat(),
                            "end_datetime": new_end_datetime.isoformat(),
                        },
                    )
                    logger.info(
                        "event_updated_in_google",
                        event_id=event_id,
                        google_event_id=google_event_id,
                    )
                except Exception as e:
                    logger.error(
                        "google_calendar_update_failed",
                        event_id=event_id,
                        error=str(e),
                        exc_info=True,
                    )

            # Marquer conflits résolu
            await conn.execute(
                """
                UPDATE knowledge.calendar_conflicts
                SET resolved = true,
                    resolution_action = 'move',
                    resolved_at = NOW()
                WHERE (event1_id = $1 OR event2_id = $1)
                  AND resolved = false
                """,
                event_uuid,
            )

        # Publier Redis Streams
        await redis_client.xadd(
            "calendar:conflict.resolved",
            {
                "event_id": event_id,
                "action": "move",
                "new_datetime": new_datetime.isoformat(),
                "resolved_at": datetime.now(timezone.utc).isoformat(),
                "resolved_by": str(user_id),
            },
        )

        # Supprimer état Redis
        await redis_client.delete(state_key)

        logger.info(
            "event_moved", event_id=event_id, user_id=user_id, new_datetime=new_datetime.isoformat()
        )

        # Notification succès
        message = (
            f"✅ <b>Événement déplacé avec succès</b>\n\n"
            f"<b>{event_name}</b>\n\n"
            f"📆 Nouvelle date : {new_date_str} à {message_text}\n\n"
            f"<i>Tous les conflits liés ont été recalculés.</i>"
        )

        await update.message.reply_text(message, parse_mode="HTML")

    except Exception as e:
        logger.error("conflict_move_finalize_error", event_id=event_id, error=str(e), exc_info=True)
        await update.message.reply_text("❌ Erreur lors du déplacement événement")
        await redis_client.delete(state_key)

    return True


# ============================================================================
# CALLBACK IGNORE - Ignorer conflit (AC6)
# ============================================================================


async def handle_conflict_ignore(query, conflict_id: str, db_pool: asyncpg.Pool) -> None:
    """
    Callback button [Ignorer conflit]

    Actions :
    1. UPDATE knowledge.calendar_conflicts resolved=true, resolution_action='ignore'
    2. Éditer message Telegram : ✅ Conflit ignoré

    Args:
        query: CallbackQuery
        conflict_id: UUID conflit à ignorer
        db_pool: Pool PostgreSQL

    Story 7.3 AC6: Ignorer conflit sans action sur événements
    """
    try:
        conflict_uuid = uuid.UUID(conflict_id)

        # UPDATE resolved=true
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE knowledge.calendar_conflicts
                SET resolved = true,
                    resolution_action = 'ignore',
                    resolved_at = NOW()
                WHERE id = $1
                """,
                conflict_uuid,
            )

            if result == "UPDATE 0":
                logger.warning("Conflict not found", conflict_id=conflict_id)
                await query.edit_message_text("❌ Conflit introuvable")
                return

        logger.info("conflict_ignored", conflict_id=conflict_id, user_id=query.from_user.id)

        # Éditer message Telegram
        message = (
            f"✅ <b>Conflit ignoré</b>\n\n"
            f"<i>Les événements restent inchangés.</i>\n\n"
            f"<i>Ignoré par {query.from_user.first_name}</i>"
        )

        await query.edit_message_text(message, parse_mode="HTML")

    except ValueError:
        logger.error("Invalid UUID format", conflict_id=conflict_id)
        await query.edit_message_text("❌ UUID conflit invalide")

    except Exception as e:
        logger.error("conflict_ignore_error", conflict_id=conflict_id, error=str(e), exc_info=True)
        await query.edit_message_text("❌ Erreur lors de l'ignorance conflit")
