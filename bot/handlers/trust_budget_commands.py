"""
Bot Telegram Friday 2.0 - Trust & Budget Commands

Story 1.11: Commandes /confiance, /receipt, /journal, /status, /budget, /stats
pour consultation metriques trust, audit actions et controle couts API.
"""

import calendar
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import redis.asyncio as aioredis
import structlog
import yaml
from bot.handlers.formatters import (
    format_confidence,
    format_eur,
    format_status_emoji,
    format_timestamp,
    parse_verbose_flag,
    truncate_text,
)
from bot.handlers.messages import send_message_with_split
from telegram import Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)

# Configuration
_OWNER_USER_ID = int(os.getenv("OWNER_USER_ID") or "0")

# Tarification Claude Sonnet 4.5 (D17)
_USD_INPUT_PER_1M = 3.0
_USD_OUTPUT_PER_1M = 15.0
_USD_EUR_RATE = float(os.getenv("USD_EUR_RATE", "0.92"))
_MONTHLY_BUDGET_EUR = 45.0

# Connection pool (lazy init)
_pool: asyncpg.Pool | None = None

# Trust levels cache
_trust_levels_cache: dict[str, dict[str, str]] | None = None
_trust_levels_cache_ts: float = 0.0
_TRUST_LEVELS_CACHE_TTL = 300.0  # 5 minutes

# Error messages (L2 fix: consistent)
_ERR_UNAUTHORIZED = "Non autorise. Commande reservee au Mainteneur."
_ERR_DB = "Erreur DB. Reessayez ou verifiez /status."


async def _get_pool() -> asyncpg.Pool:
    """Retourne le pool asyncpg (lazy init, H1 fix).

    Returns:
        Pool asyncpg

    Raises:
        ValueError: Si DATABASE_URL non defini
    """
    global _pool
    if _pool is not None:
        return _pool
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL non defini")
    _pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3, command_timeout=10.0)
    return _pool


def _check_owner(user_id: int | None) -> bool:
    """Verifie que l'utilisateur est le Mainteneur (H5 fix).

    Args:
        user_id: ID Telegram de l'utilisateur

    Returns:
        True si autorise (ou si OWNER_USER_ID non configure)
    """
    if not _OWNER_USER_ID:
        return True
    return user_id == _OWNER_USER_ID


def _load_trust_levels_config() -> dict[str, dict[str, str]]:
    """Charge trust levels depuis config/trust_levels.yaml avec cache TTL (M5+H3 fix).

    Returns:
        Dict {module: {action: trust_level}}
    """
    global _trust_levels_cache, _trust_levels_cache_ts

    now = time.monotonic()
    if _trust_levels_cache is not None and (now - _trust_levels_cache_ts) < _TRUST_LEVELS_CACHE_TTL:
        return _trust_levels_cache

    config_path = Path(__file__).resolve().parents[2] / "config" / "trust_levels.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        _trust_levels_cache = config.get("modules", {})
        _trust_levels_cache_ts = now
        return _trust_levels_cache
    except FileNotFoundError:
        logger.error("Trust levels config not found", path=str(config_path))
        return {}


def _get_ram_usage() -> str | None:
    """Lit l'usage RAM depuis /proc/meminfo (C3 fix: AC4 exige RAM %).

    Returns:
        String formatee "XX.X% (YY.Y/ZZ.Z Go)" ou None si indisponible
    """
    try:
        with open("/proc/meminfo", "r") as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(":")] = int(parts[1])

        total_kb = meminfo.get("MemTotal", 0)
        available_kb = meminfo.get("MemAvailable", 0)
        if total_kb == 0:
            return None

        used_kb = total_kb - available_kb
        used_gb = used_kb / (1024 * 1024)
        total_gb = total_kb / (1024 * 1024)
        pct = (used_kb / total_kb) * 100

        return f"{pct:.1f}% ({used_gb:.1f}/{total_gb:.1f} Go)"
    except (FileNotFoundError, OSError):
        return None


