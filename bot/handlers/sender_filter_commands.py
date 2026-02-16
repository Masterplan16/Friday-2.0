"""
Bot Telegram Friday 2.0 - Sender Filter Commands Handlers (Story 2.8, A.6 nouvelle semantique)

Commandes de filtrage sender/domain :
- /vip <email|domain>              Marquer comme VIP (prioritaire)
- /blacklist <email|domain>        Marquer comme blacklist (skip analyse)
- /whitelist <email|domain>        Marquer comme whitelist (analyser normalement)
- /filters [list|stats|delete]     Lister/stats/supprimer filtres
"""

import os
import re

import asyncpg
import structlog
from telegram import Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)

OWNER_USER_ID = os.getenv("OWNER_USER_ID")


# ----------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------


def _validate_email_format(email: str) -> bool:
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def _validate_domain_format(domain: str) -> bool:
    pattern = r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, domain))


def _parse_sender_input(sender_input: str):
    """Parse sender input, retourne (sender_email, sender_domain) ou None si invalide."""
    sender_email = None
    sender_domain = None

    if "@" in sender_input:
        if not _validate_email_format(sender_input):
            return None, None, f"Email invalide : `{sender_input}`"
        sender_email = sender_input
    else:
        if not _validate_domain_format(sender_input):
            return None, None, f"Domain invalide : `{sender_input}`"
        sender_domain = sender_input

    return sender_email, sender_domain, None


def _check_owner(user_id) -> bool:
    return OWNER_USER_ID and str(user_id) == OWNER_USER_ID


