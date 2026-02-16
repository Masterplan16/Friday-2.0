"""
Calendar Conflict Detector - Détection Conflits Agenda

Story 7.3: Multi-casquettes & Conflits (AC4)

Fonctionnalités:
- Détection conflits entre 2+ événements chevauchants (casquettes différentes)
- Algorithme overlap detection (Allen's interval algebra)
- Calcul overlap_minutes précis
- Déduplication conflits (même paire événements)
- Transaction atomique INSERT conflict + notification Telegram
"""

from datetime import date, datetime, timedelta
from typing import Optional

import asyncpg
import structlog
from agents.src.agents.calendar.models import CalendarConflict, CalendarEvent, Casquette

logger = structlog.get_logger(__name__)


# ============================================================================
# Public API
# ============================================================================


async def detect_calendar_conflicts(
    target_date: date, db_pool: asyncpg.Pool
) -> list[CalendarConflict]:
    """
    Détecte conflits calendrier pour une journée donnée (AC4).

    Conflit = 2+ événements avec:
    - Chevauchement temporel (start1 < end2 AND start2 < end1)
    - Casquettes DIFFÉRENTES (même casquette = probablement erreur saisie, pas conflit réel)

    Args:
        target_date: Date à vérifier
        db_pool: Pool PostgreSQL

    Returns:
        Liste conflits détectés (peut être vide)

    Example:
        ```python
        conflicts = await detect_calendar_conflicts(date(2026, 2, 17), db_pool)
        # [CalendarConflict(event1=..., event2=..., overlap_minutes=60)]
        ```
    """
    logger.info("detecting_conflicts", date=str(target_date))

    # Récupérer événements du jour
    events = await _get_events_for_day(target_date, db_pool)

    if len(events) < 2:
        # Pas assez d'événements pour conflit
        logger.debug("no_conflicts_insufficient_events", events_count=len(events))
        return []

    # Détecter conflits (double boucle O(n²))
    conflicts = []

    for i, event1 in enumerate(events):
        for event2 in events[i + 1 :]:
            # Check temporal overlap
            if _has_temporal_overlap(event1, event2):
                # Check different casquettes (même casquette = pas conflit réel)
                if event1.casquette != event2.casquette:
                    overlap_minutes = calculate_overlap(event1, event2)

                    # Skip si pas de chevauchement réel (événements se touchent
                    # exactement, ex: 10h-11h et 11h-12h = 0 min overlap).
                    # CalendarConflict.overlap_minutes a gt=0, donc 0 invalide.
                    if overlap_minutes == 0:
                        continue

                    conflict = CalendarConflict(
                        event1=event1, event2=event2, overlap_minutes=overlap_minutes
                    )

                    conflicts.append(conflict)

                    logger.info(
                        "conflict_detected",
                        event1_id=event1.id,
                        event2_id=event2.id,
                        overlap_minutes=overlap_minutes,
                        casquettes=f"{event1.casquette.value}/{event2.casquette.value}",
                    )

    logger.info(
        "conflict_detection_complete", date=str(target_date), conflicts_count=len(conflicts)
    )

    return conflicts


async def save_conflict_to_db(conflict: CalendarConflict, db_pool: asyncpg.Pool) -> Optional[str]:
    """
    Sauvegarde conflit dans knowledge.calendar_conflicts (AC4).

    Déduplication: Si conflit déjà existe (même paire événements non résolus) → skip.

    Args:
        conflict: CalendarConflict à sauvegarder
        db_pool: Pool PostgreSQL

    Returns:
        UUID conflict_id si créé, None si doublon

    Raises:
        asyncpg.ForeignKeyViolationError: Si event1_id ou event2_id n'existe pas
    """
    async with db_pool.acquire() as conn:
        try:
            # INSERT avec LEAST/GREATEST pour normaliser l'ordre event1/event2
            # et éviter doublons (A,B) vs (B,A).
            # ON CONFLICT DO NOTHING s'appuie sur idx_conflicts_unique_pair
            # (index partiel unique sur LEAST/GREATEST WHERE resolved = FALSE).
            # PostgreSQL ne supporte pas ON CONFLICT sur index d'expressions
            # directement, mais DO NOTHING fonctionne car l'index unique
            # déclenche le conflit sur la paire normalisée.
            conflict_id = await conn.fetchval(
                """
                INSERT INTO knowledge.calendar_conflicts (
                    event1_id,
                    event2_id,
                    overlap_minutes,
                    detected_at
                )
                VALUES (LEAST($1, $2), GREATEST($1, $2), $3, $4)
                ON CONFLICT DO NOTHING
                RETURNING id
            """,
                conflict.event1.id,
                conflict.event2.id,
                conflict.overlap_minutes,
                conflict.detected_at,
            )

            if conflict_id:
                logger.info(
                    "conflict_saved",
                    conflict_id=str(conflict_id),
                    event1_id=conflict.event1.id,
                    event2_id=conflict.event2.id,
                )
                return str(conflict_id)
            else:
                logger.debug(
                    "conflict_duplicate_skipped",
                    event1_id=conflict.event1.id,
                    event2_id=conflict.event2.id,
                )
                return None

        except asyncpg.ForeignKeyViolationError as e:
            logger.error(
                "conflict_save_fk_error",
                error=str(e),
                event1_id=conflict.event1.id,
                event2_id=conflict.event2.id,
            )
            raise

        except asyncpg.DataError as e:
            logger.error(
                "conflict_save_data_error",
                error=str(e),
                event1_id=conflict.event1.id,
                event2_id=conflict.event2.id,
            )
            raise


