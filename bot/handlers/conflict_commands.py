"""
Commandes Telegram - Dashboard Conflits Calendrier (Story 7.3 AC7)

Commandes:
- /conflits : Dashboard conflits calendrier (non résolus + stats)

Affiche :
- 🔴 Conflits non résolus (détail)
- ✅ Résolus cette semaine (count)
- 📊 Stats mois (total, répartition par casquettes)
"""

import os

import asyncpg
import structlog
from datetime import datetime, date, timedelta, timezone
from telegram import Update
from telegram.ext import ContextTypes
from typing import Any, Dict, Tuple

from agents.src.core.models import (
    Casquette,
    CASQUETTE_EMOJI_MAPPING,
    CASQUETTE_LABEL_MAPPING,
)

logger = structlog.get_logger(__name__)


# ============================================================================
# HANDLER /conflits (AC7)
# ============================================================================


async def handle_conflits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler commande /conflits (AC7)

    Affiche dashboard conflits calendrier :
    - 🔴 Conflits non résolus (liste détaillée)
    - ✅ Résolus cette semaine (count)
    - 📊 Stats mois (total, répartition par casquettes)

    Args:
        update: Telegram Update
        context: Telegram context

    Story 7.3 AC7: Dashboard conflits + stats
    """
    message = update.message
    if not message:
        return

    # H1 fix: Vérifier que l'utilisateur est le propriétaire
    owner_id = os.getenv("OWNER_USER_ID")
    if owner_id and str(message.from_user.id) != owner_id:
        return

    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await message.reply_text("❌ Erreur système : db_pool non initialisé", parse_mode="HTML")
        return

    try:
        # Récupérer conflits non résolus
        unresolved_conflicts = await _get_unresolved_conflicts(db_pool)

        # Récupérer stats semaine (résolus)
        resolved_week = await _get_resolved_week_count(db_pool)

        # Récupérer stats mois
        month_stats = await _get_month_stats(db_pool)

        # Formater message dashboard
        dashboard = _format_dashboard_message(unresolved_conflicts, resolved_week, month_stats)

        await message.reply_text(dashboard, parse_mode="HTML")

        logger.info(
            "conflits_command_executed",
            user_id=message.from_user.id,
            unresolved_count=len(unresolved_conflicts),
            resolved_week=resolved_week,
        )

    except Exception as e:
        logger.error(
            "conflits_command_error", error=str(e), user_id=message.from_user.id, exc_info=True
        )
        await message.reply_text(
            "❌ Erreur lors de la récupération des conflits", parse_mode="HTML"
        )


# ============================================================================
# QUERIES SQL
# ============================================================================


async def _get_unresolved_conflicts(db_pool: asyncpg.Pool) -> list:
    """
    Récupère conflits non résolus depuis DB (AC7)

    Returns:
        Liste conflits avec détails événements
    """
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                c.id,
                c.event1_id,
                c.event2_id,
                c.overlap_minutes,
                c.detected_at,
                e1.name AS event1_title,
                e1.properties->>'casquette' AS event1_casquette,
                e1.properties->>'start_datetime' AS event1_start,
                e2.name AS event2_title,
                e2.properties->>'casquette' AS event2_casquette,
                e2.properties->>'start_datetime' AS event2_start
            FROM knowledge.calendar_conflicts c
            INNER JOIN knowledge.entities e1
                ON c.event1_id = e1.id AND e1.entity_type = 'EVENT'
            INNER JOIN knowledge.entities e2
                ON c.event2_id = e2.id AND e2.entity_type = 'EVENT'
            WHERE c.resolved = false
            ORDER BY e1.properties->>'start_datetime' ASC
            LIMIT 20
            """)

    return [dict(row) for row in rows]


async def _get_resolved_week_count(db_pool: asyncpg.Pool) -> int:
    """
    Compte conflits résolus cette semaine (AC7)

    Returns:
        Nombre conflits résolus (int)
    """
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS count
            FROM knowledge.calendar_conflicts
            WHERE resolved = true
              AND resolved_at >= $1
            """,
            one_week_ago,
        )

    return row["count"] if row else 0


async def _get_month_stats(db_pool: asyncpg.Pool) -> Dict[str, Any]:
    """
    Récupère stats mois conflits (AC7)

    Returns:
        Dict avec total + répartition par casquettes pair

    Format :
    {
        "total": 15,
        "by_casquettes": [
            {"pair": "médecin ⚡ enseignant", "count": 8},
            {"pair": "enseignant ⚡ chercheur", "count": 5},
            {"pair": "médecin ⚡ chercheur", "count": 2}
        ]
    }
    """
    one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)

    async with db_pool.acquire() as conn:
        # Total conflits mois
        total_row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS count
            FROM knowledge.calendar_conflicts
            WHERE detected_at >= $1
            """,
            one_month_ago,
        )

        total = total_row["count"] if total_row else 0

        # Répartition par casquettes pair
        casquettes_rows = await conn.fetch(
            """
            SELECT
                e1.properties->>'casquette' AS casquette1,
                e2.properties->>'casquette' AS casquette2,
                COUNT(*) AS count
            FROM knowledge.calendar_conflicts c
            INNER JOIN knowledge.entities e1
                ON c.event1_id = e1.id AND e1.entity_type = 'EVENT'
            INNER JOIN knowledge.entities e2
                ON c.event2_id = e2.id AND e2.entity_type = 'EVENT'
            WHERE c.detected_at >= $1
            GROUP BY casquette1, casquette2
            ORDER BY count DESC
            LIMIT 5
            """,
            one_month_ago,
        )

        by_casquettes = []
        for row in casquettes_rows:
            casquette1 = row["casquette1"]
            casquette2 = row["casquette2"]

            # Formater pair avec labels français + émojis
            try:
                cas1_enum = Casquette(casquette1)
                cas2_enum = Casquette(casquette2)

                emoji1 = CASQUETTE_EMOJI_MAPPING[cas1_enum]
                emoji2 = CASQUETTE_EMOJI_MAPPING[cas2_enum]
                label1 = CASQUETTE_LABEL_MAPPING[cas1_enum]
                label2 = CASQUETTE_LABEL_MAPPING[cas2_enum]

                pair = f"{emoji1} {label1} ⚡ {emoji2} {label2}"
            except ValueError:
                # Fallback si casquette invalide
                pair = f"{casquette1} ⚡ {casquette2}"

            by_casquettes.append({"pair": pair, "count": row["count"]})

    return {"total": total, "by_casquettes": by_casquettes}


