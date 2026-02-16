"""Unit tests for Google Calendar sync manager."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest
from agents.src.integrations.google_calendar.config import CalendarConfig
from agents.src.integrations.google_calendar.models import (
    GoogleCalendarEvent,
    SyncResult,
)
from agents.src.integrations.google_calendar.sync_manager import GoogleCalendarSync
from googleapiclient.errors import HttpError

# M3 fix: inline config instead of reading real file
INLINE_CONFIG = {
    "google_calendar": {
        "enabled": True,
        "sync_interval_minutes": 30,
        "calendars": [
            {
                "id": "primary",
                "name": "Calendrier Medecin",
                "casquette": "medecin",
                "color": "#ff0000",
            },
            {
                "id": "CALENDAR_ID_ENSEIGNANT_PLACEHOLDER",
                "name": "Calendrier Enseignant",
                "casquette": "enseignant",
                "color": "#00ff00",
            },
            {
                "id": "CALENDAR_ID_CHERCHEUR_PLACEHOLDER",
                "name": "Calendrier Chercheur",
                "casquette": "chercheur",
                "color": "#0000ff",
            },
        ],
        "sync_range": {"past_days": 7, "future_days": 90},
        "default_reminders": [{"method": "popup", "minutes": 30}],
    }
}


@pytest.fixture
def mock_config():
    """Create calendar configuration from inline dict (M3 fix)."""
    return CalendarConfig(**INLINE_CONFIG)


@pytest.fixture
def mock_db_pool():
    """Create mock database pool with transaction support."""
    pool = AsyncMock()

    # Mock connection with transaction support (C4 fix)
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.execute = AsyncMock(return_value="UPDATE 1")

    # Mock transaction context manager
    mock_txn = AsyncMock()
    mock_txn.__aenter__ = AsyncMock(return_value=mock_txn)
    mock_txn.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction = Mock(return_value=mock_txn)

    # Mock acquire context manager
    mock_acquire_cm = AsyncMock()
    mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = Mock(return_value=mock_acquire_cm)

    # Also expose direct pool methods (for write_event_to_google which uses pool.fetchrow)
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.execute = AsyncMock(return_value="UPDATE 1")

    # Store mock_conn for test access
    pool._mock_conn = mock_conn

    return pool


@pytest.fixture
def mock_google_service():
    """Create mock Google Calendar API service."""
    service = Mock()
    service.events = Mock()
    return service


@pytest.fixture
def sample_google_events():
    """Create sample Google Calendar events."""
    return [
        {
            "id": "google_event_1",
            "summary": "Consultation cardio",
            "start": {"dateTime": "2026-02-17T14:00:00+01:00"},
            "end": {"dateTime": "2026-02-17T15:00:00+01:00"},
            "location": "Cabinet medical",
            "updated": "2026-02-16T10:00:00Z",
            "htmlLink": "https://calendar.google.com/event?eid=1",
        },
        {
            "id": "google_event_2",
            "summary": "Garde urgences",
            "start": {"dateTime": "2026-02-18T08:00:00+01:00"},
            "end": {"dateTime": "2026-02-18T20:00:00+01:00"},
            "updated": "2026-02-16T11:00:00Z",
            "htmlLink": "https://calendar.google.com/event?eid=2",
        },
    ]


class TestGoogleCalendarSync:
    """Test suite for Google Calendar synchronization."""

    @pytest.mark.asyncio
    async def test_sync_read_multi_calendars(
        self, mock_config, mock_db_pool, mock_google_service, sample_google_events
    ):
        """Test lecture evenements de 3 calendriers (AC2)."""
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        mock_list = Mock()
        mock_list.execute.return_value = {"items": sample_google_events}
        mock_google_service.events().list.return_value = mock_list

        # C5 fix: patch asyncio.to_thread to run directly
        with patch(
            "agents.src.integrations.google_calendar.sync_manager.asyncio.to_thread",
            side_effect=lambda fn, *a, **kw: fn(*a, **kw) if not callable(fn) else fn(),
        ):
            # Need a smarter patch: to_thread takes a callable
            pass

        # Simpler: patch to_thread to just call the function
        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch(
            "agents.src.integrations.google_calendar.sync_manager.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            result = await sync_manager.sync_from_google()

        assert result.events_created >= 2
        assert result.success

    @pytest.mark.asyncio
    async def test_write_event_to_google(self, mock_config, mock_db_pool, mock_google_service):
        """Test ecriture evenement vers Google Calendar (AC3)."""
        event_id = str(uuid4())
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        mock_db_pool.fetchrow.return_value = {
            "id": event_id,
            "name": "Reunion pedagogique",
            "properties": {
                "start_datetime": "2026-02-20T10:00:00+01:00",
                "end_datetime": "2026-02-20T11:00:00+01:00",
                "location": "Salle B",
                "casquette": "enseignant",
                "participants": ["prof1@univ.fr", "prof2@univ.fr"],
            },
        }

        mock_insert = Mock()
        mock_insert.execute.return_value = {
            "id": "google_event_created",
            "htmlLink": "https://calendar.google.com/event?eid=created",
        }
        mock_google_service.events().insert.return_value = mock_insert

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch(
            "agents.src.integrations.google_calendar.sync_manager.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            google_event_id = await sync_manager.write_event_to_google(event_id)

        assert google_event_id == "google_event_created"
        mock_db_pool.execute.assert_called()

    @pytest.mark.asyncio
    async def test_deduplication_external_id(self, mock_config, mock_db_pool, sample_google_events):
        """Test deduplication via external_id (UPDATE au lieu INSERT)."""
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)

        # C4 fix: _create_or_update_event now takes conn parameter
        mock_conn = mock_db_pool._mock_conn
        existing_event_id = str(uuid4())
        mock_conn.fetchrow.return_value = {"id": existing_event_id}

        event = GoogleCalendarEvent.from_google_api(sample_google_events[0], "primary")

        created = await sync_manager._create_or_update_event(event, "medecin", mock_conn)

        assert created is False  # Should UPDATE, not create
        execute_call = mock_conn.execute.call_args_list[0]
        assert "UPDATE" in execute_call[0][0]

    @pytest.mark.asyncio
    async def test_bidirectional_sync_google_modified(
        self, mock_config, mock_db_pool, mock_google_service, sample_google_events
    ):
        """Test sync bidirectionnelle (Google modified -> PostgreSQL update) (AC4)."""
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        mock_db_pool.fetch.return_value = [
            {
                "id": str(uuid4()),
                "name": "Consultation cardio",
                "properties": {
                    "external_id": "google_event_1",
                    "calendar_id": "primary",
                    "google_updated_at": "2026-02-15T10:00:00Z",
                },
            }
        ]

        mock_get = Mock()
        updated_event = sample_google_events[0].copy()
        updated_event["updated"] = "2026-02-16T10:00:00Z"
        updated_event["summary"] = "Consultation cardio - MODIFIE"
        mock_get.execute.return_value = updated_event
        mock_google_service.events().get.return_value = mock_get

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch(
            "agents.src.integrations.google_calendar.sync_manager.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            modifications = await sync_manager.detect_modifications()

        assert len(modifications) > 0
        assert modifications[0]["google_updated"] == "2026-02-16T10:00:00Z"

    @pytest.mark.asyncio
    async def test_retry_rate_limit_bounded(self, mock_config, mock_db_pool, mock_google_service):
        """Test retry borné si RateLimitError (429) — C2 fix: max 3 retries."""
        event_id = str(uuid4())
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        mock_db_pool.fetchrow.return_value = {
            "id": event_id,
            "name": "Test Event",
            "properties": {
                "start_datetime": "2026-02-20T10:00:00+01:00",
                "end_datetime": "2026-02-20T11:00:00+01:00",
                "casquette": "medecin",
            },
        }

        mock_response_429 = Mock()
        mock_response_429.status = 429
        http_error_429 = HttpError(resp=mock_response_429, content=b"Rate limit")

        mock_insert = Mock()
        mock_insert.execute.side_effect = [
            http_error_429,
            {
                "id": "google_event_retry",
                "htmlLink": "https://calendar.google.com/event?eid=retry",
            },
        ]
        mock_google_service.events().insert.return_value = mock_insert

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch(
                "agents.src.integrations.google_calendar.sync_manager.asyncio.to_thread",
                side_effect=fake_to_thread,
            ),
            patch(
                "agents.src.integrations.google_calendar.sync_manager.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            google_event_id = await sync_manager.write_event_to_google(event_id)

        assert google_event_id == "google_event_retry"

    @pytest.mark.asyncio
    async def test_retry_rate_limit_exhausted(self, mock_config, mock_db_pool, mock_google_service):
        """Test que retry s'arrete apres MAX_RATE_LIMIT_RETRIES (C2 fix)."""
        event_id = str(uuid4())
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        mock_db_pool.fetchrow.return_value = {
            "id": event_id,
            "name": "Test Event",
            "properties": {
                "start_datetime": "2026-02-20T10:00:00+01:00",
                "end_datetime": "2026-02-20T11:00:00+01:00",
                "casquette": "medecin",
            },
        }

        mock_response_429 = Mock()
        mock_response_429.status = 429
        http_error_429 = HttpError(resp=mock_response_429, content=b"Rate limit")

        # All retries fail with 429
        mock_insert = Mock()
        mock_insert.execute.side_effect = http_error_429
        mock_google_service.events().insert.return_value = mock_insert

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch(
                "agents.src.integrations.google_calendar.sync_manager.asyncio.to_thread",
                side_effect=fake_to_thread,
            ),
            patch(
                "agents.src.integrations.google_calendar.sync_manager.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            with pytest.raises(HttpError):
                await sync_manager.write_event_to_google(event_id)

    @pytest.mark.asyncio
    async def test_mapping_casquette_to_calendar_id(self, mock_config):
        """Test mapping casquette -> calendar_id."""
        sync_manager = GoogleCalendarSync(mock_config, Mock())

        calendar_id_medecin = sync_manager._get_calendar_id_for_casquette("medecin")
        calendar_id_enseignant = sync_manager._get_calendar_id_for_casquette("enseignant")
        calendar_id_chercheur = sync_manager._get_calendar_id_for_casquette("chercheur")

        assert calendar_id_medecin == "primary"
        assert calendar_id_enseignant != calendar_id_medecin
        assert calendar_id_chercheur != calendar_id_medecin

    @pytest.mark.asyncio
    async def test_fail_explicit_oauth2_invalid(self, mock_config, mock_db_pool):
        """Test fail-explicit si OAuth2 invalide."""
        mock_auth = AsyncMock()
        mock_auth.get_credentials.side_effect = NotImplementedError("OAuth2 authentication failed")

        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool, mock_auth)

        with pytest.raises(NotImplementedError) as exc_info:
            await sync_manager._get_service()

        assert "OAuth2 authentication failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_recurring_events_expanded(self, mock_config, mock_db_pool, mock_google_service):
        """Test evenements recurrents expanses (singleEvents=true)."""
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        mock_list = Mock()
        mock_list.execute.return_value = {"items": []}
        mock_google_service.events().list.return_value = mock_list

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch(
            "agents.src.integrations.google_calendar.sync_manager.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            await sync_manager._fetch_calendar_events(mock_google_service, "primary", "medecin")

        call_kwargs = mock_google_service.events().list.call_args[1]
        assert call_kwargs.get("singleEvents") is True
        assert call_kwargs.get("orderBy") == "startTime"

    @pytest.mark.asyncio
    async def test_timezone_europe_paris(self, mock_config, mock_db_pool, mock_google_service):
        """Test timezone Europe/Paris dans les evenements."""
        event_id = str(uuid4())
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        mock_db_pool.fetchrow.return_value = {
            "id": event_id,
            "name": "Test Timezone",
            "properties": {
                "start_datetime": "2026-02-20T10:00:00+01:00",
                "end_datetime": "2026-02-20T11:00:00+01:00",
                "casquette": "medecin",
            },
        }

        mock_insert = Mock()
        mock_insert.execute.return_value = {
            "id": "google_event_tz",
            "htmlLink": "https://calendar.google.com/event?eid=tz",
        }
        mock_google_service.events().insert.return_value = mock_insert

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch(
            "agents.src.integrations.google_calendar.sync_manager.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            await sync_manager.write_event_to_google(event_id)

        call_args = mock_google_service.events().insert.call_args
        event_body = call_args[1]["body"]
        assert event_body["start"]["timeZone"] == "Europe/Paris"
        assert event_body["end"]["timeZone"] == "Europe/Paris"

    @pytest.mark.asyncio
    async def test_sync_inverse_postgresql_to_google(
        self, mock_config, mock_db_pool, mock_google_service
    ):
        """Test sync inverse (PostgreSQL modified -> Google update)."""
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        mock_list = Mock()
        mock_list.execute.return_value = {"items": []}
        mock_google_service.events().list.return_value = mock_list

        event_id = str(uuid4())
        pending_event = {
            "id": event_id,
            "name": "Nouvel evenement local",
            "properties": {
                "start_datetime": "2026-02-25T14:00:00+01:00",
                "end_datetime": "2026-02-25T15:00:00+01:00",
                "casquette": "chercheur",
                "status": "proposed",
            },
        }

        mock_db_pool.fetch.side_effect = [
            [pending_event],
        ]
        mock_db_pool.fetchrow.return_value = pending_event

        mock_insert = Mock()
        mock_insert.execute.return_value = {
            "id": "google_event_local",
            "htmlLink": "https://calendar.google.com/event?eid=local",
        }
        mock_google_service.events().insert.return_value = mock_insert

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch(
            "agents.src.integrations.google_calendar.sync_manager.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            result = await sync_manager.sync_bidirectional()

        assert result.events_updated >= 1
        assert result.success

    @pytest.mark.asyncio
    async def test_conflict_last_write_wins(
        self, mock_config, mock_db_pool, mock_google_service, sample_google_events
    ):
        """Test gestion conflits (last-write-wins based on updated_at)."""
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        event_id = str(uuid4())
        local_updated = "2026-02-16T09:00:00Z"
        google_updated = "2026-02-16T11:00:00Z"

        mock_db_pool.fetch.return_value = [
            {
                "id": event_id,
                "name": "Consultation - version locale",
                "properties": {
                    "external_id": "google_event_conflict",
                    "calendar_id": "primary",
                    "google_updated_at": local_updated,
                },
            }
        ]

        mock_get = Mock()
        google_event = sample_google_events[0].copy()
        google_event["id"] = "google_event_conflict"
        google_event["updated"] = google_updated
        google_event["summary"] = "Consultation - version Google"
        mock_get.execute.return_value = google_event
        mock_google_service.events().get.return_value = mock_get

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch(
            "agents.src.integrations.google_calendar.sync_manager.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            modifications = await sync_manager.detect_modifications()

        assert len(modifications) > 0
        assert modifications[0]["google_updated"] == google_updated
        assert modifications[0]["local_updated"] == local_updated