def calculate_overlap(event1: CalendarEvent, event2: CalendarEvent) -> int:
    """
    Calcule durée chevauchement en minutes entre 2 événements (AC4).

    Algorithme:
    - overlap_start = max(event1.start, event2.start)
    - overlap_end = min(event1.end, event2.end)
    - overlap_minutes = (overlap_end - overlap_start).total_seconds() / 60

    Args:
        event1: Premier événement
        event2: Second événement

    Returns:
        Durée chevauchement en minutes (>0 si chevauchement)

    Example:
        ```python
        # Event1: 14h30-15h30, Event2: 14h00-16h00
        overlap = calculate_overlap(event1, event2)
        # 60 minutes (14h30-15h30)
        ```
    """
    overlap_start = max(event1.start_datetime, event2.start_datetime)
    overlap_end = min(event1.end_datetime, event2.end_datetime)

    if overlap_end <= overlap_start:
        # Pas de chevauchement
        return 0

    overlap_seconds = (overlap_end - overlap_start).total_seconds()
    overlap_minutes = int(overlap_seconds / 60)

    return overlap_minutes


async def get_conflicts_range(
    start_date: date, end_date: date, db_pool: asyncpg.Pool
) -> list[CalendarConflict]:
    """
    Récupère conflits sur une plage de dates (AC5 - Heartbeat check).

    Args:
        start_date: Date début (inclusive)
        end_date: Date fin (inclusive)
        db_pool: Pool PostgreSQL

    Returns:
        Liste conflits sur plage dates

    Example:
        ```python
        # Conflits des 7 prochains jours
        conflicts = await get_conflicts_range(
            start_date=datetime.now().date(),
            end_date=datetime.now().date() + timedelta(days=7),
            db_pool=db_pool
        )
        ```
    """
    # Une seule requête SQL pour toute la plage (H12: évite N+1 queries)
    events = await _get_events_for_range(start_date, end_date, db_pool)

    if len(events) < 2:
        logger.debug("no_conflicts_insufficient_events", events_count=len(events))
        return []

    # Détection conflits en mémoire (double boucle O(n²))
    conflicts = []

    for i, event1 in enumerate(events):
        for event2 in events[i + 1 :]:
            if _has_temporal_overlap(event1, event2):
                if event1.casquette != event2.casquette:
                    overlap_minutes = calculate_overlap(event1, event2)

                    # Skip si pas de chevauchement réel (événements se touchent exactement)
                    if overlap_minutes == 0:
                        continue

                    conflict = CalendarConflict(
                        event1=event1, event2=event2, overlap_minutes=overlap_minutes
                    )

                    conflicts.append(conflict)

    logger.info(
        "conflicts_range_detected",
        start_date=str(start_date),
        end_date=str(end_date),
        events_fetched=len(events),
        conflicts_count=len(conflicts),
    )

    return conflicts


# ============================================================================
# Private Helpers
# ============================================================================


