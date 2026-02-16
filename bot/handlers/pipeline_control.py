"""
Bot Telegram Friday 2.0 - Pipeline Control Handlers (Phase A.0)

Commandes d'urgence pour controler le pipeline email :
- /pipeline stop   - Kill switch immediat (PIPELINE_ENABLED=false en Redis)
- /pipeline start  - Redemarre le pipeline
- /pipeline status - Etat + conso tokens temps reel
- /budget          - Budget LLM aujourd'hui + ce mois + projection
"""

import os
from datetime import datetime, timezone

import asyncpg
import structlog
from telegram import Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)

OWNER_USER_ID = os.getenv("OWNER_USER_ID")
PIPELINE_REDIS_KEY = "friday:pipeline_enabled"


async def pipeline_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler /pipeline [stop|start|status]

    Controls the email processing pipeline via Redis flag.
    """
    user_id = update.effective_user.id if update.effective_user else None

    if not OWNER_USER_ID or str(user_id) != OWNER_USER_ID:
        await update.message.reply_text(
            "Commande reservee au Mainteneur.",
            parse_mode="Markdown",
        )
        return

    subcommand = context.args[0].lower() if context.args else "status"
    redis_client = context.bot_data.get("redis")

    if not redis_client:
        await update.message.reply_text("Redis non disponible.")
        return

    if subcommand == "stop":
        await redis_client.set(PIPELINE_REDIS_KEY, "false")
        logger.info("pipeline_stopped", user_id=user_id)
        await update.message.reply_text(
            "**Pipeline ARRETE**\n\n"
            "Le consumer email ne traitera plus de nouveaux messages.\n"
            "Commande `/pipeline start` pour redemerrer.",
            parse_mode="Markdown",
        )

    elif subcommand == "start":
        await redis_client.set(PIPELINE_REDIS_KEY, "true")
        logger.info("pipeline_started", user_id=user_id)
        await update.message.reply_text(
            "**Pipeline DEMARRE**\n\n" "Le consumer email reprend le traitement.",
            parse_mode="Markdown",
        )

    elif subcommand == "status":
        enabled = await redis_client.get(PIPELINE_REDIS_KEY)
        is_enabled = enabled == "true" if enabled else False

        # Lire budget du jour depuis core.llm_usage
        db_pool = context.bot_data.get("db_pool")
        cost_today = 0.0
        count_today = 0

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        SELECT COALESCE(SUM(cost_usd), 0) as cost,
                               COUNT(*) as cnt
                        FROM core.llm_usage
                        WHERE timestamp::date = CURRENT_DATE
                        """)
                    if row:
                        cost_today = float(row["cost"])
                        count_today = row["cnt"]
            except Exception as e:
                logger.warning("pipeline_status_db_error", error=str(e))

        status_icon = "ACTIF" if is_enabled else "ARRETE"
        max_daily = float(os.getenv("MAX_CLAUDE_COST_PER_DAY", "50"))
        alert_threshold = float(os.getenv("ALERT_THRESHOLD_COST", "40"))

        msg = (
            f"**Pipeline : {status_icon}**\n\n"
            f"**Budget aujourd'hui :**\n"
            f"- Depense : ${cost_today:.2f} / ${max_daily:.0f}\n"
            f"- Appels LLM : {count_today}\n"
            f"- Alerte a : ${alert_threshold:.0f}\n"
        )

        if cost_today >= alert_threshold:
            msg += f"\n**ATTENTION** : Seuil alerte atteint ({cost_today:.0f}% du budget)"

        await update.message.reply_text(msg, parse_mode="Markdown")

    else:
        await update.message.reply_text(
            "**Usage :** `/pipeline [stop|start|status]`",
            parse_mode="Markdown",
        )


async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler /budget - Affiche budget LLM aujourd'hui + ce mois + projection.
    """
    user_id = update.effective_user.id if update.effective_user else None

    if not OWNER_USER_ID or str(user_id) != OWNER_USER_ID:
        await update.message.reply_text("Commande reservee au Mainteneur.")
        return

    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await update.message.reply_text("Base de donnees non disponible.")
        return

    try:
        async with db_pool.acquire() as conn:
            # Budget aujourd'hui
            today = await conn.fetchrow("""
                SELECT COALESCE(SUM(cost_usd), 0) as cost,
                       COUNT(*) as calls,
                       COALESCE(SUM(input_tokens), 0) as input_tokens,
                       COALESCE(SUM(output_tokens), 0) as output_tokens
                FROM core.llm_usage
                WHERE timestamp::date = CURRENT_DATE
                """)

            # Budget ce mois
            month = await conn.fetchrow("""
                SELECT COALESCE(SUM(cost_usd), 0) as cost,
                       COUNT(*) as calls
                FROM core.llm_usage
                WHERE date_trunc('month', timestamp) = date_trunc('month', CURRENT_DATE)
                """)

            # Budget par contexte (classification, extraction, embeddings)
            by_context = await conn.fetch("""
                SELECT context,
                       COALESCE(SUM(cost_usd), 0) as cost,
                       COUNT(*) as calls
                FROM core.llm_usage
                WHERE date_trunc('month', timestamp) = date_trunc('month', CURRENT_DATE)
                GROUP BY context
                ORDER BY cost DESC
                LIMIT 5
                """)

        # Projection fin de mois
        now = datetime.now(timezone.utc)
        day_of_month = now.day
        days_in_month = 30  # Approximation
        month_cost = float(month["cost"])
        projection = (month_cost / max(day_of_month, 1)) * days_in_month if month_cost > 0 else 0

        msg = (
            f"**Budget LLM**\n\n"
            f"**Aujourd'hui :**\n"
            f"- Cout : ${float(today['cost']):.2f}\n"
            f"- Appels : {today['calls']}\n"
            f"- Tokens : {today['input_tokens']:,} in / {today['output_tokens']:,} out\n\n"
            f"**Ce mois :**\n"
            f"- Cout : ${month_cost:.2f}\n"
            f"- Appels : {month['calls']}\n"
            f"- Projection fin de mois : ~${projection:.0f}\n\n"
        )

        if by_context:
            msg += "**Par contexte (ce mois) :**\n"
            for row in by_context:
                ctx = row["context"] or "unknown"
                msg += f"- {ctx} : ${float(row['cost']):.2f} ({row['calls']} appels)\n"

        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        logger.error("/budget error", error=str(e))
        await update.message.reply_text(f"Erreur : `{type(e).__name__}`", parse_mode="Markdown")
