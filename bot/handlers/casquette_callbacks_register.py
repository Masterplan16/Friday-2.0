"""
Enregistrement handlers callbacks casquettes (Story 7.3 Task 3.3)

Enregistre les CallbackQueryHandlers pour les inline buttons casquettes
"""

import asyncpg
import redis.asyncio as redis
from telegram.ext import Application, CallbackQueryHandler
import structlog

from bot.handlers.casquette_callbacks import handle_casquette_button


logger = structlog.get_logger(__name__)


def register_casquette_callbacks_handlers(
    application: Application,
    db_pool: asyncpg.Pool,
    redis_client: redis.Redis
):
    """
    Enregistre les CallbackQueryHandlers pour casquettes.

    Callbacks:
    - casquette:medecin → Force contexte médecin
    - casquette:enseignant → Force contexte enseignant
    - casquette:chercheur → Force contexte chercheur
    - casquette:auto → Réactive auto-detect

    Args:
        application: Telegram Application
        db_pool: Pool PostgreSQL
        redis_client: Client Redis

    Story 7.3 AC2: Inline buttons [Médecin] [Enseignant] [Chercheur] [Auto]
    """
    # Wrapper pour injecter db_pool et redis_client dans bot_data
    async def _casquette_wrapper(update, context):
        # Injecter db_pool et redis_client dans bot_data si pas déjà fait
        if "db_pool" not in context.bot_data:
            context.bot_data["db_pool"] = db_pool
        if "redis_client" not in context.bot_data:
            context.bot_data["redis_client"] = redis_client

        return await handle_casquette_button(update, context)

    # Enregistrer handler avec pattern callback_data
    application.add_handler(
        CallbackQueryHandler(_casquette_wrapper, pattern=r"^casquette:")
    )

    logger.info("Casquette callbacks handlers registered (Story 7.3)")