async def _get_events_for_day(target_date: date, db_pool: asyncpg.Pool) -> list[CalendarEvent]:
    """
    Récupère événements confirmés qui chevauchent une journée.

    Inclut les événements multi-jours qui commencent avant ou finissent après
    la date cible (chevauchement temporel, pas seulement DATE(start) = target).

    Args:
        target_date: Date cible
        db_pool: Pool PostgreSQL

    Returns:
        Liste CalendarEvent triés par start_datetime
    """
    async with db_pool.acquire() as conn:
        # Chevauchement temporel : l'événement commence avant la fin du jour
        # ET finit après le début du jour (capte les événements multi-jours)
        rows = await conn.fetch(
            """
            SELECT
                id,
                properties->>'title' AS title,
                properties->>'casquette' AS casquette,
                (properties->>'start_datetime')::timestamptz AS start_datetime,
                (properties->>'end_datetime')::timestamptz AS end_datetime,
                properties->>'status' AS status
            FROM knowledge.entities
            WHERE entity_type = 'EVENT'
              AND (properties->>'status') = 'confirmed'
              AND (properties->>'start_datetime')::timestamptz < ($1::date + interval '1 day')
              AND (properties->>'end_datetime')::timestamptz > $1::date
              AND properties->>'casquette' IS NOT NULL
            ORDER BY (properties->>'start_datetime')::timestamptz ASC
        """,
            target_date,
        )

    return _rows_to_calendar_events(rows)


async def _get_events_for_range(
    start_date: date, end_date: date, db_pool: asyncpg.Pool
) -> list[CalendarEvent]:
    """
    Récupère événements confirmés qui chevauchent une plage de dates.

    Une seule requête SQL pour toute la plage (évite N+1 queries).
    Inclut les événements multi-jours.

    Args:
        start_date: Date début (inclusive)
        end_date: Date fin (inclusive)
        db_pool: Pool PostgreSQL

    Returns:
        Liste CalendarEvent triés par start_datetime
    """
    async with db_pool.acquire() as conn:
        # Chevauchement temporel avec la plage complète :
        # événement commence avant la fin de la plage (end_date + 1 jour)
        # ET finit après le début de la plage (start_date)
        rows = await conn.fetch(
            """
            SELECT
                id,
                properties->>'title' AS title,
                properties->>'casquette' AS casquette,
                (properties->>'start_datetime')::timestamptz AS start_datetime,
                (properties->>'end_datetime')::timestamptz AS end_datetime,
                properties->>'status' AS status
            FROM knowledge.entities
            WHERE entity_type = 'EVENT'
              AND (properties->>'status') = 'confirmed'
              AND (properties->>'start_datetime')::timestamptz < ($2::date + interval '1 day')
              AND (properties->>'end_datetime')::timestamptz > $1::date
              AND properties->>'casquette' IS NOT NULL
            ORDER BY (properties->>'start_datetime')::timestamptz ASC
        """,
            start_date,
            end_date,
        )

    return _rows_to_calendar_events(rows)


def _rows_to_calendar_events(rows: list) -> list[CalendarEvent]:
    """
    Convertit rows asyncpg en liste CalendarEvent.

    Filtre les événements avec casquettes invalides (log warning).

    Args:
        rows: Résultats asyncpg

    Returns:
        Liste CalendarEvent validés
    """
    events = []
    for row in rows:
        # Valider casquette
        try:
            casquette = Casquette(row["casquette"])
        except ValueError:
            logger.warning(
                "invalid_casquette_skipped", event_id=str(row["id"]), casquette=row["casquette"]
            )
            continue

        events.append(
            CalendarEvent(
                id=str(row["id"]),
                title=row["title"],
                casquette=casquette,
                start_datetime=row["start_datetime"],
                end_datetime=row["end_datetime"],
                status=row["status"],
            )
        )

    return events


def _has_temporal_overlap(event1: CalendarEvent, event2: CalendarEvent) -> bool:
    """
    Vérifie si 2 événements se chevauchent temporellement (AC4).

    Algorithme Allen's interval algebra:
    - Overlap si: (start1 < end2) AND (start2 < end1)

    Args:
        event1: Premier événement
        event2: Second événement

    Returns:
        True si chevauchement, False sinon

    Example:
        ```python
        # Event1: 14h30-15h30, Event2: 14h00-16h00
        _has_temporal_overlap(event1, event2)  # True

        # Event1: 09h00-10h00, Event2: 11h00-12h00
        _has_temporal_overlap(event1, event2)  # False
        ```
    """
    return (
        event1.start_datetime < event2.end_datetime and event2.start_datetime < event1.end_datetime
    )
