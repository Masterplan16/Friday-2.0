"""
Bot Telegram Friday 2.0 - Trust Commands Handlers

Story 1.8 - AC4, AC5, AC6 :
- /trust promote <module> <action> : Promotion manuelle propose→auto ou blocked→propose
- /trust set <module> <action> <level> : Override manuel (bypass conditions)
"""

import asyncpg
import os
from datetime import datetime, timedelta
from typing import Any
import yaml

import structlog
from telegram import Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)

# Configuration - Database et Redis URLs
# Note : DATABASE_URL doit être défini en production (pas de default password)
# Pour tests unitaires, les helpers sont mockés donc URL pas utilisée
_DB_URL = os.getenv("DATABASE_URL")  # None si non défini (sera vérifié au runtime)
_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


async def trust_command_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Router principal /trust - Dispatche vers sous-commandes.

    Usage:
    - /trust promote <module> <action>
    - /trust set <module> <action> <level>

    Args:
        update: Update Telegram
        context: Context bot
    """
    if not context.args or len(context.args) == 0:
        await update.message.reply_text(
            "❌ **Usage commande /trust**\n\n"
            "**Sous-commandes disponibles :**\n\n"
            "• `/trust promote <module> <action>`\n"
            "  → Promouvoir un trust level manuellement\n"
            "  → Conditions : accuracy + anti-oscillation\n\n"
            "• `/trust set <module> <action> <level>`\n"
            "  → Override manuel (bypass conditions)\n"
            "  → Reserved Antonio\n\n"
            "**Exemples :**\n"
            "• `/trust promote email classify`\n"
            "• `/trust set finance classify_transaction blocked`",
            parse_mode="Markdown"
        )
        return

    subcommand = context.args[0].lower()

    if subcommand == "promote":
        # Supprimer "promote" des args et passer le reste
        context.args = context.args[1:]
        await trust_promote_command(update, context)

    elif subcommand == "set":
        # Supprimer "set" des args et passer le reste
        context.args = context.args[1:]
        await trust_set_command(update, context)

    else:
        await update.message.reply_text(
            f"❌ **Sous-commande inconnue** : `{subcommand}`\n\n"
            f"Sous-commandes valides : `promote`, `set`\n\n"
            f"Tapez `/trust` pour voir l'aide.",
            parse_mode="Markdown"
        )


# ────────────────────────────────────────────────────────────
# Sous-commandes
# ────────────────────────────────────────────────────────────


async def trust_promote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler /trust promote <module> <action> - Promotion manuelle trust level (AC4, AC5).

    Conditions :
    - propose → auto : accuracy ≥95% sur 2 semaines + sample ≥20
    - blocked → propose : accuracy ≥90% sur 4 semaines + sample ≥10
    - Anti-oscillation : 14 jours min depuis dernière rétrogradation

    Args:
        update: Update Telegram
        context: Context bot
    """
    user_id = update.effective_user.id if update.effective_user else None
    logger.info("/trust promote command received", user_id=user_id, args=context.args)

    # Vérifier arguments
    if not context.args or len(context.args) != 2:
        await update.message.reply_text(
            "❌ Usage : `/trust promote <module> <action>`\n"
            "Exemple : `/trust promote email classify`",
            parse_mode="Markdown"
        )
        return

    module = context.args[0]
    action = context.args[1]

    try:
        # Charger trust level actuel
        current_level = await _get_current_trust_level(module, action)

        if current_level == "auto":
            await update.message.reply_text(
                f"ℹ️ Module `{module}.{action}` est déjà au niveau **auto** (maximum).",
                parse_mode="Markdown"
            )
            return

        # Vérifier anti-oscillation
        last_change = await _get_last_trust_change(module, action)
        if last_change:
            days_since_change = (datetime.utcnow() - last_change).days
            if days_since_change < 14:
                await update.message.reply_text(
                    f"❌ **Promotion refusée** : Anti-oscillation\n\n"
                    f"Dernière transition : {last_change.strftime('%Y-%m-%d')}\n"
                    f"Jours écoulés : {days_since_change}/14 minimum\n\n"
                    f"Attendre encore {14 - days_since_change} jour(s).",
                    parse_mode="Markdown"
                )
                return

        # Vérifier conditions selon transition
        if current_level == "propose":
            # propose → auto : accuracy ≥95% sur 2 semaines + sample ≥20
            metrics = await _get_metrics(module, action, weeks=2)
            avg_accuracy = sum(m["accuracy"] for m in metrics) / len(metrics) if metrics else 0.0
            total_actions = sum(m["total_actions"] for m in metrics) if metrics else 0

            if total_actions < 20:
                await update.message.reply_text(
                    f"❌ **Promotion refusée** : Échantillon insuffisant\n\n"
                    f"Actions sur 2 semaines : {total_actions}/20 minimum",
                    parse_mode="Markdown"
                )
                return

            if avg_accuracy < 0.95:
                await update.message.reply_text(
                    f"❌ **Promotion refusée** : Accuracy insuffisante\n\n"
                    f"Accuracy sur 2 semaines : {avg_accuracy:.1%}\n"
                    f"Seuil requis : 95%",
                    parse_mode="Markdown"
                )
                return

            # Conditions OK → promote à auto
            await _apply_trust_level_change(module, action, "auto", "promotion")
            await update.message.reply_text(
                f"✅ **Promotion réussie**\n\n"
                f"Module : `{module}.{action}`\n"
                f"Transition : **propose** → **auto**\n"
                f"Accuracy : {avg_accuracy:.1%} (sur 2 semaines)\n"
                f"Actions : {total_actions}",
                parse_mode="Markdown"
            )

        elif current_level == "blocked":
            # blocked → propose : accuracy ≥90% sur 4 semaines + sample ≥10
            metrics = await _get_metrics(module, action, weeks=4)
            avg_accuracy = sum(m["accuracy"] for m in metrics) / len(metrics) if metrics else 0.0
            total_actions = sum(m["total_actions"] for m in metrics) if metrics else 0

            if total_actions < 10:
                await update.message.reply_text(
                    f"❌ **Promotion refusée** : Échantillon insuffisant\n\n"
                    f"Actions sur 4 semaines : {total_actions}/10 minimum",
                    parse_mode="Markdown"
                )
                return

            if avg_accuracy < 0.90:
                await update.message.reply_text(
                    f"❌ **Promotion refusée** : Accuracy insuffisante\n\n"
                    f"Accuracy sur 4 semaines : {avg_accuracy:.1%}\n"
                    f"Seuil requis : 90%",
                    parse_mode="Markdown"
                )
                return

            # Conditions OK → promote à propose
            await _apply_trust_level_change(module, action, "propose", "promotion")
            await update.message.reply_text(
                f"✅ **Promotion réussie**\n\n"
                f"Module : `{module}.{action}`\n"
                f"Transition : **blocked** → **propose**\n"
                f"Accuracy : {avg_accuracy:.1%} (sur 4 semaines)\n"
                f"Actions : {total_actions}",
                parse_mode="Markdown"
            )

        logger.info(
            "Trust level promoted",
            module=module,
            action=action,
            old_level=current_level,
            new_level="auto" if current_level == "propose" else "propose"
        )

    except Exception as e:
        logger.error("Trust promote command failed", error=str(e), exc_info=True)
        await update.message.reply_text(
            f"❌ **Erreur** : {str(e)}\n\n"
            f"Vérifiez que le module/action existe.",
            parse_mode="Markdown"
        )