# ────────────────────────────────────────────────────────────
# /confiance (AC1)
# ────────────────────────────────────────────────────────────


async def confiance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /confiance - Tableau accuracy par module/action (AC1).

    Affiche accuracy sur 4 dernieres semaines, trend, trust level actuel.
    Flag -v pour detail semaine par semaine.
    """
    user_id = update.effective_user.id if update.effective_user else None
    if not _check_owner(user_id):
        await update.message.reply_text(_ERR_UNAUTHORIZED)
        return

    verbose = parse_verbose_flag(context.args)
    logger.info("/confiance command received", user_id=user_id, verbose=verbose)

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT module, action_type, week_start, total_actions,
                       corrected_actions, accuracy, current_trust_level,
                       trust_changed
                FROM core.trust_metrics
                WHERE week_start >= (CURRENT_DATE - INTERVAL '28 days')
                ORDER BY module, action_type, week_start DESC
                """)

        if not rows:
            await update.message.reply_text(
                "Pas encore de donnees (nightly.py n'a pas encore execute)",
                parse_mode="Markdown",
            )
            return

        trust_levels = _load_trust_levels_config()

        # Grouper par module.action
        grouped: dict[str, list] = {}
        for row in rows:
            key = f"{row['module']}.{row['action_type']}"
            grouped.setdefault(key, []).append(row)

        lines = ["**Accuracy par module/action** (4 semaines)\n"]

        for key, weeks in grouped.items():
            module, action = key.split(".", 1)
            latest = weeks[0]
            trust_level = trust_levels.get(module, {}).get(action, latest["current_trust_level"])

            # Trend: comparer semaine N vs N-1
            trend = ""
            if len(weeks) >= 2:
                diff = latest["accuracy"] - weeks[1]["accuracy"]
                if diff > 0.01:
                    trend = " \u2191"
                elif diff < -0.01:
                    trend = " \u2193"
                else:
                    trend = " \u2192"

            retro_tag = ""
            if latest.get("trust_changed"):
                retro_tag = " \u26a0\ufe0f RETRO"

            lines.append(
                f"\u2022 `{key}` : {format_confidence(latest['accuracy'])}{trend} "
                f"(n={latest['total_actions']}) [{trust_level}]{retro_tag}"
            )

            if verbose:
                for week in weeks:
                    ws = week["week_start"]
                    week_label = ws.strftime("%d/%m") if hasattr(ws, "strftime") else str(ws)
                    lines.append(
                        f"  {week_label}: {format_confidence(week['accuracy'])} "
                        f"(n={week['total_actions']}, corr={week['corrected_actions']})"
                    )

        text = "\n".join(lines)
        await send_message_with_split(update, text, parse_mode="Markdown")

    except ValueError as e:
        await update.message.reply_text(f"Configuration erreur: {e}", parse_mode="Markdown")
    except Exception as e:
        logger.error("/confiance command failed", error=str(e), exc_info=True)
        await update.message.reply_text(_ERR_DB, parse_mode="Markdown")


# ────────────────────────────────────────────────────────────
# /receipt (AC2)
# ────────────────────────────────────────────────────────────


