"""
Enregistrement handlers callbacks conflits calendrier (Story 7.3 Task 6)

Enregistre les CallbackQueryHandlers et MessageHandlers pour résolution conflits.
"""

import asyncpg
import redis.asyncio as redis
import structlog
from bot.handlers.conflict_callbacks import (
    handle_conflict_button,
    handle_move_date_response,
    handle_move_time_response,
)
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

logger = structlog.get_logger(__name__)


def register_conflict_callbacks_handlers(
    application: Application, db_pool: asyncpg.Pool, redis_client: redis.Redis
):
    """
    Enregistre les handlers pour résolution conflits calendrier.

    Callbacks:
    - conflict:cancel:<event_id> → Annuler événement
    - conflict:move:<event_id> → Déplacer événement (dialogue multi-étapes)
    - conflict:ignore:<conflict_id> → Ignorer conflit

    Message handlers:
    - Dialogue déplacement step 2: Validation date
    - Dialogue déplacement step 3: Validation heure

    Args:
        application: Telegram Application
        db_pool: Pool PostgreSQL
        redis_client: Client Redis

    Story 7.3 AC6: Résolution conflits via inline buttons + dialogue
    """

    # Wrapper pour injecter dépendances dans bot_data
    async def _conflict_wrapper(update, context):
        if "db_pool" not in context.bot_data:
            context.bot_data["db_pool"] = db_pool
        if "redis_client" not in context.bot_data:
            context.bot_data["redis_client"] = redis_client

        return await handle_conflict_button(update, context)

    # Wrapper pour handlers dialogue déplacement (messages texte)
    async def _move_dialogue_wrapper(update, context):
        if "db_pool" not in context.bot_data:
            context.bot_data["db_pool"] = db_pool
        if "redis_client" not in context.bot_data:
            context.bot_data["redis_client"] = redis_client

        # Try step 2 (date)
        handled = await handle_move_date_response(update, context)
        if handled:
            return

        # Try step 3 (time)
        await handle_move_time_response(update, context)

    # 1. Enregistrer CallbackQueryHandler pour inline buttons conflits
    application.add_handler(CallbackQueryHandler(_conflict_wrapper, pattern=r"^conflict:"))

    # 2. Enregistrer MessageHandler pour dialogue déplacement
    # Filtre : Messages texte privés (pas groupes) ou en réponse
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _move_dialogue_wrapper))

    logger.info("Conflict callbacks handlers registered (Story 7.3)")
