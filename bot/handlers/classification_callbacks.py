"""
Callbacks inline buttons classification documents (Story 3.2 Task 5.2-5.3)

Gère les actions : Approve, Correct destination, Reject, Reclassify, Finance perimeter
pour documents classifiés par l'agent Archiviste.
"""

import logging
import os
import uuid

import asyncpg
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


# ============================================================================
# CALLBACK APPROVE - Approuver classification (Task 5.2)
# ============================================================================


async def handle_classify_approve(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db_pool: asyncpg.Pool
):
    """
    Callback button [Approuver]

    Actions :
    1. Update action_receipts status pending → approved
    2. Éditer message Telegram : ✅ Classification approuvée
    3. Notifier topic Metrics

    Args:
        update: Update Telegram
        context: Context Telegram
        db_pool: Pool PostgreSQL

    Story 3.2 Task 5.2: Approve classification
    """
    query = update.callback_query
    await query.answer()

    # Vérifier autorisation owner
    owner_user_id = int(os.getenv("OWNER_USER_ID", "0"))
    if query.from_user.id != owner_user_id:
        await query.answer("Non autorisé", show_alert=True)
        return

    # Parser callback_data : "classify_approve:receipt_id"
    callback_parts = query.data.split(":")
    if len(callback_parts) != 2:
        logger.error("Invalid callback_data", callback_data=query.data)
        await query.edit_message_text("❌ Erreur : callback invalide")
        return

    receipt_id = callback_parts[1]

    try:
        async with db_pool.acquire() as conn:
            # Update action_receipts status
            result = await conn.execute(
                """
                UPDATE core.action_receipts
                SET status = 'approved',
                    validated_by = $2,
                    updated_at = NOW()
                WHERE id = $1 AND status = 'pending'
                """,
                uuid.UUID(receipt_id),
                query.from_user.id,
            )

            if result == "UPDATE 0":
                await query.answer("Action déjà traitée ou introuvable", show_alert=True)
                return

        # Éditer message Telegram
        original_text = query.message.text or ""
        await query.edit_message_text(
            original_text + "\n\n✅ Classification approuvée",
        )

        # Notifier topic Metrics
        metrics_topic_id = int(os.getenv("TOPIC_METRICS_ID", "0"))
        supergroup_id = int(os.getenv("TELEGRAM_SUPERGROUP_ID", "0"))
        if metrics_topic_id and supergroup_id:
            try:
                await context.bot.send_message(
                    chat_id=supergroup_id,
                    message_thread_id=metrics_topic_id,
                    text=f"✅ Classification approuvée\nReceipt: {receipt_id[:8]}...",
                )
            except Exception as notif_err:
                logger.warning("Failed to send metrics notification", error=str(notif_err))

        logger.info("classification_approved", receipt_id=receipt_id, user_id=query.from_user.id)

    except Exception as e:
        logger.error("classify_approve_failed", receipt_id=receipt_id, error=str(e), exc_info=True)
        await query.edit_message_text(f"❌ Erreur lors de l'approbation : {str(e)[:200]}")


# ============================================================================
# CALLBACK CORRECT - Corriger destination (Task 5.3)
# ============================================================================


async def handle_classify_correct(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db_pool: asyncpg.Pool
):
    """
    Callback button [Corriger destination]

    Affiche liste des catégories disponibles pour réassignation.

    Args:
        update: Update Telegram
        context: Context Telegram
        db_pool: Pool PostgreSQL

    Story 3.2 Task 5.3: Corriger destination avec liste catégories
    """
    query = update.callback_query
    await query.answer()

    # Vérifier autorisation owner
    owner_user_id = int(os.getenv("OWNER_USER_ID", "0"))
    if query.from_user.id != owner_user_id:
        await query.answer("Non autorisé", show_alert=True)
        return

    callback_parts = query.data.split(":")
    if len(callback_parts) != 2:
        logger.error("Invalid callback_data", callback_data=query.data)
        return

    receipt_id = callback_parts[1]

    from bot.handlers.classification_notifications import _create_correction_keyboard

    await query.edit_message_text(
        "📂 <b>Corriger la destination</b>\n\n" "Choisissez la catégorie correcte :",
        parse_mode="HTML",
        reply_markup=_create_correction_keyboard(receipt_id),
    )

    logger.info(
        "classification_correction_requested", receipt_id=receipt_id, user_id=query.from_user.id
    )


# ============================================================================
# CALLBACK REJECT - Rejeter classification (Task 5.2)
# ============================================================================


