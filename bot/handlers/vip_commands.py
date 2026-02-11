"""
Bot Telegram Friday 2.0 - VIP Commands Handlers

Story 2.3 - Task 5 :
- /vip add <email> <label> : Ajouter un expéditeur VIP
- /vip list : Lister tous les VIPs actifs
- /vip remove <email> : Retirer un VIP (soft delete)
"""

import os
import sys
from pathlib import Path

import asyncpg
import structlog
from telegram import Update
from telegram.ext import ContextTypes

# Ajouter repo root au path pour imports
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))

from agents.src.agents.email.vip_detector import compute_email_hash
from agents.src.tools.anonymize import anonymize_text
from bot.handlers.rate_limiter import vip_rate_limiter

logger = structlog.get_logger(__name__)

# Configuration
OWNER_USER_ID = os.getenv("OWNER_USER_ID")  # ID Telegram du Mainteneur


async def vip_command_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Router principal /vip - Dispatche vers sous-commandes.

    Usage:
    - /vip add <email> <label>
    - /vip list
    - /vip remove <email>

    Args:
        update: Update Telegram
        context: Context bot
    """
    if not context.args or len(context.args) == 0:
        await update.message.reply_text(
            "**Usage commande /vip**\n\n"
            "**Sous-commandes disponibles :**\n\n"
            "• `/vip add <email> <label>`\n"
            "  → Ajouter un expéditeur VIP\n\n"
            "• `/vip list`\n"
            "  → Lister tous les VIPs actifs\n\n"
            "• `/vip remove <email>`\n"
            "  → Retirer un VIP (soft delete)\n\n"
            "**Exemples :**\n"
            "• `/vip add doyen@univ-med.fr Doyen Faculte Medecine`\n"
            "• `/vip list`\n"
            "• `/vip remove doyen@univ-med.fr`",
            parse_mode="Markdown",
        )
        return

    subcommand = context.args[0].lower()

    if subcommand == "add":
        # Supprimer "add" des args et passer le reste
        context.args = context.args[1:]
        await vip_add_command(update, context)

    elif subcommand == "list":
        await vip_list_command(update, context)

    elif subcommand == "remove":
        # Supprimer "remove" des args et passer le reste
        context.args = context.args[1:]
        await vip_remove_command(update, context)

    else:
        await update.message.reply_text(
            f"**Sous-commande inconnue** : `{subcommand}`\n\n"
            f"Sous-commandes valides : `add`, `list`, `remove`\n\n"
            f"Tapez `/vip` pour voir l'aide.",
            parse_mode="Markdown",
        )


# ────────────────────────────────────────────────────────────
# Sous-commandes
# ────────────────────────────────────────────────────────────


async def vip_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler /vip add <email> <label> - Ajouter un expéditeur VIP.

    Args:
        update: Update Telegram
        context: Context bot
    """
    user_id = update.effective_user.id if update.effective_user else None
    logger.info("/vip add command received", user_id=user_id, args=context.args)

    # Rate limiting (M1 fix: protection DoS)
    allowed, retry_after = vip_rate_limiter.is_allowed(user_id, "vip_add")
    if not allowed:
        await update.message.reply_text(
            f"⚠️ **Rate limit dépassé**\n\n"
            f"Vous avez atteint la limite de 10 commandes /vip par minute.\n"
            f"Veuillez réessayer dans {retry_after} secondes.",
            parse_mode="Markdown",
        )
        return

    # Vérifier owner uniquement (commande réservée)
    if OWNER_USER_ID and str(user_id) != OWNER_USER_ID:
        await update.message.reply_text(
            "❌ **Commande réservée au Mainteneur**\n\n"
            "Seul le Mainteneur peut ajouter des VIPs.",
            parse_mode="Markdown",
        )
        return

    # Vérifier arguments
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ **Arguments manquants**\n\n"
            "**Usage :** `/vip add <email> <label>`\n\n"
            "**Exemple :**\n"
            "`/vip add doyen@univ-med.fr Doyen Faculte Medecine`",
            parse_mode="Markdown",
        )
        return

    email = context.args[0].strip()
    label = " ".join(context.args[1:]).strip()

    # Validation email basique
    if "@" not in email or "." not in email:
        await update.message.reply_text(
            f"❌ **Email invalide** : `{email}`\n\n" f"Veuillez fournir un email valide.",
            parse_mode="Markdown",
        )
        return

    # Récupérer pool DB depuis bot_data (H1 fix)
    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await update.message.reply_text(
            "❌ **Erreur configuration**\n\n"
            "Pool PostgreSQL non disponible. Le bot doit être redémarré.",
            parse_mode="Markdown",
        )
        logger.error("/vip add failed", error="DB pool not available")
        return

    try:
        # Utiliser pool au lieu de connexion directe (H1 fix)
        async with db_pool.acquire() as db:

        # Étape 1: Anonymiser email (RGPD)
        email_anon = await anonymize_text(email)

        # Étape 2: Calculer hash SHA256
        email_hash = compute_email_hash(email)

        # Étape 3: Vérifier si VIP existe déjà
        existing_vip = await db.fetchrow(
            """
            SELECT id, active, label
            FROM core.vip_senders
            WHERE email_hash = $1
            """,
            email_hash,
        )

        if existing_vip:
            if existing_vip["active"]:
                await update.message.reply_text(
                    f"ℹ️ **VIP déjà existant**\n\n"
                    f"Email (anonymisé) : `{email_anon}`\n"
                    f"Label actuel : `{existing_vip['label']}`\n\n"
                    f"Utilisez `/vip remove` puis `/vip add` pour modifier le label.",
                    parse_mode="Markdown",
                )
                return
            else:
                # VIP existe mais inactif → réactiver
                await db.execute(
                    """
                    UPDATE core.vip_senders
                    SET active = TRUE, label = $1
                    WHERE email_hash = $2
                    """,
                    label,
                    email_hash,
                )

                await update.message.reply_text(
                    f"✅ **VIP réactivé**\n\n"
                    f"Email (anonymisé) : `{email_anon}`\n"
                    f"Label : `{label}`",
                    parse_mode="Markdown",
                )
                logger.info(
                    "/vip add success (reactivated)",
                    user_id=user_id,
                    email_anon=email_anon,
                    label=label,
                )
                return

        # Étape 4: Insérer nouveau VIP
        await db.execute(
            """
            INSERT INTO core.vip_senders (
                email_anon, email_hash, label, designation_source, added_by, active
            ) VALUES ($1, $2, $3, 'manual', $4, TRUE)
            """,
            email_anon,
            email_hash,
            label,
            user_id,
        )

        # Succès
        await update.message.reply_text(
            f"✅ **VIP ajouté avec succès**\n\n"
            f"Email (anonymisé) : `{email_anon}`\n"
            f"Label : `{label}`\n"
            f"Source : Ajout manuel",
            parse_mode="Markdown",
        )

        logger.info("/vip add success", user_id=user_id, email_anon=email_anon, label=label)

    except Exception as e:
        logger.error("/vip add error", user_id=user_id, error=str(e), exc_info=True)
        await update.message.reply_text(
            f"❌ **Erreur lors de l'ajout du VIP**\n\n" f"Erreur : `{str(e)}`", parse_mode="Markdown"
        )


