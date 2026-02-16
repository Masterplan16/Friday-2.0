"""
Inline button callbacks pour validation garanties (Story 3.4 AC5).

Callbacks:
- warranty_confirm:{warranty_id} → Approuver (store in DB)
- warranty_edit:{warranty_id} → Corriger (prompt user)
- warranty_delete:{warranty_id} → Ignorer (false positive)

Pattern: Story 1.10 (Inline Buttons) + Story 3.2 (Classification Callbacks)
"""

from typing import Optional

import asyncpg
import structlog
from agents.src.agents.archiviste.warranty_db import delete_warranty
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
)

logger = structlog.get_logger(__name__)


def build_warranty_inline_keyboard(warranty_id: str) -> InlineKeyboardMarkup:
    """Build inline keyboard for warranty validation (AC5)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Approuver",
                    callback_data=f"warranty_confirm:{warranty_id}",
                ),
                InlineKeyboardButton(
                    "✏️ Corriger",
                    callback_data=f"warranty_edit:{warranty_id}",
                ),
                InlineKeyboardButton(
                    "🗑️ Ignorer",
                    callback_data=f"warranty_delete:{warranty_id}",
                ),
            ]
        ]
    )


async def callback_warranty_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle warranty confirmation button (AC5)."""
    query = update.callback_query
    await query.answer()

    data = query.data
    warranty_id = data.split(":")[1] if ":" in data else ""

    if not warranty_id:
        await query.edit_message_text("❌ ID garantie manquant")
        return

    try:
        db_pool = context.bot_data.get("db_pool")
        if db_pool:
            # Update receipt status to approved
            await db_pool.execute(
                """
                UPDATE core.action_receipts
                SET status = 'approved', updated_at = NOW()
                WHERE payload->>'warranty_id' = $1 AND status = 'pending'
                """,
                warranty_id,
            )

        original_text = query.message.text or query.message.caption or ""
        await query.edit_message_text(
            f"✅ Garantie approuvée\n\n{original_text}",
            parse_mode="HTML",
        )

        logger.info("warranty_callback.confirmed", warranty_id=warranty_id)

    except Exception as e:
        logger.error("warranty_callback.confirm_error", error=str(e))
        await query.edit_message_text(f"❌ Erreur confirmation: {e}")


async def callback_warranty_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle warranty edit button - prompt user for corrections (AC5)."""
    query = update.callback_query
    await query.answer()

    data = query.data
    warranty_id = data.split(":")[1] if ":" in data else ""

    await query.edit_message_text(
        f"✏️ <b>Correction garantie</b>\n\n"
        f"ID: <code>{warranty_id}</code>\n\n"
        f"Pour corriger, répondez avec les informations corrigées au format:\n"
        f"<code>/warranty_correct {warranty_id} champ=valeur</code>\n\n"
        f"Champs: item_name, vendor, purchase_date, duration_months, amount, category",
        parse_mode="HTML",
    )

    logger.info("warranty_callback.edit_requested", warranty_id=warranty_id)


async def callback_warranty_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle warranty deletion button - false positive (AC5)."""
    query = update.callback_query
    await query.answer()

    data = query.data
    warranty_id = data.split(":")[1] if ":" in data else ""

    if not warranty_id:
        await query.edit_message_text("❌ ID garantie manquant")
        return

    try:
        db_pool = context.bot_data.get("db_pool")
        if db_pool:
            deleted = await delete_warranty(db_pool, warranty_id)

            # Also reject the receipt
            await db_pool.execute(
                """
                UPDATE core.action_receipts
                SET status = 'rejected', updated_at = NOW()
                WHERE payload->>'warranty_id' = $1 AND status = 'pending'
                """,
                warranty_id,
            )

            if deleted:
                await query.edit_message_text("🗑️ Garantie ignorée (faux positif)")
            else:
                await query.edit_message_text("⚠️ Garantie non trouvée ou déjà supprimée")
        else:
            await query.edit_message_text("❌ Base de données non disponible")

        logger.info("warranty_callback.deleted", warranty_id=warranty_id)

    except Exception as e:
        logger.error("warranty_callback.delete_error", error=str(e))
        await query.edit_message_text(f"❌ Erreur suppression: {e}")


def register_warranty_callbacks_handlers(
    application: Application,
    db_pool: Optional[asyncpg.Pool] = None,
) -> None:
    """Register warranty callback handlers in bot application."""
    application.add_handler(
        CallbackQueryHandler(
            callback_warranty_confirm,
            pattern=r"^warranty_confirm:",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            callback_warranty_edit,
            pattern=r"^warranty_edit:",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            callback_warranty_delete,
            pattern=r"^warranty_delete:",
        )
    )
    logger.info("warranty_callback_handlers_registered")
