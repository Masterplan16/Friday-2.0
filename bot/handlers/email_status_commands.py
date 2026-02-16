#!/usr/bin/env python3
"""
Friday 2.0 - Telegram Commands: Email Pipeline Status

Commandes de monitoring du pipeline email.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.email_healthcheck.monitor import check_email_pipeline_health, format_status_message
from telegram import Update
from telegram.ext import ContextTypes


async def email_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler pour /email-status : Affiche l'état du pipeline email.

    Usage:
        /email-status - Affiche status complet
    """
    if not update.message:
        return

    # Send "typing..." indicator
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        # Check pipeline health
        health = await check_email_pipeline_health()

        # Format message
        message = format_status_message(health)

        # Send to Telegram
        await update.message.reply_text(message, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(
            f"❌ Erreur lors de la vérification du pipeline:\n\n`{e}`", parse_mode="Markdown"
        )


# Export handlers
__all__ = ["email_status_command"]
