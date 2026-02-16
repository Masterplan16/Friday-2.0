"""
Heartbeat Check - Conflits Calendrier (Story 7.3 AC5)

Check périodique détection conflits calendrier aujourd'hui + 7 jours.
Notifie Mainteneur si conflits non résolus détectés.

Priority: MEDIUM (pas CRITICAL)
Quiet hours: 22h-8h (skip), sauf conflit urgent (<6h)
"""

import asyncpg
from datetime import datetime, date, time, timedelta
from typing import Dict, Any, Optional
import structlog

from agents.src.core.heartbeat_models import CheckResult, CheckPriority
from agents.src.agents.calendar.conflict_detector import (
    detect_calendar_conflicts,
    get_conflicts_range
)


logger = structlog.get_logger(__name__)


# ============================================================================
# CHECK FUNCTION (AC5)
# ============================================================================

async def check_calendar_conflicts(
    context: Dict[str, Any],
    db_pool: Optional[asyncpg.Pool] = None
) -> CheckResult:
    """
    Check Heartbeat Phase 3 : Détection conflits calendrier (AC5)

    Vérifie conflits calendrier aujourd'hui + 7 jours prochains.
    Notifie Mainteneur SEULEMENT si conflits non résolus détectés.

    Args:
        context: Contexte Heartbeat (time, hour, is_weekend, quiet_hours, etc.)
        db_pool: Pool PostgreSQL (optionnel, créé si None)

    Returns:
        CheckResult avec notify=True si conflits détectés

    Story 7.3 AC5: Heartbeat check conflits calendrier
    """
    try:
        # 1. Vérifier quiet hours (skip sauf conflit urgent)
        if _should_skip_quiet_hours(context):
            logger.debug("heartbeat_check_calendar_conflicts_skipped_quiet_hours")
            return CheckResult(
                notify=False,
                message=""
            )

        # 2. Récupérer ou créer pool DB
        if db_pool is None:
            import os
            database_url = os.getenv("DATABASE_URL")
            if not database_url:
                logger.error("DATABASE_URL envvar manquante")
                return CheckResult(
                    notify=False,
                    error="DATABASE_URL envvar manquante"
                )

            db_pool = await asyncpg.create_pool(database_url)
            pool_created = True
        else:
            pool_created = False

        # 3. Détecter conflits sur 7 jours
        today = date.today()
        end_date = today + timedelta(days=7)

        conflicts = await get_conflicts_range(
            start_date=today,
            end_date=end_date,
            db_pool=db_pool
        )

        # Fermer pool si créé localement
        if pool_created and db_pool:
            await db_pool.close()

        # 4. Filtrer conflits non résolus
        unresolved_conflicts = [c for c in conflicts if not c.get("resolved", False)]

        if not unresolved_conflicts:
            logger.debug(
                "heartbeat_check_calendar_conflicts_ok",
                total_conflicts=len(conflicts),
                unresolved=0
            )
            return CheckResult(
                notify=False,
                message=""
            )

        # 5. Vérifier si aucun événement dans 7 jours → skip
        # Note: Si conflits trouvés, il y a forcément des événements
        # Cette condition est redondante mais explicite selon Task 7.1

        # 6. Notifier si conflits détectés
        logger.info(
            "heartbeat_check_calendar_conflicts_found",
            unresolved_conflicts=len(unresolved_conflicts),
            total_conflicts=len(conflicts)
        )

        # Formater message notification
        message = _format_conflict_notification(unresolved_conflicts, context)

        return CheckResult(
            notify=True,
            message=message,
            action="view_conflicts",
            payload={
                "conflict_count": len(unresolved_conflicts),
                "date_range": {
                    "start": today.isoformat(),
                    "end": end_date.isoformat()
                },
                "conflicts": [
                    {
                        "id": c.get("id"),
                        "event1_id": c.get("event1_id"),
                        "event2_id": c.get("event2_id"),
                        "overlap_minutes": c.get("overlap_minutes")
                    }
                    for c in unresolved_conflicts
                ]
            }
        )

    except Exception as e:
        logger.error(
            "heartbeat_check_calendar_conflicts_error",
            error=str(e),
            exc_info=True
        )
        return CheckResult(
            notify=False,
            error=str(e)
        )


# ============================================================================
# HELPERS
# ============================================================================