async def handle_classify_reject(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db_pool: asyncpg.Pool
):
    """
    Callback button [Rejeter]

    Args:
        update: Update Telegram
        context: Context Telegram
        db_pool: Pool PostgreSQL

    Story 3.2 Task 5.2: Reject classification
    """
    query = update.callback_query
    await query.answer()

    owner_user_id = int(os.getenv("OWNER_USER_ID", "0"))
    if query.from_user.id != owner_user_id:
        await query.answer("Non autorisé", show_alert=True)
        return

    callback_parts = query.data.split(":")
    if len(callback_parts) != 2:
        logger.error("Invalid callback_data", callback_data=query.data)
        return

    receipt_id = callback_parts[1]

    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE core.action_receipts
                SET status = 'rejected',
                    validated_by = $2,
                    updated_at = NOW()
                WHERE id = $1 AND status = 'pending'
                """,
                uuid.UUID(receipt_id),
                query.from_user.id,
            )

            if result == "UPDATE 0":
                await query.answer("Action déjà traitée ou introuvable", show_alert=True)
                return

        original_text = query.message.text or ""
        await query.edit_message_text(
            original_text + "\n\n❌ Classification rejetée",
        )

        # Notifier topic Metrics
        metrics_topic_id = int(os.getenv("TOPIC_METRICS_ID", "0"))
        supergroup_id = int(os.getenv("TELEGRAM_SUPERGROUP_ID", "0"))
        if metrics_topic_id and supergroup_id:
            try:
                await context.bot.send_message(
                    chat_id=supergroup_id,
                    message_thread_id=metrics_topic_id,
                    text=f"❌ Classification rejetée\nReceipt: {receipt_id[:8]}...",
                )
            except Exception as notif_err:
                logger.warning("Failed to send metrics notification", error=str(notif_err))

        logger.info("classification_rejected", receipt_id=receipt_id, user_id=query.from_user.id)

    except Exception as e:
        logger.error("classify_reject_failed", receipt_id=receipt_id, error=str(e), exc_info=True)
        await query.edit_message_text(f"❌ Erreur lors du rejet : {str(e)[:200]}")


# ============================================================================
# CALLBACK RECLASSIFY - Réassigner catégorie (Task 5.3)
# ============================================================================


async def handle_classify_reclassify(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db_pool: asyncpg.Pool
):
    """
    Callback reclassification : choix d'une nouvelle catégorie.

    Si finance → affiche sous-menu périmètres.
    Sinon → applique directement la nouvelle catégorie.

    Args:
        update: Update Telegram
        context: Context Telegram
        db_pool: Pool PostgreSQL

    Story 3.2 Task 5.3: Reclassification après correction
    """
    query = update.callback_query
    await query.answer()

    owner_user_id = int(os.getenv("OWNER_USER_ID", "0"))
    if query.from_user.id != owner_user_id:
        await query.answer("Non autorisé", show_alert=True)
        return

    # Parser callback_data : "classify_reclassify:receipt_id:category"
    callback_parts = query.data.split(":")
    if len(callback_parts) != 3:
        logger.error("Invalid callback_data", callback_data=query.data)
        return

    receipt_id = callback_parts[1]
    new_category = callback_parts[2]

    # Si finance → afficher sous-menu périmètres
    if new_category == "finance":
        from bot.handlers.classification_notifications import _create_finance_perimeter_keyboard

        await query.edit_message_text(
            "💰 <b>Sélectionner le périmètre finance</b>\n\n" "Choisissez le périmètre correct :",
            parse_mode="HTML",
            reply_markup=_create_finance_perimeter_keyboard(receipt_id),
        )
        return

    # Catégorie non-finance → appliquer directement
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ingestion.document_metadata
                SET classification_category = $2,
                    classification_subcategory = NULL
                WHERE document_id = (
                    SELECT (payload->>'document_id')::text
                    FROM core.action_receipts WHERE id = $1
                )
                """,
                uuid.UUID(receipt_id),
                new_category,
            )

            await conn.execute(
                """
                UPDATE core.action_receipts
                SET status = 'corrected',
                    validated_by = $2,
                    updated_at = NOW()
                WHERE id = $1
                """,
                uuid.UUID(receipt_id),
                query.from_user.id,
            )

        category_labels = {
            "pro": "Professionnel",
            "universite": "Université",
            "recherche": "Recherche",
            "perso": "Personnel",
        }
        label = category_labels.get(new_category, new_category)

        await query.edit_message_text(
            f"📂 <b>Classification corrigée</b>\n\n"
            f"Nouvelle catégorie : {label}\n\n"
            f"<i>Corrigé par {query.from_user.first_name}</i>",
            parse_mode="HTML",
        )

        logger.info(
            "classification_reclassified",
            receipt_id=receipt_id,
            new_category=new_category,
            user_id=query.from_user.id,
        )

    except Exception as e:
        logger.error(
            "classify_reclassify_failed", receipt_id=receipt_id, error=str(e), exc_info=True
        )
        await query.edit_message_text(f"❌ Erreur lors de la reclassification : {str(e)[:200]}")


