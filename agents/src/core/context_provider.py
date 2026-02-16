"""
Context Provider - Story 4.1 Task 3 + Story 7.2 (get_todays_events)

Fournit le contexte complet pour le LLM Décideur Heartbeat.
Fournit aussi les événements du jour pour Story 7.2 Calendar Sync.

Intégration Story 7.3 ContextManager pour casquette active.

Usage:
    from agents.src.core.context_provider import ContextProvider

    provider = ContextProvider(context_manager, db_pool)
    context = await provider.get_current_context()

    # context.current_time : datetime UTC
    # context.day_of_week : "Monday", "Tuesday", ...
    # context.is_weekend : bool
    # context.is_quiet_hours : bool (22h-8h)
    # context.current_casquette : "medecin" | "enseignant" | "chercheur" | "personnel"
    # context.next_calendar_event : dict | None
    # context.last_activity_mainteneur : datetime | None

    # Story 7.2 Calendar events
    events = await provider.get_todays_events(casquette="medecin")
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

import asyncpg
import structlog
from agents.src.calendar.models import Event
from agents.src.core.context_manager import ContextManager
from agents.src.core.heartbeat_models import HeartbeatContext

logger = structlog.get_logger(__name__)


class ContextProvider:
    """
    Fournit contexte Heartbeat pour LLM Décideur (AC2, Task 3).

    Combine :
    - Story 7.3 ContextManager (casquette active)
    - Temps actuel (UTC, jour semaine, weekend, quiet hours)
    - Prochain événement calendrier (<24h)
    - Dernière activité Mainteneur
    """

    def __init__(self, context_manager: ContextManager, db_pool: asyncpg.Pool):
        """
        Initialize Context Provider.

        Args:
            context_manager: Instance ContextManager (Story 7.3)
            db_pool: Pool PostgreSQL pour queries événements/activité
        """
        self.context_manager = context_manager
        self.db_pool = db_pool

    async def get_current_context(self) -> HeartbeatContext:
        """
        Génère HeartbeatContext complet pour LLM Décideur (Task 3.2).

        Returns:
            HeartbeatContext avec tous les champs peuplés
        """
        # Temps actuel UTC
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        day_of_week = now.strftime("%A")  # Monday, Tuesday, ...
        is_weekend = now.weekday() >= 5  # 5=samedi, 6=dimanche

        # Quiet hours (AC1) — configurable via env vars
        quiet_start = int(os.getenv("HEARTBEAT_QUIET_HOURS_START", "22"))
        quiet_end = int(os.getenv("HEARTBEAT_QUIET_HOURS_END", "8"))
        is_quiet_hours = current_hour >= quiet_start or current_hour < quiet_end

        # Casquette active via Story 7.3 ContextManager (Task 3.4)
        user_context = await self.context_manager.get_current_context()
        current_casquette = user_context.casquette.value if user_context.casquette else None

        # Prochain événement calendrier (<24h)
        next_event = await self._get_next_calendar_event()

        # Dernière activité Mainteneur
        last_activity = await self._get_last_activity()

        context = HeartbeatContext(
            current_time=now,
            day_of_week=day_of_week,
            is_weekend=is_weekend,
            is_quiet_hours=is_quiet_hours,
            current_casquette=current_casquette,
            next_calendar_event=next_event,
            last_activity_mainteneur=last_activity,
        )

        logger.debug(
            "HeartbeatContext generated",
            is_weekend=is_weekend,
            is_quiet_hours=is_quiet_hours,
            casquette=current_casquette,
        )

        return context

    async def get_todays_events(self, casquette: Optional[str] = None) -> List[Event]:
        """Get today's calendar events from knowledge.entities (Story 7.2 AC6).

        Args:
            casquette: Optional filter by casquette (medecin, enseignant, chercheur, personnel)

        Returns:
            List of Event models sorted chronologically by start_datetime.
            Empty list if no events (no exception).
        """
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        query = """
            SELECT id, name, properties, created_at
            FROM knowledge.entities
            WHERE entity_type = 'EVENT'
              AND (properties->>'start_datetime')::timestamptz >= $1
              AND (properties->>'start_datetime')::timestamptz <= $2
        """
        params: list[Any] = [today_start, today_end]

        if casquette:
            query += " AND (properties->>'casquette') = $3"
            params.append(casquette)

        query += " ORDER BY (properties->>'start_datetime')::timestamptz ASC"

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            events = []
            for row in rows:
                try:
                    properties = (
                        row["properties"]
                        if isinstance(row["properties"], dict)
                        else json.loads(row["properties"])
                    )

                    event = Event(
                        id=row["id"],
                        name=row["name"],
                        start_datetime=properties["start_datetime"],
                        end_datetime=properties["end_datetime"],
                        casquette=properties.get("casquette", "medecin"),
                        status=properties.get("status", "confirmed"),
                        location=properties.get("location"),
                        description=properties.get("description"),
                        participants=properties.get("participants", []),
                        html_link=properties.get("html_link"),
                    )
                    events.append(event)
                except Exception as e:
                    logger.warning(
                        "Failed to parse event",
                        event_id=str(row["id"]),
                        error=str(e),
                    )
                    continue

            logger.info(
                "Retrieved today events",
                count=len(events),
                casquette=casquette,
            )
            return events

        except Exception as e:
            logger.error("Failed to fetch today events", error=str(e))
            return []

    async def _get_next_calendar_event(self) -> Optional[Dict[str, Any]]:
        """
        Récupère prochain événement calendrier dans les 24h (Task 3.3).

        Returns:
            Dict avec title, start_datetime, casquette si événement trouvé, None sinon
        """
        try:
            async with self.db_pool.acquire() as conn:
                # C7 fix: field name is start_datetime (not start_time)
                row = await conn.fetchrow("""
                    SELECT
                        name as title,
                        (properties->>'start_datetime')::timestamptz as start_time,
                        properties->>'casquette' as casquette
                    FROM knowledge.entities
                    WHERE entity_type = 'EVENT'
                      AND (properties->>'start_datetime')::timestamptz > NOW()
                      AND (properties->>'start_datetime')::timestamptz < NOW() + INTERVAL '24 hours'
                    ORDER BY (properties->>'start_datetime')::timestamptz ASC
                    LIMIT 1
                    """)

                if row:
                    return {
                        "title": row["title"],
                        "start_time": row["start_time"].isoformat() if row["start_time"] else None,
                        "casquette": row["casquette"],
                    }

        except Exception as e:
            logger.warning("Failed to get next calendar event", error=str(e))

        return None

    async def _get_last_activity(self) -> Optional[datetime]:
        """
        Récupère timestamp dernière activité Mainteneur (Task 3.3).

        Activité = email lu, commande Telegram, etc.

        Returns:
            Datetime dernière activité ou None
        """
        try:
            async with self.db_pool.acquire() as conn:
                # Query dernière activité (simplified pour MVP)
                row = await conn.fetchrow("""
                    SELECT MAX(created_at) as last_activity
                    FROM core.action_receipts
                    WHERE status IN ('auto', 'approved')
                    """)

                if row and row["last_activity"]:
                    return cast(datetime, row["last_activity"])

        except Exception as e:
            logger.warning("Failed to get last activity", error=str(e))

        return None
