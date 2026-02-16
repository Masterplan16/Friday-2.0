"""ContextProvider for Heartbeat Engine.

Provides contextual information for proactive agent decisions:
- Today's calendar events
- Recent emails
- Pending tasks
- Current context (time, date, day of week)

Story 4.1 (Heartbeat Engine) will extend this module with additional methods.
Story 7.2 (Calendar Sync) implements get_todays_events() method.
"""

import json
import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

import asyncpg

from agents.src.calendar.models import Event

logger = logging.getLogger(__name__)


class ContextProvider:
    """Provides contextual information for Heartbeat Engine.

    Responsibilities:
    - Fetch today's calendar events (AC6 Story 7.2)
    - Fetch recent emails (TODO Story 2.x)
    - Fetch pending tasks (TODO Story 1.6)
    - Provide current context (time, date, user preferences) (TODO Story 4.1)
    """

    def __init__(self, db_pool: asyncpg.Pool):
        """Initialize context provider.

        Args:
            db_pool: PostgreSQL connection pool
        """
        self.db_pool = db_pool

    async def get_todays_events(
        self, casquette: Optional[str] = None
    ) -> List[Event]:
        """Get today's calendar events from knowledge.entities.

        Args:
            casquette: Optional filter by casquette (medecin, enseignant, chercheur)

        Returns:
            List of Event models sorted chronologically by start_datetime.
            Empty list if no events (no exception).

        Query logic:
        - entity_type = 'EVENT'
        - start_datetime is TODAY (00:00 to 23:59)
        - Optional: filter by casquette in properties
        - Order by start_datetime ASC
        """
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now().replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        # Build query with optional casquette filter
        query = """
            SELECT id, name, properties, created_at
            FROM knowledge.entities
            WHERE entity_type = 'EVENT'
              AND (properties->>'start_datetime')::timestamptz >= $1
              AND (properties->>'start_datetime')::timestamptz <= $2
        """
        params = [today_start, today_end]

        if casquette:
            query += " AND (properties->>'casquette') = $3"
            params.append(casquette)

        query += " ORDER BY (properties->>'start_datetime')::timestamptz ASC"

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            # Convert rows to Event models
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
                        f"Failed to parse event {row['id']}: {e}", exc_info=True
                    )
                    continue

            logger.info(
                f"Retrieved {len(events)} events for today"
                + (f" (casquette={casquette})" if casquette else "")
            )
            return events

        except Exception as e:
            logger.error(f"Failed to fetch today's events: {e}", exc_info=True)
            # Return empty list instead of raising exception (graceful degradation)
            return []

    # TODO Story 4.1 : get_recent_emails()
    # TODO Story 4.1 : get_pending_tasks()
    # TODO Story 4.1 : get_current_context()
