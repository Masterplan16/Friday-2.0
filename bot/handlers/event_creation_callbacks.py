"""
Callbacks inline buttons pour creation/annulation evenements

Story 7.4 AC3: Confirmation creation + Sync Google Calendar + Detection conflits
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import structlog
from telegram import Update
from telegram.ext import ContextTypes

from agents.src.agents.calendar.models import CalendarEvent, EventStatus
from agents.src.core.models import CASQUETTE_EMOJI_MAPPING, CASQUETTE_LABEL_MAPPING, Casquette
from bot.handlers.event_proposal_notifications import format_date_fr

logger = structlog.get_logger(__name__)

# Topic IDs
TOPIC_ACTIONS_ID = int(os.getenv("TOPIC_ACTIONS_ID", "0"))
TOPIC_SYSTEM_ID = int(os.getenv("TOPIC_SYSTEM_ID", "0"))
TELEGRAM_SUPERGROUP_ID = int(os.getenv("TELEGRAM_SUPERGROUP_ID", "0"))


async def handle_event_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Callback [Creer]: Confirme evenement + sync Google Calendar + detection conflits.

    Pipeline:
    1. UPDATE status='confirmed' dans PostgreSQL
    2. Sync Google Calendar (Story 7.2 reuse)
    3. Detection conflits immediate (Story 7.3 AC4)
    4. Notification Topic Actions "Evenement cree"
    5. ActionResult trust='auto' (inline button = approbation)

    Args:
        update: Telegram Update (CallbackQuery)
        context: Bot context
    """
    query = update.callback_query
    await query.answer()

    # Extraire event_id depuis callback_data "evt_create:{event_id}"
    callback_data = query.data or ""
    if not callback_data.startswith("evt_create:"):
        return

    event_id = callback_data[len("evt_create:") :]
    if not event_id or event_id == "none":
        await query.edit_message_text("Erreur: ID evenement manquant")
        return

    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await query.edit_message_text("Erreur: Base de donnees non disponible")
        return

    try:
        # 1. Fetch event et UPDATE status='confirmed'
        event_data = await _confirm_event(db_pool, event_id)
        if not event_data:
            await query.edit_message_text("Erreur: Evenement non trouve")
            return

        # 2. Sync Google Calendar (optionnel, depends on config)
        external_id = await _sync_to_google_calendar(db_pool, event_id, event_data)

        # 3. Detection conflits immediate
        await _check_conflicts_immediate(db_pool, event_data, context.bot)

        # 4. Notification confirmation
        title = event_data.get("name", "Evenement")
        properties = event_data.get("properties", {})
        start_dt_str = properties.get("start_datetime", "")
        casquette_str = properties.get("casquette", "")
        casquette_emoji = ""
        try:
            casq = Casquette(casquette_str)
            casquette_emoji = CASQUETTE_EMOJI_MAPPING.get(casq, "")
            casquette_label = CASQUETTE_LABEL_MAPPING.get(casq, casquette_str)
        except (ValueError, KeyError):
            casquette_label = casquette_str

        lines = [
            "Evenement cree\n",
            f"Titre : {title}",
        ]
        if start_dt_str:
            try:
                start_dt = datetime.fromisoformat(start_dt_str)
                lines.append(f"Date : {format_date_fr(start_dt)}")
            except (ValueError, TypeError):
                lines.append(f"Date : {start_dt_str}")
        if casquette_label:
            lines.append(f"Casquette : {casquette_emoji} {casquette_label}")
        if external_id:
            lines.append("Google Calendar synchronise")

        await query.edit_message_text("\n".join(lines))

        logger.info(
            "Event confirmed and created",
            extra={
                "event_id": event_id,
                "title": title,
                "external_id": external_id,
            },
        )

    except Exception as e:
        logger.error(
            "Error in event create callback",
            extra={"event_id": event_id, "error": str(e)},
        )
        await query.edit_message_text(f"Erreur lors de la creation: {str(e)[:100]}")


async def handle_event_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Callback [Annuler]: Supprime entite EVENT proposed.

    Args:
        update: Telegram Update (CallbackQuery)
        context: Bot context
    """
    query = update.callback_query
    await query.answer()

    callback_data = query.data or ""
    if not callback_data.startswith("evt_cancel:"):
        return

    event_id = callback_data[len("evt_cancel:") :]
    if not event_id or event_id == "none":
        await query.edit_message_text("Creation annulee")
        return

    db_pool = context.bot_data.get("db_pool")
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE knowledge.entities
                    SET properties = jsonb_set(properties, '{status}', '"cancelled"')
                    WHERE id = $1 AND entity_type = 'EVENT'
                    """,
                    uuid.UUID(event_id),
                )
            logger.info("Event cancelled", extra={"event_id": event_id})
        except Exception as e:
            logger.error(
                "Failed to cancel event",
                extra={"event_id": event_id, "error": str(e)},
            )

    await query.edit_message_text("Creation annulee")