def _should_skip_quiet_hours(context: Dict[str, Any]) -> bool:
    """
    Vérifie si check doit skip quiet hours (AC5)

    Règles :
    - Quiet hours : 22h-8h
    - SAUF : Conflit urgent (<6h)

    Args:
        context: Contexte Heartbeat (doit contenir 'hour')

    Returns:
        True si skip quiet hours, False sinon

    Story 7.3 AC5: Skip quiet hours 22h-8h sauf conflit urgent
    """
    hour = context.get("hour", datetime.now().hour)

    # Quiet hours : 22h-8h (traverse minuit)
    quiet_hours_start = 22
    quiet_hours_end = 8

    is_quiet_hours = (hour >= quiet_hours_start) or (hour < quiet_hours_end)

    if not is_quiet_hours:
        return False  # Pas quiet hours → exécute check

    # Quiet hours : Vérifier si conflit urgent
    # TODO Task 7.1: Implémenter détection conflit urgent (<6h)
    # Pour l'instant, skip toujours pendant quiet hours
    # Story 4.1 complète permettra d'accéder aux conflits urgents ici

    logger.debug(
        "heartbeat_check_calendar_conflicts_quiet_hours",
        hour=hour
    )

    return True  # Skip pendant quiet hours (Day 1)


def _format_conflict_notification(
    conflicts: list,
    context: Dict[str, Any]
) -> str:
    """
    Formate message notification Telegram conflits (AC5)

    Format :
    ⚠️ 2 conflits calendrier détectés (prochains 7 jours)

    📅 Demain : Consultation ⚡ Cours L2
    📅 Mardi : Réunion labo ⚡ Séminaire

    /conflits pour détails et résolution

    Args:
        conflicts: Liste conflits non résolus
        context: Contexte Heartbeat

    Returns:
        Message HTML formaté pour Telegram

    Story 7.3 AC5: Notification Heartbeat conflits
    """
    count = len(conflicts)

    lines = [
        f"⚠️ <b>{count} conflit{'s' if count > 1 else ''} calendrier détecté{'s' if count > 1 else ''}</b>",
        "<i>(prochains 7 jours)</i>",
        ""
    ]

    # Grouper conflits par date
    conflicts_by_date: Dict[str, list] = {}
    for c in conflicts:
        # Parse date depuis event1 start_datetime
        event1_start = c.get("event1_start_datetime")
        if event1_start:
            if isinstance(event1_start, str):
                event1_start = datetime.fromisoformat(event1_start)

            conflict_date = event1_start.date()
            date_key = conflict_date.isoformat()

            if date_key not in conflicts_by_date:
                conflicts_by_date[date_key] = []

            conflicts_by_date[date_key].append(c)

    # Formater lignes par date (max 3 dates)
    today = date.today()
    shown_dates = 0
    max_dates = 3

    for date_str in sorted(conflicts_by_date.keys())[:max_dates]:
        conflict_date = date.fromisoformat(date_str)
        date_conflicts = conflicts_by_date[date_str]

        # Label date relatif
        if conflict_date == today:
            date_label = "Aujourd'hui"
        elif conflict_date == today + timedelta(days=1):
            date_label = "Demain"
        else:
            # Français jour semaine
            jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
            jour_semaine = jours[conflict_date.weekday()]
            date_label = f"{jour_semaine} {conflict_date.strftime('%d/%m')}"

        # Formater conflit (premier de la date)
        first_conflict = date_conflicts[0]
        event1_title = first_conflict.get("event1_title", "Événement 1")
        event2_title = first_conflict.get("event2_title", "Événement 2")

        # Tronquer titres si trop longs
        event1_short = _truncate_title(event1_title, 25)
        event2_short = _truncate_title(event2_title, 25)

        lines.append(f"📅 <b>{date_label}</b> : {event1_short} ⚡ {event2_short}")

        shown_dates += 1

    # Si plus de 3 dates avec conflits
    remaining_dates = len(conflicts_by_date) - max_dates
    if remaining_dates > 0:
        lines.append(f"<i>... et {remaining_dates} autre{'s' if remaining_dates > 1 else ''} date{'s' if remaining_dates > 1 else ''}</i>")

    lines.append("")
    lines.append("/conflits pour détails et résolution")

    return "\n".join(lines)


def _truncate_title(title: str, max_length: int = 25) -> str:
    """
    Tronque titre événement pour affichage compact

    Args:
        title: Titre complet
        max_length: Longueur max

    Returns:
        Titre tronqué avec "..." si nécessaire
    """
    if len(title) <= max_length:
        return title

    return title[:max_length - 3] + "..."


# ============================================================================
# METADATA (pour enregistrement Heartbeat Engine Story 4.1)
# ============================================================================

CHECK_METADATA = {
    "name": "calendar_conflicts",
    "priority": CheckPriority.MEDIUM,
    "description": "Détecte conflits calendrier non résolus (7 jours)",
    "function": check_calendar_conflicts,
    "story": "7.3",
    "phase": 3  # Heartbeat Phase 3 (après urgent checks et proactif)
}
