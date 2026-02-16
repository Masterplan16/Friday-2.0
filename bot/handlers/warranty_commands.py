"""
Commandes Telegram pour le suivi des garanties (Story 3.4 AC6).

Commandes:
- /warranties - Liste toutes garanties actives groupées par catégorie
- /warranty_expiring - Filtre garanties <60 jours
- /warranty_stats - Statistiques (total, montant, prochaine expiration)

Pattern: Story 1.11 (Commands) + Story 2.3 (VIP Commands)
"""

import os

import asyncpg
import structlog
from telegram import Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)

# Icônes par catégorie (AC6)
CATEGORY_ICONS = {
    "electronics": "📦",
    "appliances": "🏠",
    "automotive": "🚗",
    "medical": "🏥",
    "furniture": "🪑",
    "other": "📋",
}

# Noms français des catégories
CATEGORY_NAMES = {
    "electronics": "Electronics",
    "appliances": "Appliances",
    "automotive": "Automotive",
    "medical": "Medical",
    "furniture": "Furniture",
    "other": "Autre",
}


async def _get_db_pool(context: ContextTypes.DEFAULT_TYPE) -> asyncpg.Pool:
    """Récupère le pool DB depuis le contexte bot."""
    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL non configurée")
        db_pool = await asyncpg.create_pool(database_url)
        context.bot_data["db_pool"] = db_pool
    return db_pool


async def _check_owner(update: Update) -> bool:
    """Vérifie que l'utilisateur est le Mainteneur."""
    owner_id = os.getenv("OWNER_USER_ID")
    if owner_id and str(update.effective_user.id) != owner_id:
        await update.message.reply_text("⛔ Accès réservé au Mainteneur.")
        return False
    return True


async def warranties_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /warranties - Liste toutes garanties actives groupées par catégorie (AC6).

    Output:
    📦 Electronics (3)
      • HP DeskJet 3720 - expire 2028-02-04 (dans 729 jours)
    """
    if not await _check_owner(update):
        return

    try:
        db_pool = await _get_db_pool(context)

        rows = await db_pool.fetch("""
            SELECT item_name, item_category, vendor, expiration_date,
                   purchase_amount,
                   (expiration_date - CURRENT_DATE) AS days_remaining
            FROM knowledge.warranties
            WHERE status = 'active'
            ORDER BY item_category, expiration_date ASC
            """)

        if not rows:
            await update.message.reply_text(
                "📦 Aucune garantie active.\n\nUtilisez l'archiviste pour détecter les garanties dans vos documents."
            )
            return

        # Group by category
        categories: dict[str, list] = {}
        for row in rows:
            cat = row["item_category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(row)

        lines = ["📦 <b>Garanties Actives</b>\n"]
        for cat, items in categories.items():
            icon = CATEGORY_ICONS.get(cat, "📋")
            name = CATEGORY_NAMES.get(cat, cat.capitalize())
            lines.append(f"{icon} <b>{name}</b> ({len(items)})")

            for item in items:
                days = item["days_remaining"]
                exp_date = item["expiration_date"].strftime("%d/%m/%Y")
                amount = f" - {item['purchase_amount']:.0f}€" if item["purchase_amount"] else ""
                warning = " ⚠️" if days <= 30 else ""
                lines.append(
                    f"  • {item['item_name']}{amount} - expire {exp_date} "
                    f"(dans {days} jours){warning}"
                )
            lines.append("")

        lines.append(f"Total: {len(rows)} garantie(s) active(s)")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error("warranty_command.error", error=str(e))
        await update.message.reply_text(f"❌ Erreur: {e}")


async def warranty_expiring_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /warranty_expiring - Garanties expirant dans <60 jours (AC6).
    """
    if not await _check_owner(update):
        return

    try:
        db_pool = await _get_db_pool(context)

        rows = await db_pool.fetch("""
            SELECT item_name, item_category, vendor, expiration_date,
                   purchase_amount,
                   (expiration_date - CURRENT_DATE) AS days_remaining
            FROM knowledge.warranties
            WHERE status = 'active'
              AND expiration_date BETWEEN CURRENT_DATE AND (CURRENT_DATE + INTERVAL '60 days')
            ORDER BY expiration_date ASC
            """)

        if not rows:
            await update.message.reply_text(
                "✅ Aucune garantie n'expire dans les 60 prochains jours."
            )
            return

        lines = ["⏰ <b>Garanties Expirant Bientôt</b> (&lt;60 jours)\n"]
        for row in rows:
            days = row["days_remaining"]
            exp_date = row["expiration_date"].strftime("%d/%m/%Y")
            icon = CATEGORY_ICONS.get(row["item_category"], "📋")

            if days <= 7:
                priority = "🚨"
            elif days <= 30:
                priority = "⚠️"
            else:
                priority = "ℹ️"

            lines.append(
                f"{priority} {icon} {row['item_name']} - " f"expire {exp_date} (dans {days} jours)"
            )

        lines.append(f"\nTotal: {len(rows)} garantie(s)")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error("warranty_expiring_command.error", error=str(e))
        await update.message.reply_text(f"❌ Erreur: {e}")


async def warranty_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /warranty_stats - Statistiques garanties (AC6).

    Output:
    📊 Statistiques Garanties
    Actives: 12
    Expirées (12 mois): 3
    Montant total couvert: 4,237.50€
    Prochaine expiration: HP Printer (dans 7 jours)
    """
    if not await _check_owner(update):
        return

    try:
        db_pool = await _get_db_pool(context)

        from agents.src.agents.archiviste.warranty_db import get_warranty_stats

        stats = await get_warranty_stats(db_pool)

        lines = ["📊 <b>Statistiques Garanties</b>\n"]
        lines.append(f"Actives: {stats['total_active']}")
        lines.append(f"Expirées (12 mois): {stats['expired_12m']}")

        total_amount = float(stats.get("total_amount", 0))
        lines.append(f"Montant total couvert: {total_amount:,.2f}€")

        next_exp = stats.get("next_expiry")
        if next_exp:
            lines.append(
                f"\nProchaine expiration: {next_exp['item_name']} "
                f"(dans {next_exp['days_remaining']} jours)"
            )

        # By category breakdown
        by_cat = stats.get("by_category", [])
        if by_cat:
            lines.append("\n<b>Par catégorie:</b>")
            for cat in by_cat:
                icon = CATEGORY_ICONS.get(cat["item_category"], "📋")
                cat_amount = float(cat.get("total_amount", 0))
                lines.append(
                    f"  {icon} {CATEGORY_NAMES.get(cat['item_category'], cat['item_category'])}: "
                    f"{cat['count']} ({cat_amount:,.0f}€)"
                )

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error("warranty_stats_command.error", error=str(e))
        await update.message.reply_text(f"❌ Erreur: {e}")
