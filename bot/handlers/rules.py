"""
Bot Telegram - Commandes /rules CRUD (Story 1.7, AC5).

Permet à Antonio de gérer les correction_rules via Telegram.
"""

import asyncpg
import structlog
from telegram import Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)


class RulesHandler:
    """Handler commandes /rules CRUD."""

    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool

    async def list_rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/rules list : Affiche règles actives triées par priorité (AC5)."""
        query = "SELECT id, module, action_type, rule_name, priority, hit_count FROM core.correction_rules WHERE active = true ORDER BY priority ASC LIMIT 20"

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(query)

        if not rows:
            await update.message.reply_text("Aucune règle active.")
            return

        text = "📋 **Règles actives**\n\n"
        for row in rows:
            text += f"• `{row['rule_name']}` (P{row['priority']}, {row['hit_count']}x)\n  {row['module']}.{row['action_type']}\n"

        await update.message.reply_text(text, parse_mode="Markdown")

    async def show_rule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/rules show <id> : Détail complet règle (AC5)."""
        if not context.args:
            await update.message.reply_text("Usage: `/rules show <rule_id>`", parse_mode="Markdown")
            return

        rule_id = context.args[0]
        query = "SELECT * FROM core.correction_rules WHERE id::text LIKE $1 || '%'"

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(query, rule_id[:8])

        if not row:
            await update.message.reply_text(
                f"Règle `{rule_id}` introuvable.", parse_mode="Markdown"
            )
            return

        text = (
            f"📋 **Règle {row['rule_name']}**\n\n"
            f"**Scope** : {row['scope']}\n"
            f"**Priority** : {row['priority']}\n"
            f"**Module** : {row['module']}.{row['action_type']}\n"
            f"**Conditions** : `{row['conditions']}`\n"
            f"**Output** : `{row['output']}`\n"
            f"**Hit count** : {row['hit_count']}\n"
            f"**Active** : {row['active']}\n"
        )

        await update.message.reply_text(text, parse_mode="Markdown")

    async def delete_rule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/rules delete <id> : Désactive règle (active=false) (AC5)."""
        if not context.args:
            await update.message.reply_text(
                "Usage: `/rules delete <rule_id>`", parse_mode="Markdown"
            )
            return

        rule_id = context.args[0]
        query = "UPDATE core.correction_rules SET active = false WHERE id::text LIKE $1 || '%' RETURNING rule_name"

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(query, rule_id[:8])

        if not row:
            await update.message.reply_text(
                f"Règle `{rule_id}` introuvable.", parse_mode="Markdown"
            )
            return

        await update.message.reply_text(
            f"✅ Règle `{row['rule_name']}` désactivée.", parse_mode="Markdown"
        )
        logger.info("Rule deleted", rule_id=rule_id, rule_name=row["rule_name"])


def register_rules_handlers(application, db_pool: asyncpg.Pool):
    """Enregistre handlers /rules dans application Telegram."""
    from telegram.ext import CommandHandler

    handler = RulesHandler(db_pool)

    # Dispatcher par sous-commande
    async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text(
                "📋 **Commandes /rules**\n\n"
                "`/rules list` - Liste règles actives\n"
                "`/rules show <id>` - Détail règle\n"
                "`/rules delete <id>` - Désactiver règle\n",
                parse_mode="Markdown",
            )
            return

        subcmd = context.args[0].lower()
        context.args = context.args[1:]  # Shift args

        if subcmd == "list":
            await handler.list_rules(update, context)
        elif subcmd == "show":
            await handler.show_rule(update, context)
        elif subcmd == "delete":
            await handler.delete_rule(update, context)
        else:
            await update.message.reply_text(
                f"Sous-commande `{subcmd}` inconnue. Utilise `/rules` pour aide.",
                parse_mode="Markdown",
            )

    application.add_handler(CommandHandler("rules", rules_command))
    logger.info("Rules handlers enregistrés")
