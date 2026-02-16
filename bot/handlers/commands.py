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

👤 **VIP & URGENCE**
• `/vip add <email> <label>` - Ajouter un VIP
• `/vip list` - Lister les VIPs
• `/vip remove <email>` - Retirer un VIP

📎 **FICHIERS** (Story 3.6)
• **Upload** - Glisser-déposer fichier (PDF, Office, images)
• **Recherche** - Message naturel: "Envoie-moi la facture du plombier"
• `/search <query>` - Recherche sémantique documents
• `/arbo` - Voir arborescence documents
• `/arbo stats` - Statistiques classification

📅 **CALENDRIER & MULTI-CASQUETTES** (Story 7.2-7.3)
• `/casquette` - Changer casquette (médecin/enseignant/chercheur)
• `/conflits` - Voir conflits calendrier (7j par défaut)
• `/conflits 14j` - Conflits 14 prochains jours
• `/calendar sync` - Forcer sync Google Calendar

🔄 **DÉDUPLICATION** (Story 3.8)
• `/scan_dedup` - Scanner le PC pour trouver les doublons

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
