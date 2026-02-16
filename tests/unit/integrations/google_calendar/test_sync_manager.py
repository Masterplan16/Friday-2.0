"""Unit tests for Google Calendar sync manager."""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from googleapiclient.errors import HttpError

from agents.src.integrations.google_calendar.config import CalendarConfig
from agents.src.integrations.google_calendar.models import (
    GoogleCalendarEvent,
    SyncResult,
)
from agents.src.integrations.google_calendar.sync_manager import GoogleCalendarSync


@pytest.fixture
def mock_config():
    """Create mock calendar configuration."""
    return CalendarConfig.from_yaml("config/calendar_config.yaml")


@pytest.fixture
def mock_db_pool():
    """Create mock database pool."""
    pool = AsyncMock()
    pool.acquire = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.execute = AsyncMock(return_value="UPDATE 1")
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
            "location": "Cabinet médical",
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
        """Test lecture événements de 3 calendriers (AC2)."""
        # Arrange
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        # Mock events().list() to return sample events
        mock_list = Mock()
        mock_list.execute.return_value = {"items": sample_google_events}
        mock_google_service.events().list.return_value = mock_list

        # Act
        result = await sync_manager.sync_from_google()

        # Assert
        assert result.events_created >= 2  # Au moins les 2 events de test
        assert result.success
        # Vérifie que list() a été appelé pour chaque calendrier
        assert mock_google_service.events().list.call_count == 3  # 3 calendriers

    @pytest.mark.asyncio
    async def test_write_event_to_google(
        self, mock_config, mock_db_pool, mock_google_service
    ):
        """Test écriture événement vers Google Calendar (AC3)."""
        # Arrange
        event_id = str(uuid4())
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        # Mock database event
        mock_db_pool.fetchrow.return_value = {
            "id": event_id,
            "name": "Réunion pédagogique",
            "properties": {
                "start_datetime": "2026-02-20T10:00:00+01:00",
                "end_datetime": "2026-02-20T11:00:00+01:00",
                "location": "Salle B",
                "casquette": "enseignant",
                "participants": ["prof1@univ.fr", "prof2@univ.fr"],
            },
        }

        # Mock Google Calendar insert
        mock_insert = Mock()
        mock_insert.execute.return_value = {
            "id": "google_event_created",
            "htmlLink": "https://calendar.google.com/event?eid=created",
        }
        mock_google_service.events().insert.return_value = mock_insert

        # Act
        google_event_id = await sync_manager.write_event_to_google(event_id)

        # Assert
        assert google_event_id == "google_event_created"
        mock_google_service.events().insert.assert_called_once()
        # Vérifie que PostgreSQL a été mis à jour avec external_id
        mock_db_pool.execute.assert_called()

    @pytest.mark.asyncio
    async def test_deduplication_external_id(
        self, mock_config, mock_db_pool, sample_google_events
    ):
        """Test déduplication via external_id (UPDATE au lieu INSERT)."""
        # Arrange
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)

        # Mock existing event in database
        existing_event_id = str(uuid4())
        mock_db_pool.fetchrow.return_value = {"id": existing_event_id}

        event = GoogleCalendarEvent.from_google_api(
            sample_google_events[0], "primary"
        )

        # Act
        created = await sync_manager._create_or_update_event(event, "medecin")

        # Assert
        assert created is False  # Should UPDATE, not create
        # Vérifie que UPDATE a été appelé (pas INSERT)
        execute_call = mock_db_pool.execute.call_args_list[0]
        assert "UPDATE" in execute_call[0][0]

    @pytest.mark.asyncio
    async def test_bidirectional_sync_google_modified(
        self, mock_config, mock_db_pool, mock_google_service, sample_google_events
    ):
        """Test sync bidirectionnelle (Google modified → PostgreSQL update) (AC4)."""
        # Arrange
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        # Mock events in database with old timestamp
        mock_db_pool.fetch.return_value = [
            {
                "id": str(uuid4()),
                "name": "Consultation cardio",
                "properties": {
                    "external_id": "google_event_1",
                    "calendar_id": "primary",
                    "google_updated_at": "2026-02-15T10:00:00Z",  # Older
                },
            }
        ]

        # Mock Google Calendar with newer timestamp
        mock_get = Mock()
        updated_event = sample_google_events[0].copy()
        updated_event["updated"] = "2026-02-16T10:00:00Z"  # Newer
        updated_event["summary"] = "Consultation cardio - MODIFIÉ"  # Changed
        mock_get.execute.return_value = updated_event
        mock_google_service.events().get.return_value = mock_get

        # Act
        modifications = await sync_manager.detect_modifications()

        # Assert
        assert len(modifications) > 0
        assert modifications[0]["google_updated"] == "2026-02-16T10:00:00Z"

    @pytest.mark.asyncio
    async def test_retry_rate_limit_error(
        self, mock_config, mock_db_pool, mock_google_service
    ):
        """Test retry automatique si RateLimitError (429)."""
        # Arrange
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

        # Mock first call returns 429, second call succeeds
        mock_response_429 = Mock()
        mock_response_429.status = 429
        http_error_429 = HttpError(resp=mock_response_429, content=b"Rate limit")

        mock_insert = Mock()
        mock_insert.execute.side_effect = [
            http_error_429,  # First call fails with 429
            {
                "id": "google_event_retry",
                "htmlLink": "https://calendar.google.com/event?eid=retry",
            },  # Second call succeeds
        ]
        mock_google_service.events().insert.return_value = mock_insert

        # Act
        google_event_id = await sync_manager.write_event_to_google(event_id)

        # Assert
        assert google_event_id == "google_event_retry"
        # Vérifie que insert a été appelé 2 fois (retry)
        assert mock_insert.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_mapping_casquette_to_calendar_id(self, mock_config):
        """Test mapping casquette → calendar_id."""
        # Arrange
        sync_manager = GoogleCalendarSync(mock_config, Mock())

        # Act
        calendar_id_medecin = sync_manager._get_calendar_id_for_casquette("medecin")
        calendar_id_enseignant = sync_manager._get_calendar_id_for_casquette(
            "enseignant"
        )
        calendar_id_chercheur = sync_manager._get_calendar_id_for_casquette("chercheur")

        # Assert
        assert calendar_id_medecin == "primary"  # From config
        assert (
            calendar_id_enseignant != calendar_id_medecin
        )  # Different calendar for enseignant
        assert (
            calendar_id_chercheur != calendar_id_medecin
        )  # Different calendar for chercheur

    @pytest.mark.asyncio
    async def test_fail_explicit_oauth2_invalid(self, mock_config, mock_db_pool):
        """Test fail-explicit si OAuth2 invalide."""
        # Arrange
        mock_auth = AsyncMock()
        mock_auth.get_credentials.side_effect = NotImplementedError(
            "OAuth2 authentication failed"
        )

        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool, mock_auth)

        # Act & Assert
        with pytest.raises(NotImplementedError) as exc_info:
            await sync_manager._get_service()

        assert "OAuth2 authentication failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_recurring_events_expanded(
        self, mock_config, mock_db_pool, mock_google_service
    ):
        """Test événements récurrents expansés (singleEvents=true)."""
        # Arrange
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        # Mock list() call
        mock_list = Mock()
        mock_list.execute.return_value = {"items": []}
        mock_google_service.events().list.return_value = mock_list

        # Act
        await sync_manager._fetch_calendar_events(
            mock_google_service, "primary", "medecin"
        )

        # Assert
        # Vérifie que singleEvents=True est passé à l'API
        call_kwargs = mock_google_service.events().list.call_args[1]
        assert call_kwargs.get("singleEvents") is True
        assert call_kwargs.get("orderBy") == "startTime"

    @pytest.mark.asyncio
    async def test_timezone_europe_paris(
        self, mock_config, mock_db_pool, mock_google_service
    ):
        """Test timezone Europe/Paris dans les événements."""
        # Arrange
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

        # Act
        await sync_manager.write_event_to_google(event_id)

        # Assert
        # Vérifie que timeZone="Europe/Paris" est passé
        call_args = mock_google_service.events().insert.call_args
        event_body = call_args[1]["body"]
        assert event_body["start"]["timeZone"] == "Europe/Paris"
        assert event_body["end"]["timeZone"] == "Europe/Paris"

    @pytest.mark.asyncio
    async def test_sync_inverse_postgresql_to_google(
        self, mock_config, mock_db_pool, mock_google_service
    ):
        """Test sync inverse (PostgreSQL modified → Google update)."""
        # Arrange
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        # Mock events().list() to return empty (no Google events to sync)
        mock_list = Mock()
        mock_list.execute.return_value = {"items": []}
        mock_google_service.events().list.return_value = mock_list

        # Mock pending local changes - first call returns pending, second returns empty
        event_id = str(uuid4())
        pending_event = {
            "id": event_id,
            "name": "Nouvel événement local",
            "properties": {
                "start_datetime": "2026-02-25T14:00:00+01:00",
                "end_datetime": "2026-02-25T15:00:00+01:00",
                "casquette": "chercheur",
                "status": "proposed",  # Pending sync
            },
        }

        # First fetch (during sync_bidirectional for pending events)
        mock_db_pool.fetch.side_effect = [
            [pending_event],  # Has pending event
        ]

        mock_db_pool.fetchrow.return_value = pending_event

        mock_insert = Mock()
        mock_insert.execute.return_value = {
            "id": "google_event_local",
            "htmlLink": "https://calendar.google.com/event?eid=local",
        }
        mock_google_service.events().insert.return_value = mock_insert

        # Act
        result = await sync_manager.sync_bidirectional()

        # Assert
        assert result.events_updated >= 1  # Local event synced to Google
        assert result.success

    @pytest.mark.asyncio
    async def test_conflict_last_write_wins(
        self, mock_config, mock_db_pool, mock_google_service, sample_google_events
    ):
        """Test gestion conflits (last-write-wins based on updated_at)."""
        # Arrange
        sync_manager = GoogleCalendarSync(mock_config, mock_db_pool)
        sync_manager.service = mock_google_service

        # Mock event in database (local modification)
        event_id = str(uuid4())
        local_updated = "2026-02-16T09:00:00Z"  # Older
        google_updated = "2026-02-16T11:00:00Z"  # Newer - wins

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

        # Mock Google Calendar with newer version
        mock_get = Mock()
        google_event = sample_google_events[0].copy()
        google_event["id"] = "google_event_conflict"
        google_event["updated"] = google_updated
        google_event["summary"] = "Consultation - version Google"  # Different
        mock_get.execute.return_value = google_event
        mock_google_service.events().get.return_value = mock_get

        # Act
        modifications = await sync_manager.detect_modifications()

        # Assert
        assert len(modifications) > 0
        # Google version is newer → should be detected as modification
        assert modifications[0]["google_updated"] == google_updated
        assert modifications[0]["local_updated"] == local_updated
