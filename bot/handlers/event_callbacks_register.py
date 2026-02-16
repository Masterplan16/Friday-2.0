"""
Enregistrement handlers callbacks événements (Story 7.1 Task 5.3)

Enregistre les CallbackQueryHandlers pour les inline buttons événements
"""

import asyncpg
from telegram.ext import Application, CallbackQueryHandler
import structlog

from bot.handlers.event_callbacks import (
    handle_event_approve,
    handle_event_modify,
    handle_event_ignore,
    handle_event_back,
)

logger = structlog.get_logger(__name__)


def register_event_callbacks_handlers(application: Application, db_pool: asyncpg.Pool):
    """
    Enregistre les CallbackQueryHandlers pour événements

    Callbacks:
    - event_approve:* → handle_event_approve
    - event_modify:* → handle_event_modify
    - event_ignore:* → handle_event_ignore
    - event_back:* → handle_event_back

    Args:
        application: Telegram Application
        db_pool: Pool PostgreSQL

    Story 7.1 AC3: Inline buttons [Ajouter] [Modifier] [Ignorer]
    """

    # Wrapper pour injecter db_pool dans callbacks
    async def _approve_wrapper(update, context):
        return await handle_event_approve(update, context, db_pool)

    async def _modify_wrapper(update, context):
        return await handle_event_modify(update, context, db_pool)

    async def _ignore_wrapper(update, context):
        return await handle_event_ignore(update, context, db_pool)

    async def _back_wrapper(update, context):
        return await handle_event_back(update, context, db_pool)

    # Enregistrer handlers avec pattern callback_data
    application.add_handler(CallbackQueryHandler(_approve_wrapper, pattern=r"^event_approve:"))

    application.add_handler(CallbackQueryHandler(_modify_wrapper, pattern=r"^event_modify:"))

    application.add_handler(CallbackQueryHandler(_ignore_wrapper, pattern=r"^event_ignore:"))

    application.add_handler(CallbackQueryHandler(_back_wrapper, pattern=r"^event_back:"))

    logger.info("Event callbacks handlers registered (Story 7.1)")
