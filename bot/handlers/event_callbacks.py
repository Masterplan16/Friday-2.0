"""
Callbacks inline buttons événements (Story 7.1 AC3)

Gère les actions : Approve, Modify, Ignore pour événements détectés
"""

import logging
import json
import uuid
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import asyncpg

logger = logging.getLogger(__name__)


# ============================================================================
# CALLBACK APPROVE - Ajouter à l'agenda (AC3)
# ============================================================================

async def handle_event_approve(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db_pool: asyncpg.Pool
):
    """
    Callback button [Ajouter à l'agenda]

    Actions :
    1. Update status proposed → confirmed dans knowledge.entities
    2. Publier événement calendar.event.confirmed dans Redis Streams
    3. Story 7.2: Sync Google Calendar (write_event_to_google)
    4. Éditer message Telegram : ✅ Événement ajouté à l'agenda + lien Google Calendar

    Args:
        update: Update Telegram
        context: Context Telegram
        db_pool: Pool PostgreSQL

    Story 7.1 AC3: Approve événement → status confirmed
    Story 7.2 AC3: Write event to Google Calendar
    """
    query = update.callback_query
    await query.answer()

    # Parser callback_data : "event_approve:uuid"
    callback_parts = query.data.split(":")
    if len(callback_parts) != 2:
        logger.error("Invalid callback_data", callback_data=query.data)
        await query.edit_message_text("❌ Erreur : callback invalide")
        return

    event_id = uuid.UUID(callback_parts[1])

    try:
        # 1. Update status proposed → confirmed
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE knowledge.entities
                SET properties = jsonb_set(properties, '{status}', '"confirmed"')
                WHERE id = $1 AND entity_type = 'EVENT'
                RETURNING name, properties
                """,
                event_id
            )

            if result == "UPDATE 0":
                logger.warning("Event not found", event_id=event_id)
                await query.edit_message_text("❌ Événement introuvable")
                return

            # Récupérer données événement
            event_row = await conn.fetchrow(
                "SELECT name, properties FROM knowledge.entities WHERE id = $1",
                event_id
            )

            event_name = event_row["name"]
            event_props = event_row["properties"]

            logger.info(
                "event_approved",
                event_id=event_id,
                event_name=event_name,
                user_id=query.from_user.id
            )

            # 2. Publier calendar.event.confirmed dans Redis Streams
            redis_client = context.bot_data.get("redis_client")
            if redis_client:
                await redis_client.xadd('calendar:event.confirmed', {
                    'event_id': str(event_id),
                    'status': 'confirmed',
                    'confirmed_at': datetime.utcnow().isoformat(),
                    'confirmed_by': str(query.from_user.id)
                })

        # 3. Story 7.2: Sync to Google Calendar
        google_event_id = None
        html_link = None
        casquette = event_props.get("casquette", "médecin")

        sync_manager = context.bot_data.get("google_calendar_sync")
        if sync_manager:
            try:
                google_event_id = await sync_manager.write_event_to_google(str(event_id))

                # Récupérer le html_link mis à jour
                updated_row = await db_pool.fetchrow(
                    "SELECT properties FROM knowledge.entities WHERE id = $1",
                    event_id
                )
                html_link = updated_row["properties"].get("html_link")

                logger.info(
                    "event_synced_to_google",
                    event_id=event_id,
                    google_event_id=google_event_id,
                    casquette=casquette
                )
            except Exception as e:
                logger.error(
                    "google_calendar_sync_failed",
                    event_id=event_id,
                    error=str(e),
                    exc_info=True
                )
                # Continue même si sync Google Calendar échoue

        # 4. Éditer message Telegram
        start_datetime = event_props.get("start_datetime", "date inconnue")

        message = (
            f"✅ <b>Événement ajouté à l'agenda</b>\n\n"
            f"<b>{event_name}</b>\n"
            f"📆 {start_datetime}\n"
            f"📍 Calendrier : {casquette.capitalize()}\n\n"
        )

        if html_link:
            message += f"🔗 <a href='{html_link}'>Voir dans Google Calendar</a>\n\n"

        message += f"<i>Approuvé par {query.from_user.first_name}</i>"

        await query.edit_message_text(
            message,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

        # 5. Story 7.3: Trigger détection conflits après ajout événement (AC5)
        try:
            from agents.src.agents.calendar.conflict_detector import detect_calendar_conflicts
            from bot.handlers.conflict_notifications import send_conflict_alert

            # Récupérer date événement
            start_datetime_parsed = datetime.fromisoformat(event_props["start_datetime"])
            event_date = start_datetime_parsed.date()

            # Détecter conflits pour cette date
            conflicts = await detect_calendar_conflicts(
                target_date=event_date,
                db_pool=db_pool
            )

            # Notifier immédiatement si conflits trouvés
            if conflicts:
                bot = context.bot
                for conflict in conflicts:
                    # Envoyer alerte conflit Topic Actions
                    conflict_sent = await send_conflict_alert(
                        bot=bot,
                        conflict=conflict,
                        conflict_id=None  # Pas encore enregistré en DB
                    )

                    if conflict_sent:
                        logger.info(
                            "conflict_alert_sent_after_event_approve",
                            event_id=event_id,
                            event_date=event_date.isoformat(),
                            conflicts_detected=len(conflicts)
                        )

        except Exception as conflict_e:
            # Ne pas bloquer l'approbation si détection conflits échoue
            logger.error(
                "conflict_detection_after_event_failed",
                event_id=event_id,
                error=str(conflict_e),
                exc_info=True
            )

    except Exception as e:
        logger.error(
            "event_approve_failed",
            event_id=event_id,
            error=str(e),
            exc_info=True
        )
        await query.edit_message_text(
            f"❌ Erreur lors de l'approbation : {str(e)}"
        )


# ============================================================================
# CALLBACK MODIFY - Modifier événement (AC3)
# ============================================================================

async def handle_event_modify(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db_pool: asyncpg.Pool
):
    """
    Callback button [Modifier]

    Actions :
    1. Ouvrir dialogue Telegram pour modifier titre/date/lieu
    2. Update knowledge.entities avec nouvelles valeurs
    3. Republier événement modifié

    Args:
        update: Update Telegram
        context: Context Telegram
        db_pool: Pool PostgreSQL

    Story 7.1 AC3: Modifier événement avant confirmation
    """
    query = update.callback_query
    await query.answer()

    # Parser callback_data
    callback_parts = query.data.split(":")
    if len(callback_parts) != 2:
        logger.error("Invalid callback_data", callback_data=query.data)
        await query.edit_message_text("❌ Erreur : callback invalide")
        return

    event_id = uuid.UUID(callback_parts[1])

    # Story 7.1 simplification : Éditer message avec bouton "Annuler modification"
    # Full dialogue Telegram = Story 7.3 (avancé)
    await query.edit_message_text(
        "✏️ <b>Modification d'événement</b>\n\n"
        "Pour modifier cet événement, utilisez la commande :\n"
        f"<code>/edit_event {event_id}</code>\n\n"
        "<i>Dialogue complet de modification disponible dans Story 7.3</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Retour", callback_data=f"event_back:{event_id}")]
        ])
    )

    logger.info(
        "event_modify_requested",
        event_id=event_id,
        user_id=query.from_user.id
    )


# ============================================================================
# CALLBACK IGNORE - Ignorer événement (AC3)
# ============================================================================

async def handle_event_ignore(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db_pool: asyncpg.Pool
):
    """
    Callback button [Ignorer]

    Actions :
    1. Update status proposed → cancelled dans knowledge.entities
    2. Éditer message Telegram : ❌ Événement ignoré
    3. Logger raison ignorance (pour améliorer détection future)

    Args:
        update: Update Telegram
        context: Context Telegram
        db_pool: Pool PostgreSQL

    Story 7.1 AC3: Rejeter événement → status cancelled
    """
    query = update.callback_query
    await query.answer()

    # Parser callback_data
    callback_parts = query.data.split(":")
    if len(callback_parts) != 2:
        logger.error("Invalid callback_data", callback_data=query.data)
        await query.edit_message_text("❌ Erreur : callback invalide")
        return

    event_id = uuid.UUID(callback_parts[1])

    try:
        # 1. Update status proposed → cancelled
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE knowledge.entities
                SET properties = jsonb_set(properties, '{status}', '"cancelled"')
                WHERE id = $1 AND entity_type = 'EVENT'
                RETURNING name
                """,
                event_id
            )

            if result == "UPDATE 0":
                logger.warning("Event not found", event_id=event_id)
                await query.edit_message_text("❌ Événement introuvable")
                return

            event_row = await conn.fetchrow(
                "SELECT name FROM knowledge.entities WHERE id = $1",
                event_id
            )

            event_name = event_row["name"]

            logger.info(
                "event_ignored",
                event_id=event_id,
                event_name=event_name,
                user_id=query.from_user.id
            )

        # 2. Éditer message Telegram
        await query.edit_message_text(
            f"❌ <b>Événement ignoré</b>\n\n"
            f"<b>{event_name}</b>\n\n"
            f"<i>Ignoré par {query.from_user.first_name}</i>",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(
            "event_ignore_failed",
            event_id=event_id,
            error=str(e),
            exc_info=True
        )
        await query.edit_message_text(
            f"❌ Erreur lors de l'ignorance : {str(e)}"
        )


# ============================================================================
# CALLBACK BACK - Retour message original
# ============================================================================

async def handle_event_back(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db_pool: asyncpg.Pool
):
    """
    Callback button [Retour]

    Restaure le message original avec inline buttons
    (utilisé après [Modifier])

    Args:
        update: Update Telegram
        context: Context Telegram
        db_pool: Pool PostgreSQL
    """
    query = update.callback_query
    await query.answer()

    callback_parts = query.data.split(":")
    if len(callback_parts) != 2:
        logger.error("Invalid callback_data", callback_data=query.data)
        return

    event_id = uuid.UUID(callback_parts[1])

    try:
        # Récupérer données événement
        async with db_pool.acquire() as conn:
            event_row = await conn.fetchrow(
                "SELECT name, properties FROM knowledge.entities WHERE id = $1",
                event_id
            )

            if not event_row:
                await query.edit_message_text("❌ Événement introuvable")
                return

            event_name = event_row["name"]
            event_props = event_row["properties"]

        # Reconstruire message original
        from bot.handlers.event_notifications import _format_event_message, _create_event_keyboard

        event_data = {
            "event_id": event_id,
            "title": event_name,
            "start_datetime": event_props.get("start_datetime"),
            "end_datetime": event_props.get("end_datetime"),
            "location": event_props.get("location"),
            "participants": event_props.get("participants", []),
            "casquette": event_props.get("casquette"),
            "confidence": event_props.get("confidence", 0.0)
        }

        message = _format_event_message(event_data)
        keyboard = _create_event_keyboard(event_id)

        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(
            "event_back_failed",
            event_id=event_id,
            error=str(e),
            exc_info=True
        )