# ============================================================================
# FORMATAGE MESSAGE
# ============================================================================


def _format_dashboard_message(
    unresolved_conflicts: list, resolved_week: int, month_stats: Dict[str, Any]
) -> str:
    """
    Formate message dashboard conflits (AC7)

    Args:
        unresolved_conflicts: Liste conflits non résolus
        resolved_week: Nombre résolus cette semaine
        month_stats: Stats mois (total + répartition)

    Returns:
        Message HTML formaté pour Telegram

    Format :
    📊 DASHBOARD CONFLITS CALENDRIER

    🔴 Non résolus : 3 conflits

    [Liste détaillée conflits]

    ✅ Résolus cette semaine : 5
    📊 Stats mois (30 jours) : 15 conflits

    Répartition casquettes :
    • 🩺 Médecin ⚡ 🎓 Enseignant : 8
    • 🎓 Enseignant ⚡ 🔬 Chercheur : 5
    • 🩺 Médecin ⚡ 🔬 Chercheur : 2
    """
    lines = ["📊 <b>DASHBOARD CONFLITS CALENDRIER</b>", ""]

    # Section 1: Conflits non résolus
    unresolved_count = len(unresolved_conflicts)

    if unresolved_count == 0:
        lines.append("✅ <b>Aucun conflit non résolu</b>")
        lines.append("")
    else:
        lines.append(
            f"🔴 <b>Non résolus</b> : {unresolved_count} conflit{'s' if unresolved_count > 1 else ''}"
        )
        lines.append("")

        # Liste conflits (max 5 affichés)
        for i, conflict in enumerate(unresolved_conflicts[:5], 1):
            conflict_line = _format_conflict_line(conflict)
            lines.append(f"{i}. {conflict_line}")

        # Si plus de 5 conflits
        if unresolved_count > 5:
            remaining = unresolved_count - 5
            lines.append(
                f"<i>... et {remaining} autre{'s' if remaining > 1 else ''} conflit{'s' if remaining > 1 else ''}</i>"
            )

        lines.append("")

    # Section 2: Résolus cette semaine
    lines.append(f"✅ <b>Résolus cette semaine</b> : {resolved_week}")
    lines.append("")

    # Section 3: Stats mois
    total_month = month_stats["total"]
    lines.append(
        f"📊 <b>Stats mois</b> (30 jours) : {total_month} conflit{'s' if total_month > 1 else ''}"
    )

    if month_stats["by_casquettes"]:
        lines.append("")
        lines.append("<b>Répartition casquettes :</b>")

        for entry in month_stats["by_casquettes"]:
            lines.append(f"• {entry['pair']} : {entry['count']}")

    return "\n".join(lines)


def _format_conflict_line(conflict: dict) -> str:
    """
    Formate ligne conflit détaillée

    Args:
        conflict: Dict conflit avec événements

    Returns:
        Ligne formatée HTML

    Format :
    📅 18/02 14h30 : 🩺 Consultation ⚡ 🎓 Cours L2 (30 min)
    """
    # Parse date
    event1_start = conflict["event1_start"]
    if isinstance(event1_start, str):
        event1_start = datetime.fromisoformat(event1_start)

    date_str = event1_start.strftime("%d/%m")
    time_str = event1_start.strftime("%Hh%M")

    # Émojis casquettes
    try:
        cas1 = Casquette(conflict["event1_casquette"])
        cas2 = Casquette(conflict["event2_casquette"])

        emoji1 = CASQUETTE_EMOJI_MAPPING[cas1]
        emoji2 = CASQUETTE_EMOJI_MAPPING[cas2]
    except (ValueError, KeyError):
        emoji1 = ""
        emoji2 = ""

    # Titres tronqués
    title1 = _truncate_title(conflict["event1_title"], 20)
    title2 = _truncate_title(conflict["event2_title"], 20)

    # Durée chevauchement
    overlap = conflict["overlap_minutes"]
    overlap_str = _format_duration(overlap)

    return (
        f"📅 {date_str} {time_str} : " f"{emoji1} {title1} ⚡ {emoji2} {title2} " f"({overlap_str})"
    )


def _truncate_title(title: str, max_length: int = 20) -> str:
    """Tronque titre événement."""
    if len(title) <= max_length:
        return title

    return title[: max_length - 3] + "..."


def _format_duration(minutes: int) -> str:
    """
    Formate durée en heures et minutes

    Args:
        minutes: Durée en minutes

    Returns:
        "1h30", "45 min", "2h00"
    """
    if minutes < 60:
        return f"{minutes} min"

    heures = minutes // 60
    reste_minutes = minutes % 60

    if reste_minutes == 0:
        return f"{heures}h00"

    return f"{heures}h{reste_minutes:02d}"
