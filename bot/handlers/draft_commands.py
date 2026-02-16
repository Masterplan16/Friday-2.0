"""
Commandes Telegram pour brouillons emails

Commande /draft pour générer manuellement un brouillon de réponse email.

Story: 2.5 Brouillon Réponse Email - Task 6 Subtask 6.2
"""

# TODO(M4 - Story future): Migrer vers structlog pour logs structurés JSON
import logging

from telegram import Update
from telegram.ext import ContextTypes

# Import lazy de draft_email_reply (disponible uniquement si agents/ est dans le PYTHONPATH)
draft_email_reply = None


def _get_draft_email_reply():
    global draft_email_reply
    if draft_email_reply is not None:
        return draft_email_reply
    try:
        import sys
        from pathlib import Path

        repo_root = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(repo_root))
        from agents.src.agents.email.draft_reply import draft_email_reply as _fn

        draft_email_reply = _fn
        return draft_email_reply
    except ImportError:
        return None


logger = logging.getLogger(__name__)


async def draft_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Commande /draft [email_id] - Générer brouillon manuellement

    Usage:
        /draft abc-123-def-456

    Args:
        update: Telegram Update
        context: Callback context (contient db_pool)

    Workflow:
        1. Parse email_id depuis args
        2. Fetch email depuis ingestion.emails
        3. Call draft_email_reply()
        4. Notification envoyée automatiquement via @friday_action

    Example:
        User: /draft f47ac10b-58cc-4372-a567-0e02b2c3d479
        Bot: Brouillon en cours de génération...
        [Notification topic Actions apparaît avec inline buttons]
    """

    # Vérifier args
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "❌ **Usage incorrect**\n\n"
            "**Usage:** `/draft <email_id>`\n\n"
            "**Exemple:** `/draft f47ac10b-58cc-4372-a567-0e02b2c3d479`",
            parse_mode="Markdown",
        )
        return

    email_id = context.args[0]

    # Get db_pool from context
    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await update.message.reply_text(
            "❌ **Erreur serveur**\n\n" "Pool de connexions DB non disponible.",
            parse_mode="Markdown",
        )
        logger.error("draft_command_no_db_pool")
        return

    try:
        # Fetch email depuis DB
        async with db_pool.acquire() as conn:
            email = await conn.fetchrow("SELECT * FROM ingestion.emails WHERE id=$1", email_id)

            if not email:
                await update.message.reply_text(
                    f"❌ **Email introuvable**\n\n"
                    f"Aucun email avec ID `{email_id}` dans la base.",
                    parse_mode="Markdown",
                )
                return

        # Confirmation démarrage
        await update.message.reply_text(
            "⏳ **Génération brouillon en cours...**\n\n"
            f"Email: {email['subject'][:50]}...\n"
            f"Expéditeur: {email['sender_email']}\n\n"
            "Vous recevrez une notification dans le topic **Actions** "
            "dès que le brouillon sera prêt.",
            parse_mode="Markdown",
        )

        # Call draft_email_reply (async)
        # La notification sera envoyée automatiquement via @friday_action
        _draft_fn = _get_draft_email_reply()
        if _draft_fn is None:
            await update.message.reply_text(
                "Draft reply agent non disponible (agents/ non deploye)."
            )
            return
        email_data = dict(email)
        result = await _draft_fn(email_id=email_id, email_data=email_data, db_pool=db_pool)

        logger.info(
            "draft_command_success",
            email_id=email_id,
            receipt_id=result.payload.get("receipt_id", "unknown"),
            confidence=result.confidence,
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ **Erreur lors de la génération**\n\n" f"```\n{str(e)[:200]}\n```",
            parse_mode="Markdown",
        )
        logger.error("draft_command_failed", email_id=email_id, error=str(e), exc_info=True)