# ============================================================================
# CALLBACK FINANCE PERIMETER - Sélection périmètre (Task 5.3)
# ============================================================================


async def handle_classify_finance(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db_pool: asyncpg.Pool
):
    """
    Callback sélection périmètre finance.

    Args:
        update: Update Telegram
        context: Context Telegram
        db_pool: Pool PostgreSQL

    Story 3.2 Task 5.3: Sélection périmètre finance
    """
    query = update.callback_query
    await query.answer()

    owner_user_id = int(os.getenv("OWNER_USER_ID", "0"))
    if query.from_user.id != owner_user_id:
        await query.answer("Non autorisé", show_alert=True)
        return

    # Parser callback_data : "classify_finance:receipt_id:perimeter"
    callback_parts = query.data.split(":")
    if len(callback_parts) != 3:
        logger.error("Invalid callback_data", callback_data=query.data)
        return

    receipt_id = callback_parts[1]
    perimeter = callback_parts[2]

    # Validation périmètre (anti-contamination AC6)
    valid_perimeters = {"selarl", "scm", "sci_ravas", "sci_malbosc", "personal"}
    if perimeter not in valid_perimeters:
        await query.answer(f"Périmètre invalide : {perimeter}", show_alert=True)
        return

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ingestion.document_metadata
                SET classification_category = 'finance',
                    classification_subcategory = $2
                WHERE document_id = (
                    SELECT (payload->>'document_id')::text
                    FROM core.action_receipts WHERE id = $1
                )
                """,
                uuid.UUID(receipt_id),
                perimeter,
            )

            await conn.execute(
                """
                UPDATE core.action_receipts
                SET status = 'corrected',
                    validated_by = $2,
                    updated_at = NOW()
                WHERE id = $1
                """,
                uuid.UUID(receipt_id),
                query.from_user.id,
            )

        finance_labels = {
            "selarl": "SELARL",
            "scm": "SCM",
            "sci_ravas": "SCI Ravas",
            "sci_malbosc": "SCI Malbosc",
            "personal": "Personnel",
        }
        label = finance_labels.get(perimeter, perimeter)

        await query.edit_message_text(
            f"💰 <b>Classification corrigée</b>\n\n"
            f"Catégorie : Finance > {label}\n\n"
            f"<i>Corrigé par {query.from_user.first_name}</i>",
            parse_mode="HTML",
        )

        logger.info(
            "classification_finance_perimeter_set",
            receipt_id=receipt_id,
            perimeter=perimeter,
            user_id=query.from_user.id,
        )

    except Exception as e:
        logger.error("classify_finance_failed", receipt_id=receipt_id, error=str(e), exc_info=True)
        await query.edit_message_text(f"❌ Erreur lors de la correction finance : {str(e)[:200]}")


# ============================================================================
# CALLBACK BACK - Retour message original (Task 5.3)
# ============================================================================


async def handle_classify_back(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db_pool: asyncpg.Pool
):
    """
    Callback [Retour] : restaure le message original avec inline buttons.

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

    receipt_id = callback_parts[1]

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT payload, module, action_type, output_summary, confidence
                FROM core.action_receipts WHERE id = $1
                """,
                uuid.UUID(receipt_id),
            )

            if not row:
                await query.edit_message_text("❌ Receipt introuvable")
                return

        from bot.handlers.classification_notifications import (
            _create_classification_keyboard,
            _format_classification_message,
        )

        payload = row["payload"] or {}
        classification_data = {
            "document_id": payload.get("document_id", receipt_id[:8]),
            "category": payload.get("category", "unknown"),
            "subcategory": payload.get("subcategory"),
            "path": payload.get("path", ""),
            "confidence": row["confidence"] or 0.0,
            "reasoning": payload.get("reasoning", ""),
            "receipt_id": receipt_id,
        }

        message = _format_classification_message(classification_data)
        keyboard = _create_classification_keyboard(receipt_id)

        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)

    except Exception as e:
        logger.error("classify_back_failed", receipt_id=receipt_id, error=str(e), exc_info=True)
