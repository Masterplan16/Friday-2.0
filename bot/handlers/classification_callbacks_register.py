"""
Enregistrement handlers callbacks classification (Story 3.2 Task 5.6)

Enregistre les CallbackQueryHandlers pour les inline buttons classification
"""

import asyncpg
import structlog
from bot.handlers.classification_callbacks import (
    handle_classify_approve,
    handle_classify_back,
    handle_classify_correct,
    handle_classify_finance,
    handle_classify_reclassify,
    handle_classify_reject,
)
from telegram.ext import Application, CallbackQueryHandler

logger = structlog.get_logger(__name__)


def register_classification_callbacks_handlers(application: Application, db_pool: asyncpg.Pool):
    """
    Enregistre les CallbackQueryHandlers pour classification documents.

    Callbacks:
    - classify_approve:* → Approuver classification
    - classify_correct:* → Corriger destination (affiche catégories)
    - classify_reject:* → Rejeter classification
    - classify_reclassify:*:* → Réassigner catégorie
    - classify_finance:*:* → Sélectionner périmètre finance
    - classify_back:* → Retour message original

    Args:
        application: Telegram Application
        db_pool: Pool PostgreSQL

    Story 3.2 Task 5.6: Registration inline buttons classification
    """

    # Wrapper pour injecter db_pool dans callbacks
    async def _approve_wrapper(update, context):
        return await handle_classify_approve(update, context, db_pool)

    async def _correct_wrapper(update, context):
        return await handle_classify_correct(update, context, db_pool)

    async def _reject_wrapper(update, context):
        return await handle_classify_reject(update, context, db_pool)

    async def _reclassify_wrapper(update, context):
        return await handle_classify_reclassify(update, context, db_pool)

    async def _finance_wrapper(update, context):
        return await handle_classify_finance(update, context, db_pool)

    async def _back_wrapper(update, context):
        return await handle_classify_back(update, context, db_pool)

    # Enregistrer handlers avec pattern callback_data
    application.add_handler(CallbackQueryHandler(_approve_wrapper, pattern=r"^classify_approve:"))

    application.add_handler(CallbackQueryHandler(_correct_wrapper, pattern=r"^classify_correct:"))

    application.add_handler(CallbackQueryHandler(_reject_wrapper, pattern=r"^classify_reject:"))

    application.add_handler(
        CallbackQueryHandler(_reclassify_wrapper, pattern=r"^classify_reclassify:")
    )

    application.add_handler(CallbackQueryHandler(_finance_wrapper, pattern=r"^classify_finance:"))

    application.add_handler(CallbackQueryHandler(_back_wrapper, pattern=r"^classify_back:"))

    logger.info("Classification callbacks handlers registered (Story 3.2)")