async def trust_set_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler /trust set <module> <action> <level> - Override manuel trust level (AC6).

    Bypass toutes conditions (anti-oscillation, accuracy) - Reserved Antonio.

    Args:
        update: Update Telegram
        context: Context bot
    """
    user_id = update.effective_user.id if update.effective_user else None
    logger.info("/trust set command received", user_id=user_id, args=context.args)

    # Vérifier arguments
    if not context.args or len(context.args) != 3:
        await update.message.reply_text(
            "❌ Usage : `/trust set <module> <action> <level>`\n"
            "Niveaux valides : `auto`, `propose`, `blocked`\n\n"
            "Exemple : `/trust set email classify blocked`",
            parse_mode="Markdown"
        )
        return

    module = context.args[0]
    action = context.args[1]
    new_level = context.args[2]

    # Valider level
    if new_level not in ["auto", "propose", "blocked"]:
        await update.message.reply_text(
            f"❌ **Niveau invalide** : `{new_level}`\n\n"
            f"Valeurs acceptées : `auto`, `propose`, `blocked`",
            parse_mode="Markdown"
        )
        return

    try:
        # Charger trust level actuel
        old_level = await _get_current_trust_level(module, action)

        if old_level == new_level:
            await update.message.reply_text(
                f"ℹ️ Module `{module}.{action}` est déjà au niveau **{new_level}**.",
                parse_mode="Markdown"
            )
            return

        # Appliquer override (bypass conditions)
        await _apply_trust_level_change(module, action, new_level, "manual_override")

        # Log WARNING pour override manuel
        logger.warning(
            "Manual trust override by Antonio",
            module=module,
            action=action,
            old_level=old_level,
            new_level=new_level
        )

        await update.message.reply_text(
            f"⚙️ **Override manuel appliqué**\n\n"
            f"Module : `{module}.{action}`\n"
            f"Transition : **{old_level}** → **{new_level}**\n\n"
            f"⚠️ Bypass des conditions (anti-oscillation, accuracy)",
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error("Trust set command failed", error=str(e), exc_info=True)
        await update.message.reply_text(
            f"❌ **Erreur** : {str(e)}",
            parse_mode="Markdown"
        )


# ────────────────────────────────────────────────────────────
# Helpers internes
# ────────────────────────────────────────────────────────────


async def _get_current_trust_level(module: str, action: str) -> str:
    """
    Récupère trust level actuel depuis config/trust_levels.yaml.

    Args:
        module: Nom du module
        action: Nom de l'action

    Returns:
        Trust level actuel ("auto", "propose", "blocked")

    Raises:
        ValueError: Si module/action introuvable
    """
    config_path = "config/trust_levels.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    modules = config.get("modules", {})
    if module not in modules or action not in modules[module]:
        raise ValueError(f"Module/action introuvable : {module}.{action}")

    return modules[module][action]


async def _get_last_trust_change(module: str, action: str) -> datetime | None:
    """
    Récupère timestamp dernière transition trust level depuis BDD.

    Args:
        module: Nom du module
        action: Nom de l'action

    Returns:
        Timestamp dernière transition, ou None si jamais changé

    Raises:
        ValueError: Si DATABASE_URL non défini
    """
    if not _DB_URL:
        raise ValueError("DATABASE_URL environment variable required")

    conn = await asyncpg.connect(_DB_URL)

    try:
        query = """
            SELECT last_trust_change_at
            FROM core.trust_metrics
            WHERE module = $1 AND action_type = $2
            ORDER BY week_start DESC
            LIMIT 1
        """
        row = await conn.fetchrow(query, module, action)
        return row["last_trust_change_at"] if row else None

    finally:
        await conn.close()


async def _get_metrics(module: str, action: str, weeks: int) -> list[dict[str, Any]]:
    """
    Récupère metrics des N dernières semaines pour module/action.

    Args:
        module: Nom du module
        action: Nom de l'action
        weeks: Nombre de semaines à récupérer

    Returns:
        Liste de metrics (accuracy, total_actions)

    Raises:
        ValueError: Si DATABASE_URL non défini
    """
    if not _DB_URL:
        raise ValueError("DATABASE_URL environment variable required")

    conn = await asyncpg.connect(_DB_URL)

    try:
        cutoff_date = datetime.utcnow() - timedelta(weeks=weeks)

        query = """
            SELECT accuracy, total_actions
            FROM core.trust_metrics
            WHERE module = $1 AND action_type = $2
              AND week_start >= $3
            ORDER BY week_start DESC
        """
        rows = await conn.fetch(query, module, action, cutoff_date)
        return [dict(row) for row in rows]

    finally:
        await conn.close()


async def _apply_trust_level_change(module: str, action: str, new_level: str, reason: str) -> None:
    """
    Applique changement trust level : YAML + BDD + événement Redis.

    Args:
        module: Nom du module
        action: Nom de l'action
        new_level: Nouveau trust level
        reason: Raison du changement ("promotion" ou "manual_override")

    Raises:
        ValueError: Si DATABASE_URL non défini
    """
    if not _DB_URL:
        raise ValueError("DATABASE_URL environment variable required")

    # 1. Modifier YAML
    config_path = "config/trust_levels.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if "modules" not in config:
        config["modules"] = {}
    if module not in config["modules"]:
        config["modules"][module] = {}

    config["modules"][module][action] = new_level

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)

    # 2. Mettre à jour timestamp BDD
    conn = await asyncpg.connect(_DB_URL)

    try:
        timestamp = datetime.utcnow()
        query = """
            UPDATE core.trust_metrics
            SET last_trust_change_at = $1
            WHERE module = $2 AND action_type = $3
        """
        await conn.execute(query, timestamp, module, action)

    finally:
        await conn.close()

    # 3. Envoyer événement Redis Streams
    import redis.asyncio as aioredis

    # Utiliser async with pour garantir fermeture connexion
    async with aioredis.from_url(_REDIS_URL, decode_responses=True) as redis_client:
        event_data = {
            "module": module,
            "action": action,
            "new_level": new_level,
            "reason": reason,
            "timestamp": timestamp.isoformat(),
        }
        await redis_client.xadd("friday:events:trust.level.changed", event_data)
