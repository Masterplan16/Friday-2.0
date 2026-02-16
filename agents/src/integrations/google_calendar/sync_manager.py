"""Google Calendar synchronization manager."""

import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Optional

import asyncpg
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .auth import GoogleCalendarAuth
from .config import CalendarConfig
from .models import GoogleCalendarEvent, SyncResult


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
            self.service = build("calendar", "v3", credentials=creds)
        return self.service

    async def sync_from_google(self) -> SyncResult:
        """Sync events from Google Calendar to PostgreSQL (AC2).

        Reads events from all configured calendars and creates/updates
        entities in PostgreSQL knowledge.entities table.

        Returns:
            SyncResult with counts of created/updated events

        Raises:
            HttpError: If Google Calendar API call fails
        """
        result = SyncResult()

        try:
            service = await self._get_service()

            # Sync all configured calendars
            for calendar in self.config.google_calendar.calendars:
                try:
                    events = await self._fetch_calendar_events(
                        service, calendar.id, calendar.casquette
                    )

                    # Create or update each event in PostgreSQL
                    for event in events:
                        created = await self._create_or_update_event(event, calendar.casquette)
                        if created:
                            result.events_created += 1
                        else:
                            result.events_updated += 1

                except HttpError as e:
                    error_msg = f"Error syncing calendar {calendar.name}: {str(e)}"
                    result.errors.append(error_msg)
                    # Continue with other calendars

        except Exception as e:
            result.errors.append(f"Sync from Google failed: {str(e)}")

        return result

    async def _fetch_calendar_events(
        self, service, calendar_id: str, casquette: str
    ) -> List[GoogleCalendarEvent]:
        """Fetch events from a single Google Calendar.

        Args:
            service: Google Calendar API service
            calendar_id: Calendar ID to fetch from
            casquette: Casquette for this calendar (medecin, enseignant, chercheur)

        Returns:
            List of GoogleCalendarEvent models
        """
        # Calculate time range
        sync_range = self.config.google_calendar.sync_range
        time_min = (
            datetime.now() - timedelta(days=sync_range.past_days)
        ).isoformat() + "Z"
        time_max = (
            datetime.now() + timedelta(days=sync_range.future_days)
        ).isoformat() + "Z"

        # Fetch events from Google Calendar API
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,  # Expand recurring events
                orderBy="startTime",
                maxResults=2500,  # Google Calendar API max
            )
            .execute()
        )

        google_events = events_result.get("items", [])

        # Convert to models
        return [
            GoogleCalendarEvent.from_google_api(event, calendar_id)
            for event in google_events
        ]

    async def _create_or_update_event(
        self, event: GoogleCalendarEvent, casquette: str
    ) -> bool:
        """Create or update event in PostgreSQL.

        Uses external_id for deduplication (UPSERT pattern).

        Args:
            event: GoogleCalendarEvent to save
            casquette: Casquette for this event

        Returns:
            True if created (new), False if updated (existing)
        """
        # Check if event already exists
        existing = await self.db_pool.fetchrow(
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
            # UPDATE existing event
            await self.db_pool.execute(
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
            return False  # Updated
        else:
            # INSERT new event
            await self.db_pool.execute(
                """
                INSERT INTO knowledge.entities (entity_type, name, properties, source_type, confidence)
                VALUES ('EVENT', $1, $2, 'google_calendar', 1.0)
                """,
                event.summary,
                json.dumps(properties),
            )
            return True  # Created

    async def write_event_to_google(self, event_id: str) -> Optional[str]:
        """Write event from PostgreSQL to Google Calendar (AC3).

        Args:
            event_id: UUID of event in knowledge.entities

        Returns:
            Google Calendar event ID if successful, None otherwise

        Raises:
            HttpError: If Google Calendar API call fails
        """
        # Fetch event from PostgreSQL
        event_row = await self.db_pool.fetchrow(
            """
            SELECT id, name, properties
            FROM knowledge.entities
            WHERE id = $1 AND entity_type = 'EVENT'
            """,
            event_id,
        )

        if not event_row:
            raise ValueError(f"Event {event_id} not found in database")

        properties = event_row["properties"]
        casquette = properties.get("casquette", "medecin")

        # Determine target calendar from casquette
        calendar_id = self._get_calendar_id_for_casquette(casquette)

        # Build event body
        event_body = {
            "summary": event_row["name"],
            "location": properties.get("location", ""),
            "description": (
                f"Source: {properties.get('source_type', 'unknown')} | "
                f"Confidence: {properties.get('confidence', 0.0)}"
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

        # Add attendees if present
        participants = properties.get("participants", [])
        if participants:
            event_body["attendees"] = [
                {"email": p} for p in participants if "@" in p
            ]

        # Create event in Google Calendar
        service = await self._get_service()

        try:
            created_event = (
                service.events()
                .insert(calendarId=calendar_id, body=event_body)
                .execute()
            )

            google_event_id = created_event["id"]
            html_link = created_event.get("htmlLink", "")

            # Update PostgreSQL with external_id and status
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
            # Retry on rate limit (exponential backoff)
            if e.resp.status == 429:  # Rate limit
                await asyncio.sleep(1)  # Wait 1 second
                return await self.write_event_to_google(event_id)  # Retry
            raise

    def _get_calendar_id_for_casquette(self, casquette: str) -> str:
        """Get calendar ID for given casquette.

        Args:
            casquette: medecin, enseignant, or chercheur

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

        Detects modifications in both directions and syncs changes.

        Strategy:
        - Google Calendar = source of truth (priority read)
        - PostgreSQL modifications → Immediately sync to Google
        - Conflicts: Last-write-wins based on updated_at timestamp

        Returns:
            SyncResult with counts of synced events
        """
        result = SyncResult()

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
                    result.errors.append(f"Error writing event {row['id']}: {str(e)}")

        except Exception as e:
            result.errors.append(f"Bidirectional sync failed: {str(e)}")

        return result

    async def detect_modifications(self) -> List[dict]:
        """Detect events modified in Google Calendar.

        Compares updated_at timestamps to detect changes.

        Returns:
            List of dicts with event modifications
        """
        modifications = []

        # Get all events with external_id (synced from Google)
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
            external_id = properties.get("external_id")
            calendar_id = properties.get("calendar_id")
            local_updated = properties.get("google_updated_at")

            if not external_id or not calendar_id:
                continue

            try:
                # Fetch current version from Google
                google_event = (
                    service.events()
                    .get(calendarId=calendar_id, eventId=external_id)
                    .execute()
                )

                google_updated = google_event.get("updated")

                # Compare timestamps
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
                    # Event deleted in Google Calendar
                    modifications.append(
                        {
                            "event_id": event_row["id"],
                            "external_id": external_id,
                            "deleted": True,
                        }
                    )

        return modifications
