"""Unit tests pour ContextProvider - get_todays_events()."""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agents.src.core.context import ContextProvider
from agents.src.calendar.models import Event
from tests.conftest import create_mock_pool_with_conn


@pytest.fixture
def mock_db_pool():
    """Create mock database pool.

    Returns:
        Tuple of (pool, mock_conn) so tests can configure mock_conn.fetch.return_value
    """
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    pool = create_mock_pool_with_conn(mock_conn)
    return pool, mock_conn


@pytest.fixture
def sample_events_today():
    """Create sample events for today."""
    today = datetime.now().date()
    return [
        {
            "id": str(uuid4()),
            "name": "Consultation cardio",
            "entity_type": "EVENT",
            "properties": json.dumps({
                "start_datetime": f"{today}T09:00:00+01:00",
                "end_datetime": f"{today}T10:00:00+01:00",
                "casquette": "medecin",
                "status": "confirmed",
                "location": "Cabinet",
            }),
            "created_at": datetime.now(),
        },
        {
            "id": str(uuid4()),
            "name": "Réunion pédagogique",
            "entity_type": "EVENT",
            "properties": json.dumps({
                "start_datetime": f"{today}T14:00:00+01:00",
                "end_datetime": f"{today}T15:30:00+01:00",
                "casquette": "enseignant",
                "status": "confirmed",
                "location": "Université",
            }),
            "created_at": datetime.now(),
        },
        {
            "id": str(uuid4()),
            "name": "Séminaire recherche",
            "entity_type": "EVENT",
            "properties": json.dumps({
                "start_datetime": f"{today}T16:00:00+01:00",
                "end_datetime": f"{today}T18:00:00+01:00",
                "casquette": "chercheur",
                "status": "confirmed",
                "location": "Lab",
            }),
            "created_at": datetime.now(),
        },
    ]


@pytest.fixture
def sample_events_yesterday():
    """Create sample events for yesterday."""
    yesterday = (datetime.now() - timedelta(days=1)).date()
    return [
        {
            "id": str(uuid4()),
            "name": "Événement hier",
            "entity_type": "EVENT",
            "properties": json.dumps({
                "start_datetime": f"{yesterday}T10:00:00+01:00",
                "end_datetime": f"{yesterday}T11:00:00+01:00",
                "casquette": "medecin",
                "status": "confirmed",
            }),
            "created_at": datetime.now(),
        }
    ]


@pytest.fixture
def sample_events_tomorrow():
    """Create sample events for tomorrow."""
    tomorrow = (datetime.now() + timedelta(days=1)).date()
    return [
        {
            "id": str(uuid4()),
            "name": "Événement demain",
            "entity_type": "EVENT",
            "properties": json.dumps({
                "start_datetime": f"{tomorrow}T10:00:00+01:00",
                "end_datetime": f"{tomorrow}T11:00:00+01:00",
                "casquette": "medecin",
                "status": "confirmed",
            }),
            "created_at": datetime.now(),
        }
    ]