async def vip_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler /vip list - Lister tous les VIPs actifs.

    Args:
        update: Update Telegram
        context: Context bot
    """
    user_id = update.effective_user.id if update.effective_user else None
    logger.info("/vip list command received", user_id=user_id)

    # Récupérer pool DB depuis bot_data (H1 fix)
    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await update.message.reply_text(
            "❌ **Erreur configuration**\n\n"
            "Pool PostgreSQL non disponible. Le bot doit être redémarré.",
            parse_mode="Markdown",
        )
        logger.error("/vip list failed", error="DB pool not available")
        return

    try:
        # Utiliser pool au lieu de connexion directe (H1 fix)
        async with db_pool.acquire() as db:

        # Récupérer tous les VIPs actifs
        vips = await db.fetch(
            """
            SELECT email_anon, label, emails_received_count, last_email_at, designation_source
            FROM core.vip_senders
            WHERE active = TRUE
            ORDER BY emails_received_count DESC, label ASC
            """
        )

        if not vips:
            await update.message.reply_text(
                "ℹ️ **Aucun VIP enregistré**\n\n"
                "Utilisez `/vip add <email> <label>` pour ajouter un VIP.",
                parse_mode="Markdown",
            )
            return

        # Formater liste VIPs
        vip_lines = []
        for vip in vips:
            email_anon = vip["email_anon"]
            label = vip["label"]
            count = vip["emails_received_count"]
            last_email = vip["last_email_at"]
            source = vip["designation_source"]

            last_email_str = last_email.strftime("%Y-%m-%d") if last_email else "Jamais"
            source_emoji = "👤" if source == "manual" else "🤖"

            vip_lines.append(
                f"{source_emoji} **{label}**\n"
                f"   Email : `{email_anon}`\n"
                f"   Emails reçus : {count} | Dernier : {last_email_str}"
            )

        vip_list_text = "\n\n".join(vip_lines)
        total_vips = len(vips)

        await update.message.reply_text(
            f"📋 **Liste des VIPs** ({total_vips} total)\n\n{vip_list_text}", parse_mode="Markdown"
        )

        logger.info("/vip list success", user_id=user_id, total_vips=total_vips)

    except Exception as e:
        logger.error("/vip list error", user_id=user_id, error=str(e), exc_info=True)
        await update.message.reply_text(
            f"❌ **Erreur lors de la récupération des VIPs**\n\n" f"Erreur : `{str(e)}`",
            parse_mode="Markdown",
        )


async def vip_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler /vip remove <email> - Retirer un VIP (soft delete).

    Args:
        update: Update Telegram
        context: Context bot
    """
    user_id = update.effective_user.id if update.effective_user else None
    logger.info("/vip remove command received", user_id=user_id, args=context.args)

    # Rate limiting (M1 fix: protection DoS)
    allowed, retry_after = vip_rate_limiter.is_allowed(user_id, "vip_remove")
    if not allowed:
        await update.message.reply_text(
            f"⚠️ **Rate limit dépassé**\n\n"
            f"Vous avez atteint la limite de 10 commandes /vip par minute.\n"
            f"Veuillez réessayer dans {retry_after} secondes.",
            parse_mode="Markdown",
        )
        return

    # Vérifier owner uniquement (commande réservée)
    if OWNER_USER_ID and str(user_id) != OWNER_USER_ID:
        await update.message.reply_text(
            "❌ **Commande réservée au Mainteneur**\n\n"
            "Seul le Mainteneur peut retirer des VIPs.",
            parse_mode="Markdown",
        )
        return

    # Vérifier arguments
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "❌ **Arguments manquants**\n\n"
            "**Usage :** `/vip remove <email>`\n\n"
            "**Exemple :**\n"
            "`/vip remove doyen@univ-med.fr`",
            parse_mode="Markdown",
        )
        return

    email = context.args[0].strip()

    # Validation email basique
    if "@" not in email or "." not in email:
        await update.message.reply_text(
            f"❌ **Email invalide** : `{email}`\n\n" f"Veuillez fournir un email valide.",
            parse_mode="Markdown",
        )
        return

    # Récupérer pool DB depuis bot_data (H1 fix)
    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await update.message.reply_text(
            "❌ **Erreur configuration**\n\n"
            "Pool PostgreSQL non disponible. Le bot doit être redémarré.",
            parse_mode="Markdown",
        )
        logger.error("/vip remove failed", error="DB pool not available")
        return

    try:
        # Utiliser pool au lieu de connexion directe (H1 fix)
        async with db_pool.acquire() as db:

        # Calculer hash SHA256
        email_hash = compute_email_hash(email)

        # Vérifier si VIP existe
        existing_vip = await db.fetchrow(
            """
            SELECT id, email_anon, label, active
            FROM core.vip_senders
            WHERE email_hash = $1
            """,
            email_hash,
        )

        if not existing_vip:
            await update.message.reply_text(
                f"ℹ️ **VIP non trouvé**\n\n"
                f"Aucun VIP correspondant à cet email n'a été trouvé.\n\n"
                f"Utilisez `/vip list` pour voir la liste des VIPs.",
                parse_mode="Markdown",
            )
            return

        if not existing_vip["active"]:
            await update.message.reply_text(
                f"ℹ️ **VIP déjà inactif**\n\n"
                f"Email (anonymisé) : `{existing_vip['email_anon']}`\n"
                f"Label : `{existing_vip['label']}`\n\n"
                f"Ce VIP est déjà désactivé.",
                parse_mode="Markdown",
            )
            return

        # Soft delete : active = FALSE
        await db.execute(
            """
            UPDATE core.vip_senders
            SET active = FALSE
            WHERE email_hash = $1
            """,
            email_hash,
        )

        # Succès
        await update.message.reply_text(
            f"✅ **VIP retiré avec succès**\n\n"
            f"Email (anonymisé) : `{existing_vip['email_anon']}`\n"
            f"Label : `{existing_vip['label']}`\n\n"
            f"Ce VIP ne sera plus détecté comme prioritaire.",
            parse_mode="Markdown",
        )

        logger.info(
            "/vip remove success",
            user_id=user_id,
            email_anon=existing_vip["email_anon"],
            label=existing_vip["label"],
        )

    except Exception as e:
        logger.error("/vip remove error", user_id=user_id, error=str(e), exc_info=True)
        await update.message.reply_text(
            f"❌ **Erreur lors du retrait du VIP**\n\n" f"Erreur : `{str(e)}`",
            parse_mode="Markdown",
        )