async def _add_filter(update, context, filter_type: str, category=None, confidence=None):
    """Helper commun pour ajouter un filtre (vip/whitelist/blacklist)."""
    user_id = update.effective_user.id if update.effective_user else None

    if not _check_owner(user_id):
        await update.message.reply_text("Commande reservee au Mainteneur.")
        return

    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            f"**Usage :** `/{filter_type} <email|domain>`",
            parse_mode="Markdown",
        )
        return

    sender_input = context.args[0].strip().lower()
    sender_email, sender_domain, error = _parse_sender_input(sender_input)
    if error:
        await update.message.reply_text(error, parse_mode="Markdown")
        return

    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await update.message.reply_text("Pool PostgreSQL non disponible.")
        return

    try:
        async with db_pool.acquire() as db:
            filter_id = await db.fetchval(
                """
                INSERT INTO core.sender_filters
                (sender_email, sender_domain, filter_type, category, confidence, created_by)
                VALUES ($1, $2, $3, $4, $5, 'user')
                ON CONFLICT (sender_email) WHERE sender_email IS NOT NULL
                DO UPDATE SET filter_type = EXCLUDED.filter_type,
                              category = EXCLUDED.category,
                              confidence = EXCLUDED.confidence,
                              updated_at = NOW()
                RETURNING id
                """,
                sender_email,
                sender_domain,
                filter_type,
                category,
                confidence,
            )

            logger.info(
                "filter_added",
                user_id=user_id,
                filter_id=str(filter_id),
                filter_type=filter_type,
                sender=sender_email or sender_domain,
            )

            labels = {
                "vip": "VIP (prioritaire + notification immediate)",
                "blacklist": "Blacklist (skip analyse, economie tokens)",
                "whitelist": "Whitelist (analyser normalement)",
            }

            await update.message.reply_text(
                f"**Filtre ajoute**\n\n"
                f"**Sender :** `{sender_email or sender_domain}`\n"
                f"**Type :** {labels.get(filter_type, filter_type)}",
                parse_mode="Markdown",
            )

    except asyncpg.UniqueViolationError:
        await update.message.reply_text(
            f"`{sender_email or sender_domain}` est deja dans les filtres.\n"
            f"Utilisez `/filters delete {sender_email or sender_domain}` puis reessayez.",
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error("filter_add_error", user_id=user_id, error=str(e))
        await update.message.reply_text(f"Erreur : `{type(e).__name__}`", parse_mode="Markdown")


# ----------------------------------------------------------------
# /vip <email|domain>
# ----------------------------------------------------------------


async def vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /vip <email|domain> - Marquer comme VIP."""
    await _add_filter(update, context, filter_type="vip", confidence=0.95)


# ----------------------------------------------------------------
# /blacklist <email|domain>
# ----------------------------------------------------------------


async def blacklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /blacklist <email|domain> - Skip analyse (economie tokens)."""
    await _add_filter(
        update, context, filter_type="blacklist", category="blacklisted", confidence=1.0
    )


# ----------------------------------------------------------------
# /whitelist <email|domain>
# ----------------------------------------------------------------


async def whitelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /whitelist <email|domain> - Analyser normalement."""
    await _add_filter(update, context, filter_type="whitelist", confidence=0.95)


# ----------------------------------------------------------------
# /filters [list|stats|delete]
# ----------------------------------------------------------------


async def filters_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /filters [list|stats|delete <target>]"""
    user_id = update.effective_user.id if update.effective_user else None

    if not _check_owner(user_id):
        await update.message.reply_text("Commande reservee au Mainteneur.")
        return

    subcommand = context.args[0].lower() if context.args else "list"

    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await update.message.reply_text("Pool PostgreSQL non disponible.")
        return

    try:
        async with db_pool.acquire() as db:
            if subcommand == "list":
                filters = await db.fetch("""
                    SELECT sender_email, sender_domain, filter_type, category, created_at
                    FROM core.sender_filters
                    ORDER BY filter_type, created_at DESC
                    """)

                if not filters:
                    await update.message.reply_text(
                        "Aucun filtre actif.\n"
                        "Utilisez `/vip`, `/blacklist` ou `/whitelist` pour ajouter.",
                        parse_mode="Markdown",
                    )
                    return

                vip_items = []
                blacklist_items = []
                whitelist_items = []

                for f in filters:
                    sender = f["sender_email"] or f["sender_domain"]
                    if f["filter_type"] == "vip":
                        vip_items.append(f"  `{sender}`")
                    elif f["filter_type"] == "blacklist":
                        blacklist_items.append(f"  `{sender}`")
                    elif f["filter_type"] == "whitelist":
                        whitelist_items.append(f"  `{sender}`")

                msg = "**Filtres actifs**\n\n"

                if vip_items:
                    msg += f"**VIP ({len(vip_items)}) :**\n" + "\n".join(vip_items[:10])
                    if len(vip_items) > 10:
                        msg += f"\n  _... et {len(vip_items) - 10} autres_"
                    msg += "\n\n"

                if blacklist_items:
                    msg += f"**Blacklist ({len(blacklist_items)}) :**\n" + "\n".join(
                        blacklist_items[:10]
                    )
                    if len(blacklist_items) > 10:
                        msg += f"\n  _... et {len(blacklist_items) - 10} autres_"
                    msg += "\n\n"

                if whitelist_items:
                    msg += f"**Whitelist ({len(whitelist_items)}) :**\n" + "\n".join(
                        whitelist_items[:10]
                    )
                    if len(whitelist_items) > 10:
                        msg += f"\n  _... et {len(whitelist_items) - 10} autres_"

                await update.message.reply_text(msg, parse_mode="Markdown")

            elif subcommand == "stats":
                stats = await db.fetchrow("""
                    SELECT
                        COUNT(*) as total_filters,
                        COUNT(*) FILTER (WHERE filter_type = 'vip') as vip_count,
                        COUNT(*) FILTER (WHERE filter_type = 'blacklist') as blacklist_count,
                        COUNT(*) FILTER (WHERE filter_type = 'whitelist') as whitelist_count
                    FROM core.sender_filters
                    """)

                # Economie tokens reelle depuis core.llm_usage
                savings = await db.fetchrow("""
                    SELECT COALESCE(SUM(tokens_saved_by_filters), 0) as tokens_saved
                    FROM core.llm_usage
                    WHERE date_trunc('month', timestamp) = date_trunc('month', CURRENT_DATE)
                    """)

                msg = (
                    f"**Statistiques filtrage**\n\n"
                    f"**Filtres actifs :**\n"
                    f"  Total : {stats['total_filters']}\n"
                    f"  VIP : {stats['vip_count']}\n"
                    f"  Blacklist : {stats['blacklist_count']}\n"
                    f"  Whitelist : {stats['whitelist_count']}\n\n"
                    f"**Economie ce mois :**\n"
                    f"  ~${stats['blacklist_count'] * 0.006:.2f}/email blackliste\n"
                )

                await update.message.reply_text(msg, parse_mode="Markdown")

            elif subcommand == "delete":
                if not context.args or len(context.args) < 2:
                    await update.message.reply_text(
                        "**Usage :** `/filters delete <email|domain>`",
                        parse_mode="Markdown",
                    )
                    return

                target = context.args[1].strip().lower()
                deleted = await db.execute(
                    """
                    DELETE FROM core.sender_filters
                    WHERE sender_email = $1 OR sender_domain = $1
                    """,
                    target,
                )

                deleted_count = int(deleted.split()[-1]) if deleted else 0

                if deleted_count > 0:
                    logger.info(
                        "filter_deleted", user_id=user_id, target=target, count=deleted_count
                    )
                    await update.message.reply_text(
                        f"Filtre supprime : `{target}` ({deleted_count} entree(s))",
                        parse_mode="Markdown",
                    )
                else:
                    await update.message.reply_text(
                        f"Aucun filtre trouve pour `{target}`", parse_mode="Markdown"
                    )

            else:
                await update.message.reply_text(
                    "**Subcommands :** `/filters list`, `/filters stats`, `/filters delete <target>`",
                    parse_mode="Markdown",
                )

    except Exception as e:
        logger.error("/filters error", user_id=user_id, error=str(e))
        await update.message.reply_text(f"Erreur : `{type(e).__name__}`", parse_mode="Markdown")