# ============================================================================
# HELPERS
# ============================================================================


async def _confirm_event(db_pool: asyncpg.Pool, event_id: str) -> Optional[dict]:
    """
    UPDATE status='confirmed' et retourne les donnees de l'evenement.

    Returns:
        dict avec id, name, properties ou None si non trouve
    """
    try:
        async with db_pool.acquire() as conn:
            # UPDATE status='confirmed'
            row = await conn.fetchrow(
                """
                UPDATE knowledge.entities
                SET properties = jsonb_set(properties, '{status}', '"confirmed"'),
                    updated_at = $2
                WHERE id = $1 AND entity_type = 'EVENT'
                RETURNING id, name, entity_type, properties
                """,
                uuid.UUID(event_id),
                datetime.now(timezone.utc),
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
            "Failed to confirm event",
            extra={"event_id": event_id, "error": str(e)},
        )
        return None


async def _sync_to_google_calendar(
    db_pool: asyncpg.Pool, event_id: str, event_data: dict
) -> Optional[str]:
    """
    Sync evenement vers Google Calendar (Story 7.2 reuse).

    Returns:
        Google Calendar external_id ou None si erreur/non configure
    """
    try:
        from agents.src.integrations.google_calendar.config import CalendarConfig
        from agents.src.integrations.google_calendar.sync_manager import GoogleCalendarSync

        config = CalendarConfig()
        sync_manager = GoogleCalendarSync(config=config, db_pool=db_pool)

        external_id = await sync_manager.write_event_to_google(event_id)

        if external_id:
            # Sauvegarder external_id dans properties
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE knowledge.entities
                    SET properties = jsonb_set(properties, '{external_id}', to_jsonb($2::text))
                    WHERE id = $1
                    """,
                    uuid.UUID(event_id),
                    external_id,
                )

            logger.info(
                "Event synced to Google Calendar",
                extra={"event_id": event_id, "external_id": external_id},
            )

        return external_id

    except ImportError:
        logger.debug("Google Calendar not configured, skipping sync")
        return None
    except Exception as e:
        logger.warning(
            "Google Calendar sync failed (non-blocking)",
            extra={"event_id": event_id, "error": str(e)},
        )
        return None


async def _check_conflicts_immediate(db_pool: asyncpg.Pool, event_data: dict, bot) -> None:
    """
    Detection conflits immediate apres creation (Story 7.3 AC4).

    Si conflits detectes -> notification Topic System.
    """
    try:
        from datetime import date as date_type

        from agents.src.agents.calendar.conflict_detector import (
            detect_calendar_conflicts,
        )

        properties = event_data.get("properties", {})
        start_dt_str = properties.get("start_datetime", "")

        if not start_dt_str:
            return

        try:
            start_dt = datetime.fromisoformat(start_dt_str)
            event_date = start_dt.date()
        except (ValueError, TypeError):
            return

        conflicts = await detect_calendar_conflicts(event_date, db_pool)

        if conflicts:
            # Envoyer alerte Topic System
            if TELEGRAM_SUPERGROUP_ID and TOPIC_SYSTEM_ID:
                conflict_msg = f"Conflit calendrier detecte le {event_date}\n\n"
                for conflict in conflicts[:3]:  # Max 3 conflits affiches
                    conflict_msg += (
                        f"- {conflict.event1.title} vs {conflict.event2.title} "
                        f"({conflict.overlap_minutes} min chevauchement)\n"
                    )

                try:
                    await bot.send_message(
                        chat_id=TELEGRAM_SUPERGROUP_ID,
                        message_thread_id=TOPIC_SYSTEM_ID,
                        text=conflict_msg,
                    )
                except Exception as tg_err:
                    logger.error(
                        "Failed to send conflict alert",
                        extra={"error": str(tg_err)},
                    )

            logger.info(
                "Conflicts detected after event creation",
                extra={
                    "event_id": event_data.get("id"),
                    "conflicts_count": len(conflicts),
                },
            )

    except ImportError:
        logger.debug("Conflict detector not available, skipping check")
    except Exception as e:
        logger.warning(
            "Conflict detection failed (non-blocking)",
            extra={"error": str(e)},
        )


def register_event_creation_callbacks(application, db_pool) -> None:
    """
    Enregistre les callback handlers pour creation/annulation evenements.

    Args:
        application: Telegram Application
        db_pool: Pool asyncpg
    """
    from telegram.ext import CallbackQueryHandler

    application.add_handler(
        CallbackQueryHandler(
            handle_event_create_callback,
            pattern=r"^evt_create:",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            handle_event_cancel_callback,
            pattern=r"^evt_cancel:",
        )
    )

    logger.info("Story 7.4 event creation callback handlers registered")
