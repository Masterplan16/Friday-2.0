"""
Handlers pour commandes recovery Telegram - Story 1.13
/recovery : Liste événements recovery
"""

import asyncpg
from telegram import Update
from telegram.ext import ContextTypes

from .formatters import format_timestamp, parse_verbose_flag
from .messages import send_message_with_split


async def _get_pool(context: ContextTypes.DEFAULT_TYPE) -> asyncpg.Pool:
    """
    Récupérer pool PostgreSQL asyncpg depuis context.
    Pattern H1 fix Story 1.11 : pool asyncpg (pas psycopg2).
    """
    pool = context.bot_data.get("db_pool")
    if pool is None:
        raise RuntimeError("Database pool not initialized in bot_data")
    return pool


async def recovery_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Commande /recovery : Liste derniers événements recovery

    Usage:
        /recovery         - 10 derniers événements (résumé)
        /recovery -v      - Détails complets
        /recovery stats   - Statistiques (uptime, MTTR, recovery count)

    Story 1.13 - AC5: Consultation recovery events
    """
    pool = await _get_pool(context)

    # Parser arguments
    args = context.args or []
    verbose = parse_verbose_flag(args)
    show_stats = "stats" in args

    if show_stats:
        # Afficher statistiques
        async with pool.acquire() as conn:
            # Total recoveries
            total_recoveries = await conn.fetchval("SELECT COUNT(*) FROM core.recovery_events")

            # Successful recoveries
            successful_recoveries = await conn.fetchval(
                "SELECT COUNT(*) FROM core.recovery_events WHERE success = true"
            )

            # MTTR (Mean Time To Recovery)
            avg_duration = await conn.fetchval(
                "SELECT AVG(recovery_duration_seconds) FROM core.recovery_events "
                "WHERE recovery_duration_seconds IS NOT NULL"
            )

            # Last 30 days uptime (approximation)
            # Uptime ≈ 100% - (failed_recoveries / total_time)
            failed_last_30d = await conn.fetchval(
                "SELECT COUNT(*) FROM core.recovery_events "
                "WHERE success = false AND created_at > NOW() - INTERVAL '30 days'"
            )

            # Success rate
            success_rate = (
                (successful_recoveries / total_recoveries * 100) if total_recoveries > 0 else 100.0
            )

        # Format response
        response = "📊 **Recovery Statistics**\n\n"
        response += f"**Total recoveries**: {total_recoveries}\n"
        response += f"**Success rate**: {success_rate:.1f}%\n"
        response += f"**MTTR**: {avg_duration:.1f}s\n" if avg_duration else "**MTTR**: N/A\n"
        response += f"**Failed (30d)**: {failed_last_30d}\n"
        response += f"**Uptime estimate**: {100 - (failed_last_30d / 30 * 100 / 24):.2f}%\n"

        await send_message_with_split(update, response)
        return

    # Liste événements recovery
    async with pool.acquire() as conn:
        events = await conn.fetch(
            """
            SELECT
                event_type,
                services_affected,
                ram_before,
                ram_after,
                success,
                recovery_duration_seconds,
                notification_sent,
                created_at
            FROM core.recovery_events
            ORDER BY created_at DESC
            LIMIT 10
            """
        )

    if not events:
        await update.message.reply_text("✅ Aucun événement recovery enregistré.")
        return

    # Format response
    response = "🛡️ **Recovery Events** (10 derniers)\n\n"

    for event in events:
        icon = "✅" if event["success"] else "❌"
        event_type_label = {
            "auto_recovery_ram": "RAM Auto-Recovery",
            "crash_loop_detected": "Crash Loop",
            "os_reboot": "OS Reboot",
            "docker_restart": "Docker Restart",
        }.get(event["event_type"], event["event_type"])

        timestamp_str = format_timestamp(event["created_at"])

        response += f"{icon} **{event_type_label}**\n"
        response += f"   {timestamp_str}\n"

        if verbose:
            # Détails complets
            if event["services_affected"]:
                response += f"   Services: `{event['services_affected']}`\n"

            if event["ram_before"] and event["ram_after"]:
                response += f"   RAM: {event['ram_before']}% → {event['ram_after']}%\n"

            if event["recovery_duration_seconds"]:
                response += f"   Duration: {event['recovery_duration_seconds']}s\n"

            response += f"   Notification: {'✓' if event['notification_sent'] else '✗'}\n"

        response += "\n"

    # Footer
    if not verbose:
        response += "\n💡 Tip: `/recovery -v` pour détails complets\n"
        response += "💡 Tip: `/recovery stats` pour statistiques\n"

    await send_message_with_split(update, response)


# Export handlers
__all__ = ["recovery_command"]
