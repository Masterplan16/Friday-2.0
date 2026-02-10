"""
Bot Telegram Friday 2.0 - Command Handlers

Handlers pour toutes les commandes Telegram (/ prefix).
"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler /help - Affiche liste complète des commandes (AC5).

    Args:
        update: Update Telegram
        context: Context bot
    """
    user_id = update.effective_user.id if update.effective_user else None
    logger.info("/help command received", user_id=user_id)

    help_text = """📋 **Commandes Friday 2.0**

💬 **CONVERSATION**
• Message libre - Pose une question à Friday

🔍 **CONSULTATION**
• `/status` - État système (services, RAM, actions)
• `/journal` - 20 dernières actions
• `/receipt <id>` - Détail d'une action (-v pour steps)
• `/confiance` - Accuracy par module/action
• `/stats` - Métriques globales
• `/budget` - Consommation API Claude du mois

📚 Plus d'infos: `docs/telegram-user-guide.md`
"""

    await update.message.reply_text(help_text, parse_mode="Markdown")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler /start - Alias de /help.

    Args:
        update: Update Telegram
        context: Context bot
    """
    await help_command(update, context)