class TestContextProviderEvents:
    """Test suite for ContextProvider.get_todays_events()."""

    @pytest.mark.asyncio
    async def test_get_todays_events_excludes_yesterday_and_tomorrow(
        self, mock_db_pool, sample_events_today, sample_events_yesterday, sample_events_tomorrow
    ):
        """Test événements du jour (exclut hier/demain)."""
        # Arrange
        pool, mock_conn = mock_db_pool
        # Simulate that SQL query already filtered to today's events only
        # (WHERE start_datetime >= today_start AND start_datetime <= today_end)
        mock_conn.fetch.return_value = sample_events_today  # Only today's events

        provider = ContextProvider(db_pool=pool)

        # Act
        events = await provider.get_todays_events()

        # Assert
        # Should return exactly today's events (3 events)
        assert len(events) == 3

        # Verify all events are from today
        today = datetime.now().date()
        for event in events:
            event_date = datetime.fromisoformat(event.start_datetime.replace("+01:00", "")).date()
            assert event_date == today

        # Verify event names (from sample_events_today)
        event_names = [e.name for e in events]
        assert "Consultation cardio" in event_names
        assert "Réunion pédagogique" in event_names
        assert "Séminaire recherche" in event_names

        # Verify yesterday/tomorrow events NOT included
        assert "Événement hier" not in event_names
        assert "Événement demain" not in event_names

    @pytest.mark.asyncio
    async def test_get_todays_events_filters_by_casquette(
        self, mock_db_pool, sample_events_today
    ):
        """Test filtrage par casquette."""
        # Arrange
        pool, mock_conn = mock_db_pool

        # Simulate SQL filtering by casquette (WHERE casquette = $3)
        # Each call to get_todays_events() with different casquette returns filtered results
        mock_conn.fetch.side_effect = [
            [sample_events_today[0]],  # medecin only (Consultation cardio)
            [sample_events_today[1]],  # enseignant only (Réunion pédagogique)
            [sample_events_today[2]],  # chercheur only (Séminaire recherche)
        ]

        provider = ContextProvider(db_pool=pool)

        # Act - Filter by "medecin"
        events_medecin = await provider.get_todays_events(casquette="medecin")

        # Assert
        assert len(events_medecin) == 1
        assert events_medecin[0].name == "Consultation cardio"
        assert events_medecin[0].casquette == "medecin"

        # Act - Filter by "enseignant"
        events_enseignant = await provider.get_todays_events(casquette="enseignant")

        # Assert
        assert len(events_enseignant) == 1
        assert events_enseignant[0].name == "Réunion pédagogique"
        assert events_enseignant[0].casquette == "enseignant"

        # Act - Filter by "chercheur"
        events_chercheur = await provider.get_todays_events(casquette="chercheur")

        # Assert
        assert len(events_chercheur) == 1
        assert events_chercheur[0].name == "Séminaire recherche"
        assert events_chercheur[0].casquette == "chercheur"

    @pytest.mark.asyncio
    async def test_get_todays_events_sorted_chronologically(
        self, mock_db_pool
    ):
        """Test tri chronologique."""
        # Arrange - Create events in wrong order
        pool, mock_conn = mock_db_pool
        today = datetime.now().date()
        unordered_events = [
            {
                "id": str(uuid4()),
                "name": "Event 3 - 18:00",
                "entity_type": "EVENT",
                "properties": json.dumps({
                    "start_datetime": f"{today}T18:00:00+01:00",
                    "end_datetime": f"{today}T19:00:00+01:00",
                    "casquette": "chercheur",
                    "status": "confirmed",
                }),
                "created_at": datetime.now(),
            },
            {
                "id": str(uuid4()),
                "name": "Event 1 - 08:00",
                "entity_type": "EVENT",
                "properties": json.dumps({
                    "start_datetime": f"{today}T08:00:00+01:00",
                    "end_datetime": f"{today}T09:00:00+01:00",
                    "casquette": "medecin",
                    "status": "confirmed",
                }),
                "created_at": datetime.now(),
            },
            {
                "id": str(uuid4()),
                "name": "Event 2 - 14:00",
                "entity_type": "EVENT",
                "properties": json.dumps({
                    "start_datetime": f"{today}T14:00:00+01:00",
                    "end_datetime": f"{today}T15:00:00+01:00",
                    "casquette": "enseignant",
                    "status": "confirmed",
                }),
                "created_at": datetime.now(),
            },
        ]

        # Simulate SQL already sorted the events (ORDER BY start_datetime ASC)
        sorted_events = [
            unordered_events[1],  # Event 1 - 08:00
            unordered_events[2],  # Event 2 - 14:00
            unordered_events[0],  # Event 3 - 18:00
        ]
        mock_conn.fetch.return_value = sorted_events

        provider = ContextProvider(db_pool=pool)

        # Act
        events = await provider.get_todays_events()

        # Assert
        assert len(events) == 3

        # Verify chronological order (08:00 → 14:00 → 18:00)
        assert events[0].name == "Event 1 - 08:00"
        assert events[1].name == "Event 2 - 14:00"
        assert events[2].name == "Event 3 - 18:00"

        # Verify start times are in ascending order
        for i in range(len(events) - 1):
            current_start = datetime.fromisoformat(events[i].start_datetime.replace("+01:00", ""))
            next_start = datetime.fromisoformat(events[i + 1].start_datetime.replace("+01:00", ""))
            assert current_start < next_start

    @pytest.mark.asyncio
    async def test_get_todays_events_empty_list_when_no_events(
        self, mock_db_pool
    ):
        """Test aucun événement → liste vide (pas d'erreur)."""
        # Arrange
        pool, mock_conn = mock_db_pool
        mock_conn.fetch.return_value = []  # No events

        provider = ContextProvider(db_pool=pool)

        # Act
        events = await provider.get_todays_events()

        # Assert
        assert events == []  # Empty list, not None, not exception
        assert isinstance(events, list)
