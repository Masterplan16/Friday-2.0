"""
Handler Telegram pour les commandes de backup.

Story 1.12 - Task 4.2
Commande: /backup [-v]
"""

import os
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from telegram import Update
from telegram.ext import ContextTypes

from .formatters import parse_verbose_flag, format_timestamp
from .messages import send_message_with_split


async def _get_pool(context: ContextTypes.DEFAULT_TYPE) -> asyncpg.Pool:
    """Lazy init pool asyncpg (pattern Story 1.11 H1 fix)."""
    pool = context.bot_data.get("db_pool")
    if pool is None:
        database_url = os.getenv("DATABASE_URL")
        pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
        context.bot_data["db_pool"] = pool
    return pool


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Affiche les derniers backups avec statut sync.

    Usage:
        /backup       → Derniers 5 backups (résumé)
        /backup -v    → Derniers 5 backups (détails complets)

    Permissions: OWNER_USER_ID uniquement (observabilité système).
    """
    # OWNER_USER_ID check (H5 fix Story 1.11)
    owner_id = int(os.getenv("OWNER_USER_ID", "0"))
    if owner_id != 0 and update.effective_user.id != owner_id:
        await update.message.reply_text("❌ Unauthorized: Commande réservée au Mainteneur")
        return

    # Parse verbose flag (pattern Story 1.11)
    verbose = parse_verbose_flag(context.args or [])

    # Get pool
    pool = await _get_pool(context)

    # Query derniers backups
    async with pool.acquire() as conn:
        backups = await conn.fetch("""
            SELECT
                backup_date,
                filename,
                size_bytes,
                synced_to_pc,
                pc_arrival_time,
                retention_policy,
                last_restore_test,
                restore_test_status
            FROM core.backup_metadata
            ORDER BY backup_date DESC
            LIMIT 5
        """)

    if not backups:
        await update.message.reply_text(
            "ℹ️ Aucun backup trouvé.\n\n"
            "Les backups seront créés automatiquement à 03h00 quotidiennement."
        )
        return

    # Build response
    response = "📦 **Derniers backups**\n\n"

    for i, b in enumerate(backups, 1):
        # Format timestamp
        backup_time = format_timestamp(b["backup_date"])

        # Size MB
        size_mb = b["size_bytes"] // (1024 * 1024)

        # Sync status icon
        sync_icon = "✅" if b["synced_to_pc"] else "❌"

        # Basic info (toujours affiché)
        response += f"**{i}. {backup_time}**\n"
        response += f"   📄 `{b['filename']}`\n"
        response += f"   📊 {size_mb} MB | Sync PC: {sync_icon}\n"

        # Verbose details (si -v flag)
        if verbose:
            response += f"   🔒 Chiffré: age (clé publique VPS)\n"
            response += f"   📅 Rétention: {b['retention_policy']}\n"

            if b["synced_to_pc"]:
                pc_time = format_timestamp(b["pc_arrival_time"]) if b["pc_arrival_time"] else "N/A"
                response += f"   🖥️  Arrivée PC: {pc_time}\n"

            if b["last_restore_test"]:
                test_time = format_timestamp(b["last_restore_test"])
                test_status_icon = "✅" if b["restore_test_status"] == "success" else "❌"
                response += f"   🧪 Dernier test restore: {test_time} {test_status_icon}\n"

        response += "\n"

    # Footer
    response += "─────────────────────\n"
    response += f"💾 Total: {len(backups)} backup(s) récent(s)\n"

    if not verbose:
        response += "\n💡 Astuce: `/backup -v` pour détails complets"

    # Send avec split si >4096 chars (pattern Story 1.11 M4 fix)
    await send_message_with_split(update, response)


# Export
__all__ = ["backup_command"]