async def receipt_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /receipt [id] - Detail complet d'un recu (AC2).

    UUID complet ou prefix (>=8 chars). Flag -v pour payload + steps.
    """
    user_id = update.effective_user.id if update.effective_user else None
    if not _check_owner(user_id):
        await update.message.reply_text(_ERR_UNAUTHORIZED)
        return

    verbose = parse_verbose_flag(context.args)
    logger.info("/receipt command received", user_id=user_id, verbose=verbose)

    # Extraire UUID (filtrer flags -v)
    args = [a for a in (context.args or []) if not a.startswith("-")]
    if not args:
        await update.message.reply_text(
            "Usage: `/receipt <uuid>` (`-v` pour details)\n" "Exemple: `/receipt a1b2c3d4`",
            parse_mode="Markdown",
        )
        return

    receipt_id = args[0]

    # Valider format UUID (au moins 8 chars hex)
    clean_id = receipt_id.replace("-", "")
    if len(clean_id) < 8 or not all(c in "0123456789abcdef" for c in clean_id.lower()):
        await update.message.reply_text(
            f"UUID invalide: `{receipt_id}`\n"
            f"Format attendu: UUID complet ou prefix >= 8 caracteres hex",
            parse_mode="Markdown",
        )
        return

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            # Essayer UUID exact d'abord
            row = None
            is_full_uuid = len(clean_id) == 32 or len(receipt_id) == 36
            if is_full_uuid:
                row = await conn.fetchrow(
                    """
                    SELECT id, module, action_type, trust_level, status,
                           input_summary, output_summary, confidence, reasoning,
                           payload, correction, feedback_comment,
                           created_at, updated_at, validated_by, duration_ms
                    FROM core.action_receipts WHERE id = $1
                    """,
                    receipt_id,
                )

            # Sinon recherche par prefix
            if not row:
                rows = await conn.fetch(
                    """
                    SELECT id, module, action_type, trust_level, status,
                           input_summary, output_summary, confidence, reasoning,
                           payload, correction, feedback_comment,
                           created_at, updated_at, validated_by, duration_ms
                    FROM core.action_receipts
                    WHERE id::text LIKE $1 || '%'
                    ORDER BY created_at DESC LIMIT 5
                    """,
                    receipt_id,
                )

                if not rows:
                    await update.message.reply_text(
                        f"Receipt introuvable pour `{receipt_id}`",
                        parse_mode="Markdown",
                    )
                    return

                if len(rows) > 1:
                    lines = [f"Plusieurs receipts pour prefix `{receipt_id}`:\n"]
                    for r in rows:
                        rid = str(r["id"])[:8]
                        lines.append(
                            f"\u2022 `{rid}...` {r['module']}.{r['action_type']} "
                            f"{format_status_emoji(r['status'])} "
                            f"{format_timestamp(r['created_at'])}"
                        )
                    lines.append("\nPrecisez avec `/receipt <uuid_complet>`")
                    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
                    return

                row = rows[0]

        # Formater receipt
        rid = str(row["id"])
        lines = [
            f"**Receipt** `{rid[:8]}...`\n",
            f"Module: `{row['module']}.{row['action_type']}`",
            f"Trust: {row['trust_level']}",
            f"Status: {format_status_emoji(row['status'])} {row['status']}",
            f"Confidence: {format_confidence(row['confidence'])}",
            f"Input: {truncate_text(row['input_summary'] or '', 200)}",
            f"Output: {truncate_text(row['output_summary'] or '', 200)}",
            f"Reasoning: {truncate_text(row['reasoning'] or '', 200)}",
            f"Created: {format_timestamp(row['created_at'], verbose=True)}",
        ]

        if row.get("correction"):
            lines.append(f"Correction: {row['correction']}")

        # Story 2.6 AC4: Section spéciale pour emails envoyés (lisibilité améliorée)
        if row["module"] == "email" and row["action_type"] == "draft_reply" and row.get("payload"):
            payload = row["payload"]
            lines.append("\n**Email Details**")
            if payload.get("account_id"):
                lines.append(f"Compte IMAP: `{payload['account_id']}`")
            if payload.get("email_type"):
                lines.append(f"Type: {payload['email_type']}")
            if payload.get("message_id"):
                lines.append(f"Message ID: `{payload['message_id'][:50]}...`")
            if payload.get("draft_body"):
                draft_preview = truncate_text(payload["draft_body"], 300)
                lines.append(f"\nBrouillon (extrait):\n---\n{draft_preview}\n---")

        if verbose:
            lines.append("\n**Details** (`-v`)")
            if row.get("duration_ms"):
                lines.append(f"Duration: {row['duration_ms']}ms")
            if row.get("validated_by"):
                lines.append(f"Validated by: user {row['validated_by']}")
            if row.get("validated_at"):
                lines.append(f"Validated at: {format_timestamp(row['validated_at'], verbose=True)}")
            if row.get("executed_at"):
                lines.append(f"Executed at: {format_timestamp(row['executed_at'], verbose=True)}")
            if row.get("payload"):
                payload_str = json.dumps(row["payload"], indent=2, ensure_ascii=False)
                if len(payload_str) > 1500:
                    payload_str = payload_str[:1500] + "\n..."
                lines.append(f"Payload (JSON complet):\n```json\n{payload_str}\n```")
            if row.get("feedback_comment"):
                lines.append(f"Feedback: {row['feedback_comment']}")
            lines.append(f"Updated: {format_timestamp(row['updated_at'], verbose=True)}")

        text = "\n".join(lines)
        await send_message_with_split(update, text, parse_mode="Markdown")

    except ValueError as e:
        await update.message.reply_text(f"Configuration erreur: {e}", parse_mode="Markdown")
    except Exception as e:
        logger.error("/receipt command failed", error=str(e), exc_info=True)
        await update.message.reply_text(_ERR_DB, parse_mode="Markdown")


# ────────────────────────────────────────────────────────────
# /journal (AC3)
# ────────────────────────────────────────────────────────────


async def journal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /journal - 20 dernieres actions (AC3 Story 1.11 + AC4 Story 2.6).

    Affiche chronologiquement les actions avec status emoji et confidence.
    Flag -v pour afficher input_summary par entree.

    Story 2.6 AC4:
        - Format spécialisé pour emails envoyés (affiche recipient_anon)
        - Filtrage optionnel par module: /journal email
    """
    user_id = update.effective_user.id if update.effective_user else None
    if not _check_owner(user_id):
        await update.message.reply_text(_ERR_UNAUTHORIZED)
        return

    verbose = parse_verbose_flag(context.args)

    # Story 2.6 AC4: Support filtrage module (/journal email)
    filter_module = None
    if context.args:
        for arg in context.args:
            if arg != "-v":
                filter_module = arg
                break

    logger.info(
        "/journal command received", user_id=user_id, verbose=verbose, filter_module=filter_module
    )

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            if filter_module:
                rows = await conn.fetch(
                    """
                    SELECT id, module, action_type, status, confidence,
                           input_summary, output_summary, created_at
                    FROM core.action_receipts
                    WHERE module = $1
                    ORDER BY created_at DESC LIMIT 20
                    """,
                    filter_module,
                )
            else:
                rows = await conn.fetch("""
                    SELECT id, module, action_type, status, confidence,
                           input_summary, output_summary, created_at
                    FROM core.action_receipts
                    ORDER BY created_at DESC LIMIT 20
                    """)

        if not rows:
            await update.message.reply_text("Aucune action enregistree", parse_mode="Markdown")
            return

        filter_label = f" (filtre: {filter_module})" if filter_module else ""
        lines = [f"**Journal** (20 dernieres actions{filter_label})\n"]

        for row in rows:
            ts = format_timestamp(row["created_at"])
            emoji = format_status_emoji(row["status"])
            conf = format_confidence(row["confidence"])

            # Story 2.6 AC4: Format spécialisé pour emails envoyés
            if row["module"] == "email" and row["action_type"] == "draft_reply":
                # Extraire recipient_anon depuis output_summary
                output_summary = row.get("output_summary", "")
                # Format: "Email envoyé → [RECIPIENT_ANON]" ou similaire
                lines.append(f"`{ts}` {emoji} Email envoyé → {output_summary} {conf}")
            else:
                # Format générique pour autres actions
                lines.append(f"`{ts}` {row['module']}.{row['action_type']} " f"{emoji} {conf}")

            if verbose and row.get("input_summary"):
                lines.append(f"  Input: {truncate_text(row['input_summary'], 150)}")

        text = "\n".join(lines)
        await send_message_with_split(update, text, parse_mode="Markdown")

    except ValueError as e:
        await update.message.reply_text(f"Configuration erreur: {e}", parse_mode="Markdown")
    except Exception as e:
        logger.error("/journal command failed", error=str(e), exc_info=True)
        await update.message.reply_text(_ERR_DB, parse_mode="Markdown")


