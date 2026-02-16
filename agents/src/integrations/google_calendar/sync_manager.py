"""Google Calendar synchronization manager."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import asyncpg
import structlog
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .auth import GoogleCalendarAuth
from .config import CalendarConfig
from .models import GoogleCalendarEvent, SyncResult

logger = structlog.get_logger(__name__)

# C2 fix: max retries to prevent infinite recursion on rate limit
MAX_RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BASE_DELAY_S = 1.0


class GoogleCalendarSync:
    """Manage bidirectional synchronization with Google Calendar.

    Handles:
    - Reading events from Google Calendar to PostgreSQL (AC2)
    - Writing events from PostgreSQL to Google Calendar (AC3)
    - Bidirectional sync with conflict detection (AC4)
    """

    def __init__(
        self,
        config: CalendarConfig,
        db_pool: asyncpg.Pool,
        auth_manager: Optional[GoogleCalendarAuth] = None,
    ):
        """Initialize sync manager.

        Args:
            config: Calendar configuration
            db_pool: PostgreSQL connection pool
            auth_manager: OAuth2 authentication manager (optional, created if None)
        """
        self.config = config
        self.db_pool = db_pool
        self.auth_manager = auth_manager or GoogleCalendarAuth()
        self.service = None  # Lazy-loaded Google Calendar service

    async def _get_service(self):
        """Get or create Google Calendar API service.

        Returns:
            Google Calendar API service instance

        Raises:
            NotImplementedError: If authentication fails
        """
        if self.service is None:
            creds = await self.auth_manager.get_credentials()
            # C5 fix: build() is sync but fast (no network), acceptable
            self.service = build("calendar", "v3", credentials=creds)
        return self.service

    async def sync_from_google(self) -> SyncResult:
        """Sync events from Google Calendar to PostgreSQL (AC2).

        Reads events from all configured calendars and creates/updates
        entities in PostgreSQL knowledge.entities table.
        Uses a transaction for atomicity (C4 fix).

        Returns:
            SyncResult with counts of created/updated events
        """
        result = SyncResult(sync_timestamp=datetime.now(timezone.utc))

        try:
            service = await self._get_service()

            # Sync all configured calendars
            for calendar in self.config.google_calendar.calendars:
                try:
                    events = await self._fetch_calendar_events(
                        service, calendar.id, calendar.casquette
                    )

                    # C4 fix: wrap all DB writes in a transaction
                    async with self.db_pool.acquire() as conn:
                        async with conn.transaction():
                            for event in events:
                                created = await self._create_or_update_event(
                                    event, calendar.casquette, conn
                                )
                                if created:
                                    result.events_created += 1
                                else:
                                    result.events_updated += 1

                except HttpError as e:
                    error_msg = "Error syncing calendar %s: %s" % (calendar.name, str(e))
                    result.errors.append(error_msg)
                    logger.warning(
                        "Calendar sync error",
                        calendar=calendar.name,
                        error=str(e),
                    )

        except Exception as e:
            result.errors.append("Sync from Google failed: %s" % str(e))
            logger.error("Sync from Google failed", error=str(e))

        return result

    async def _fetch_calendar_events(
        self, service, calendar_id: str, casquette: str
    ) -> List[GoogleCalendarEvent]:
        """Fetch events from a single Google Calendar.

        Args:
            service: Google Calendar API service
            calendar_id: Calendar ID to fetch from
            casquette: Casquette for this calendar

        Returns:
            List of GoogleCalendarEvent models
        """
        # Build API params - timeMin/timeMax are OPTIONAL per Google Calendar API docs
        # If not specified, API returns ALL events without time filtering
        api_params = {
            "calendarId": calendar_id,
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 2500,
        }

        # Only add time filters if sync_range is configured
        sync_range = self.config.google_calendar.sync_range
        if sync_range is not None:
            now = datetime.now(timezone.utc)
            if sync_range.past_days is not None:
                api_params["timeMin"] = (now - timedelta(days=sync_range.past_days)).isoformat()
            if sync_range.future_days is not None:
                api_params["timeMax"] = (now + timedelta(days=sync_range.future_days)).isoformat()

        # C5 fix: wrap sync Google API .execute() in asyncio.to_thread
        def _list_events():
            return service.events().list(**api_params).execute()

        events_result = await asyncio.to_thread(_list_events)
        google_events = events_result.get("items", [])

        return [GoogleCalendarEvent.from_google_api(event, calendar_id) for event in google_events]

    async def _create_or_update_event(
        self,
        event: GoogleCalendarEvent,
        casquette: str,
        conn: asyncpg.Connection,
    ) -> bool:
        """Create or update event in PostgreSQL.

        Uses external_id for deduplication (UPSERT pattern).
        C4 fix: uses provided connection (within caller's transaction).

        Args:
            event: GoogleCalendarEvent to save
            casquette: Casquette for this event
            conn: asyncpg connection (within transaction)

        Returns:
            True if created (new), False if updated (existing)
        """
        existing = await conn.fetchrow(
            """
            SELECT id FROM knowledge.entities
            WHERE entity_type = 'EVENT'
              AND source_type = 'google_calendar'
              AND (properties->>'external_id') = $1
            """,
            event.id,
        )

        properties = {
            "start_datetime": event.start,
            "end_datetime": event.end,
            "location": event.location or "",
            "casquette": casquette,
            "status": "confirmed",
            "calendar_id": event.calendar_id,
            "external_id": event.id,
            "participants": event.attendees,
            "description": event.description or "",
            "html_link": event.html_link or "",
        }

        if event.updated:
            properties["google_updated_at"] = event.updated

        if existing:
            await conn.execute(
                """
                UPDATE knowledge.entities
                SET name = $1,
                    properties = $2,
                    updated_at = NOW()
                WHERE id = $3
                """,
                event.summary,
                json.dumps(properties),
                existing["id"],
            )
            return False
        else:
            await conn.execute(
                """
                INSERT INTO knowledge.entities (entity_type, name, properties, source_type, confidence)
                VALUES ('EVENT', $1, $2, 'google_calendar', 1.0)
                """,
                event.summary,
                json.dumps(properties),
            )
            return True

    async def write_event_to_google(
        self,
        event_id: str,
        _retry_count: int = 0,
    ) -> Optional[str]:
        """Write event from PostgreSQL to Google Calendar (AC3).

        Args:
            event_id: UUID of event in knowledge.entities
            _retry_count: Internal retry counter (do not set manually)

        Returns:
            Google Calendar event ID if successful, None otherwise

        Raises:
            HttpError: If Google Calendar API call fails after retries
        """
        event_row = await self.db_pool.fetchrow(
            """
            SELECT id, name, properties
            FROM knowledge.entities
            WHERE id = $1 AND entity_type = 'EVENT'
            """,
            event_id,
        )

        if not event_row:
            raise ValueError("Event %s not found in database" % event_id)

        properties = event_row["properties"]
        if isinstance(properties, str):
            properties = json.loads(properties)
        casquette = properties.get("casquette", "medecin")

        calendar_id = self._get_calendar_id_for_casquette(casquette)

        event_body = {
            "summary": event_row["name"],
            "location": properties.get("location", ""),
            "description": (
                "Source: %s | Confidence: %s"
                % (properties.get("source_type", "unknown"), properties.get("confidence", 0.0))
            ),
            "start": {
                "dateTime": properties["start_datetime"],
                "timeZone": "Europe/Paris",
            },
            "end": {
                "dateTime": properties["end_datetime"],
                "timeZone": "Europe/Paris",
            },
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": 30}],
            },
        }

        participants = properties.get("participants", [])
        if participants:
            event_body["attendees"] = [{"email": p} for p in participants if "@" in p]

        service = await self._get_service()

        try:
            # C5 fix: wrap sync .execute() in asyncio.to_thread
            def _insert_event():
                return service.events().insert(calendarId=calendar_id, body=event_body).execute()

            created_event = await asyncio.to_thread(_insert_event)

            google_event_id = created_event["id"]
            html_link = created_event.get("htmlLink", "")

            await self.db_pool.execute(
                """
                UPDATE knowledge.entities
                SET properties = properties || $1::jsonb,
                    updated_at = NOW()
                WHERE id = $2
                """,
                json.dumps(
                    {
                        "external_id": google_event_id,
                        "status": "confirmed",
                        "html_link": html_link,
                    }
                ),
                event_id,
            )

            return google_event_id

        except HttpError as e:
            # C2 fix: bounded retry with exponential backoff (max 3 retries)
            if e.resp.status == 429 and _retry_count < MAX_RATE_LIMIT_RETRIES:
                delay = RATE_LIMIT_BASE_DELAY_S * (2**_retry_count)
                logger.warning(
                    "Rate limit hit, retrying",
                    retry=_retry_count + 1,
                    max_retries=MAX_RATE_LIMIT_RETRIES,
                    delay_s=delay,
                )
                await asyncio.sleep(delay)
                return await self.write_event_to_google(event_id, _retry_count=_retry_count + 1)
            raise

    def _get_calendar_id_for_casquette(self, casquette: str) -> str:
        """Get calendar ID for given casquette.

        Args:
            casquette: medecin, enseignant, chercheur, or personnel

        Returns:
            Calendar ID for this casquette
        """
        for calendar in self.config.google_calendar.calendars:
            if calendar.casquette == casquette:
                return calendar.id

        # Fallback to first calendar
        return self.config.google_calendar.calendars[0].id

    async def sync_bidirectional(self) -> SyncResult:
        """Perform bidirectional synchronization (AC4).

        Strategy:
        - Google Calendar = source of truth (priority read)
        - PostgreSQL modifications -> Immediately sync to Google
        - Conflicts: Last-write-wins based on updated_at timestamp

        Returns:
            SyncResult with counts of synced events
        """
        result = SyncResult(sync_timestamp=datetime.now(timezone.utc))

        try:
            # Step 1: Sync from Google to PostgreSQL (read)
            read_result = await self.sync_from_google()
            result.events_created += read_result.events_created
            result.events_updated += read_result.events_updated
            result.errors.extend(read_result.errors)

            # Step 2: Sync pending local changes to Google (write)
            pending_events = await self.db_pool.fetch(
                """
                SELECT id
                FROM knowledge.entities
                WHERE entity_type = 'EVENT'
                  AND source_type != 'google_calendar'
                  AND (properties->>'status') = 'proposed'
                """
            )

            for row in pending_events:
                try:
                    await self.write_event_to_google(row["id"])
                    result.events_updated += 1
                except Exception as e:
                    result.errors.append("Error writing event %s: %s" % (row["id"], str(e)))
                    logger.warning(
                        "Failed to write event to Google",
                        event_id=str(row["id"]),
                        error=str(e),
                    )

        except Exception as e:
            result.errors.append("Bidirectional sync failed: %s" % str(e))
            logger.error("Bidirectional sync failed", error=str(e))

        return result

    async def detect_modifications(self) -> List[dict]:
        """Detect events modified in Google Calendar.

        Compares updated_at timestamps to detect changes.

        Returns:
            List of dicts with event modifications
        """
        modifications = []

        events = await self.db_pool.fetch(
            """
            SELECT id, name, properties
            FROM knowledge.entities
            WHERE entity_type = 'EVENT'
              AND source_type = 'google_calendar'
              AND (properties->>'external_id') IS NOT NULL
            """
        )

        service = await self._get_service()

        for event_row in events:
            properties = event_row["properties"]
            if isinstance(properties, str):
                properties = json.loads(properties)
            external_id = properties.get("external_id")
            calendar_id = properties.get("calendar_id")
            local_updated = properties.get("google_updated_at")

            if not external_id or not calendar_id:
                continue

            try:
                # C5 fix: wrap sync .execute() in asyncio.to_thread
                def _get_event(cal_id=calendar_id, evt_id=external_id):
                    return service.events().get(calendarId=cal_id, eventId=evt_id).execute()

                google_event = await asyncio.to_thread(_get_event)

                google_updated = google_event.get("updated")

                if local_updated and google_updated != local_updated:
                    modifications.append(
                        {
                            "event_id": event_row["id"],
                            "external_id": external_id,
                            "local_updated": local_updated,
                            "google_updated": google_updated,
                            "google_event": google_event,
                        }
                    )

            except HttpError as e:
                if e.resp.status == 404:
                    modifications.append(
                        {
                            "event_id": event_row["id"],
                            "external_id": external_id,
                            "deleted": True,
                        }
                    )

        return modifications