# ────────────────────────────────────────────────────────────
# /status (AC4)
# ────────────────────────────────────────────────────────────


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /status - Dashboard temps reel (AC4).

    Affiche health checks, RAM %, actions du jour, pending count.
    Flag -v pour detail repartition par status.
    """
    user_id = update.effective_user.id if update.effective_user else None
    if not _check_owner(user_id):
        await update.message.reply_text(_ERR_UNAUTHORIZED)
        return

    verbose = parse_verbose_flag(context.args)
    logger.info("/status command received", user_id=user_id, verbose=verbose)

    lines = ["**Dashboard Friday 2.0**\n"]

    # Health checks
    lines.append("**Services:**")

    # PostgreSQL check + actions (M1 fix: single connection)
    db_ok = False
    today_rows = []
    pending_row = None

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
            db_ok = True
            lines.append("\u2705 PostgreSQL: OK")

            today_rows = await conn.fetch("""
                SELECT status, COUNT(*) as cnt
                FROM core.action_receipts
                WHERE created_at >= CURRENT_DATE
                GROUP BY status
                """)

            pending_row = await conn.fetchrow("""
                SELECT COUNT(*) as pending_count,
                       MIN(created_at) as oldest_pending
                FROM core.action_receipts WHERE status = 'pending'
                """)
    except ValueError as e:
        lines.append(f"\u274c PostgreSQL: {e}")
    except Exception as e:
        lines.append(f"\u274c PostgreSQL: {type(e).__name__}")

    # Redis check
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        pong = await redis_client.ping()
        await redis_client.close()
        if pong:
            lines.append("\u2705 Redis: OK")
        else:
            lines.append("\u274c Redis: No PONG")
    except Exception as e:
        lines.append(f"\u274c Redis: {type(e).__name__}")

    # RAM usage (C3 fix: AC4 exige RAM %)
    ram_info = _get_ram_usage()
    if ram_info:
        lines.append(f"RAM: {ram_info}")
    else:
        lines.append("RAM: N/A (Linux only)")

    # Bot uptime
    start_time = context.bot_data.get("start_time") if context.bot_data else None
    if start_time:
        uptime_sec = time.time() - start_time
        hours = int(uptime_sec // 3600)
        minutes = int((uptime_sec % 3600) // 60)
        lines.append(f"\u2705 Bot uptime: {hours}h{minutes:02d}m")
    else:
        lines.append("\u2705 Bot: Running")

    # Actions du jour + pending
    if db_ok:
        total_today = sum(r["cnt"] for r in today_rows)
        lines.append(f"\n**Actions aujourd'hui:** {total_today}")

        if verbose and today_rows:
            status_breakdown = ", ".join(f"{r['status']}={r['cnt']}" for r in today_rows)
            lines.append(f"  {status_breakdown}")

        pending_count = pending_row["pending_count"] if pending_row else 0
        if pending_count > 0:
            oldest = pending_row["oldest_pending"]
            oldest_str = format_timestamp(oldest) if oldest else "?"
            lines.append(f"\n\u23f3 **Pending:** {pending_count} " f"(plus ancien: {oldest_str})")
        else:
            lines.append("\n\u2705 Aucune action pending")
    else:
        lines.append("\nActions: indisponible (DB down)")

    text = "\n".join(lines)
    await send_message_with_split(update, text, parse_mode="Markdown")


# ────────────────────────────────────────────────────────────
# /budget (AC5)
# ────────────────────────────────────────────────────────────


async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /budget - Consommation API Claude du mois (AC5).

    Affiche tokens utilises, cout EUR, projection fin de mois.
    Flag -v pour detail par module.
    """
    user_id = update.effective_user.id if update.effective_user else None
    if not _check_owner(user_id):
        await update.message.reply_text(_ERR_UNAUTHORIZED)
        return

    verbose = parse_verbose_flag(context.args)
    logger.info("/budget command received", user_id=user_id, verbose=verbose)

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    module,
                    COUNT(*) as action_count,
                    COALESCE(SUM((payload->>'llm_tokens_input')::int), 0) as tokens_in,
                    COALESCE(SUM((payload->>'llm_tokens_output')::int), 0) as tokens_out
                FROM core.action_receipts
                WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE)
                  AND payload ? 'llm_tokens_input'
                GROUP BY module ORDER BY tokens_in + tokens_out DESC
                """)

        # Verifier si tracking tokens actif
        total_tokens_in = sum(r["tokens_in"] for r in rows) if rows else 0
        total_tokens_out = sum(r["tokens_out"] for r in rows) if rows else 0

        if total_tokens_in == 0 and total_tokens_out == 0:
            await update.message.reply_text(
                "**Budget API Claude**\n\n"
                "Tracking tokens non encore actif.\n"
                "Les tokens seront suivis quand le LLM adapter "
                "injectera `llm_tokens_input`/`llm_tokens_output` dans le payload.\n\n"
                f"Budget mensuel: {format_eur(_MONTHLY_BUDGET_EUR)}",
                parse_mode="Markdown",
            )
            return

        # Calculer cout en USD puis EUR
        cost_usd = (
            total_tokens_in * _USD_INPUT_PER_1M / 1_000_000
            + total_tokens_out * _USD_OUTPUT_PER_1M / 1_000_000
        )
        cost_eur = cost_usd * _USD_EUR_RATE
        pct_budget = (cost_eur / _MONTHLY_BUDGET_EUR * 100) if _MONTHLY_BUDGET_EUR > 0 else 0

        # Projection fin de mois
        now = datetime.now(tz=timezone.utc)
        day_of_month = now.day
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        daily_rate = cost_eur / day_of_month if day_of_month > 0 else 0.0
        projected_eur = daily_rate * days_in_month

        lines = [
            "**Budget API Claude** (mois en cours)\n",
            f"Tokens input: {total_tokens_in:,}",
            f"Tokens output: {total_tokens_out:,}",
            f"Cout: {format_eur(cost_eur)} / {format_eur(_MONTHLY_BUDGET_EUR)}",
            f"Consomme: {pct_budget:.1f}%",
            f"Projection fin de mois: {format_eur(projected_eur)}",
        ]

        # Alerte si >80% budget
        if pct_budget > 80:
            lines.append(
                f"\n\u26a0\ufe0f **ALERTE**: Budget consomme a {pct_budget:.1f}% " f"(seuil 80%)"
            )

        # Detail par module (M4 fix: verbose only)
        if verbose and rows:
            lines.append("\n**Par module:**")
            for row in rows:
                mod_cost_usd = (
                    row["tokens_in"] * _USD_INPUT_PER_1M / 1_000_000
                    + row["tokens_out"] * _USD_OUTPUT_PER_1M / 1_000_000
                )
                mod_cost_eur = mod_cost_usd * _USD_EUR_RATE
                lines.append(
                    f"\u2022 {row['module']}: {format_eur(mod_cost_eur)} "
                    f"({row['action_count']} actions)"
                )

        text = "\n".join(lines)
        await send_message_with_split(update, text, parse_mode="Markdown")

    except ValueError as e:
        await update.message.reply_text(f"Configuration erreur: {e}", parse_mode="Markdown")
    except Exception as e:
        logger.error("/budget command failed", error=str(e), exc_info=True)
        await update.message.reply_text(_ERR_DB, parse_mode="Markdown")


# ────────────────────────────────────────────────────────────
# /stats (AC6)
# ────────────────────────────────────────────────────────────


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /stats - Metriques globales agregees (AC6).

    Affiche totaux 24h/7j/30j, success rate, top 5 modules.
    Flag -v pour repartition status detaillee.
    """
    user_id = update.effective_user.id if update.effective_user else None
    if not _check_owner(user_id):
        await update.message.reply_text(_ERR_UNAUTHORIZED)
        return

    verbose = parse_verbose_flag(context.args)
    logger.info("/stats command received", user_id=user_id, verbose=verbose)

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            stats_24h = await conn.fetchrow("""
                SELECT COUNT(*) as total,
                       ROUND(AVG(confidence)::numeric, 3) as avg_confidence
                FROM core.action_receipts
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                """)

            stats_7d = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (
                        WHERE status IN ('auto', 'approved', 'executed')
                    ) as success_cnt,
                    COUNT(*) FILTER (WHERE status = 'error') as error_cnt,
                    ROUND(AVG(confidence)::numeric, 3) as avg_confidence
                FROM core.action_receipts
                WHERE created_at >= NOW() - INTERVAL '7 days'
                """)

            stats_30d = await conn.fetchrow("""
                SELECT COUNT(*) as total
                FROM core.action_receipts
                WHERE created_at >= NOW() - INTERVAL '30 days'
                """)

            # Top 5 modules (7 jours)
            top_modules = await conn.fetch("""
                SELECT module, COUNT(*) as cnt
                FROM core.action_receipts
                WHERE created_at >= NOW() - INTERVAL '7 days'
                GROUP BY module ORDER BY cnt DESC LIMIT 5
                """)

            # Repartition status (7 jours)
            status_breakdown = await conn.fetch("""
                SELECT status, COUNT(*) as cnt
                FROM core.action_receipts
                WHERE created_at >= NOW() - INTERVAL '7 days'
                GROUP BY status ORDER BY cnt DESC
                """)

        total_24h = stats_24h["total"] if stats_24h else 0
        total_7d = stats_7d["total"] if stats_7d else 0
        total_30d = stats_30d["total"] if stats_30d else 0

        if total_7d == 0 and total_24h == 0 and total_30d == 0:
            await update.message.reply_text(
                "Aucune action enregistree sur les 30 derniers jours.",
                parse_mode="Markdown",
            )
            return

        # Success rate
        success_cnt = stats_7d["success_cnt"] if stats_7d else 0
        success_rate = (success_cnt / total_7d * 100) if total_7d > 0 else 0

        lines = [
            "**Statistiques Friday 2.0**\n",
            f"Actions 24h: {total_24h}",
            f"Actions 7j: {total_7d}",
            f"Actions 30j: {total_30d}",
            f"Success rate (7j): {success_rate:.1f}%",
        ]

        # Avg confidence
        avg_conf = stats_7d["avg_confidence"] if stats_7d and stats_7d["avg_confidence"] else None
        if avg_conf is not None:
            lines.append(f"Avg confidence (7j): {format_confidence(float(avg_conf))}")

        # Repartition status (M4 fix: verbose only)
        if verbose and status_breakdown:
            lines.append("\n**Status (7j):**")
            for row in status_breakdown:
                lines.append(
                    f"  {format_status_emoji(row['status'])} {row['status']}: {row['cnt']}"
                )

        # Top modules
        if top_modules:
            lines.append("\n**Top modules (7j):**")
            for i, row in enumerate(top_modules, 1):
                lines.append(f"  {i}. {row['module']}: {row['cnt']} actions")

        # Erreurs recentes
        error_cnt = stats_7d["error_cnt"] if stats_7d else 0
        if error_cnt > 0:
            lines.append(f"\n\u26a0\ufe0f Erreurs 7j: {error_cnt}")

        text = "\n".join(lines)
        await send_message_with_split(update, text, parse_mode="Markdown")

    except ValueError as e:
        await update.message.reply_text(f"Configuration erreur: {e}", parse_mode="Markdown")
    except Exception as e:
        logger.error("/stats command failed", error=str(e), exc_info=True)
        await update.message.reply_text(_ERR_DB, parse_mode="Markdown")
