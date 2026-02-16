"""Unit tests pour ContextProvider - get_todays_events() (Story 7.2 AC6)."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agents.src.calendar.models import Event
from agents.src.core.context_provider import ContextProvider
from tests.conftest import create_mock_pool_with_conn


@pytest.fixture
def mock_context_manager():
    """Create mock ContextManager (Story 7.3)."""
    cm = AsyncMock()
    mock_user_ctx = MagicMock()
    mock_user_ctx.casquette = MagicMock()
    mock_user_ctx.casquette.value = "medecin"
    cm.get_current_context.return_value = mock_user_ctx
    return cm


@pytest.fixture
def mock_db_pool():
    """Create mock database pool.

    Returns:
        Tuple of (pool, mock_conn) so tests can configure mock_conn.fetch.return_value
    """
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)
    pool = create_mock_pool_with_conn(mock_conn)
    return pool, mock_conn


@pytest.fixture
def sample_events_today():
    """Create sample events for today."""
    today = datetime.now(timezone.utc).date()
    return [
        {
            "id": str(uuid4()),
            "name": "Consultation cardio",
            "entity_type": "EVENT",
            "properties": json.dumps(
                {
                    "start_datetime": f"{today}T09:00:00+01:00",
                    "end_datetime": f"{today}T10:00:00+01:00",
                    "casquette": "medecin",
                    "status": "confirmed",
                    "location": "Cabinet",
                }
            ),
            "created_at": datetime.now(timezone.utc),
        },
        {
            "id": str(uuid4()),
            "name": "Réunion pédagogique",
            "entity_type": "EVENT",
            "properties": json.dumps(
                {
                    "start_datetime": f"{today}T14:00:00+01:00",
                    "end_datetime": f"{today}T15:30:00+01:00",
                    "casquette": "enseignant",
                    "status": "confirmed",
                    "location": "Université",
                }
            ),
            "created_at": datetime.now(timezone.utc),
        },
        {
            "id": str(uuid4()),
            "name": "Séminaire recherche",
            "entity_type": "EVENT",
            "properties": json.dumps(
                {
                    "start_datetime": f"{today}T16:00:00+01:00",
                    "end_datetime": f"{today}T18:00:00+01:00",
                    "casquette": "chercheur",
                    "status": "confirmed",
                    "location": "Lab",
                }
            ),
            "created_at": datetime.now(timezone.utc),
        },
    ]


@pytest.fixture
def sample_events_yesterday():
    """Create sample events for yesterday."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    return [
        {
            "id": str(uuid4()),
            "name": "Événement hier",
            "entity_type": "EVENT",
            "properties": json.dumps(
                {
                    "start_datetime": f"{yesterday}T10:00:00+01:00",
                    "end_datetime": f"{yesterday}T11:00:00+01:00",
                    "casquette": "medecin",
                    "status": "confirmed",
                }
            ),
            "created_at": datetime.now(timezone.utc),
        }
    ]


@pytest.fixture
def sample_events_tomorrow():
    """Create sample events for tomorrow."""
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    return [
        {
            "id": str(uuid4()),
            "name": "Événement demain",
            "entity_type": "EVENT",
            "properties": json.dumps(
                {
                    "start_datetime": f"{tomorrow}T10:00:00+01:00",
                    "end_datetime": f"{tomorrow}T11:00:00+01:00",
                    "casquette": "medecin",
                    "status": "confirmed",
                }
            ),
            "created_at": datetime.now(timezone.utc),
        }
    ]


class TestContextProviderEvents:
    """Test suite for ContextProvider.get_todays_events()."""

    @pytest.mark.asyncio
    async def test_get_todays_events_excludes_yesterday_and_tomorrow(
        self,
        mock_context_manager,
        mock_db_pool,
        sample_events_today,
        sample_events_yesterday,
        sample_events_tomorrow,
    ):
        """Test événements du jour (exclut hier/demain)."""
        pool, mock_conn = mock_db_pool
        mock_conn.fetch.return_value = sample_events_today

        provider = ContextProvider(mock_context_manager, pool)

        events = await provider.get_todays_events()

        assert len(events) == 3
        event_names = [e.name for e in events]
        assert "Consultation cardio" in event_names
        assert "Réunion pédagogique" in event_names
        assert "Séminaire recherche" in event_names
        assert "Événement hier" not in event_names
        assert "Événement demain" not in event_names

    @pytest.mark.asyncio
    async def test_get_todays_events_filters_by_casquette(
        self, mock_context_manager, mock_db_pool, sample_events_today
    ):
        """Test filtrage par casquette."""
        pool, mock_conn = mock_db_pool
        mock_conn.fetch.side_effect = [
            [sample_events_today[0]],
            [sample_events_today[1]],
            [sample_events_today[2]],
        ]

        provider = ContextProvider(mock_context_manager, pool)

        events_medecin = await provider.get_todays_events(casquette="medecin")
        assert len(events_medecin) == 1
        assert events_medecin[0].name == "Consultation cardio"

        events_enseignant = await provider.get_todays_events(casquette="enseignant")
        assert len(events_enseignant) == 1
        assert events_enseignant[0].name == "Réunion pédagogique"

        events_chercheur = await provider.get_todays_events(casquette="chercheur")
        assert len(events_chercheur) == 1
        assert events_chercheur[0].name == "Séminaire recherche"

    @pytest.mark.asyncio
    async def test_get_todays_events_sorted_chronologically(
        self, mock_context_manager, mock_db_pool
    ):
        """Test tri chronologique."""
        pool, mock_conn = mock_db_pool
        today = datetime.now(timezone.utc).date()
        sorted_events = [
            {
                "id": str(uuid4()),
                "name": "Event 1 - 08:00",
                "properties": json.dumps(
                    {
                        "start_datetime": f"{today}T08:00:00+01:00",
                        "end_datetime": f"{today}T09:00:00+01:00",
                        "casquette": "medecin",
                        "status": "confirmed",
                    }
                ),
                "created_at": datetime.now(timezone.utc),
            },
            {
                "id": str(uuid4()),
                "name": "Event 2 - 14:00",
                "properties": json.dumps(
                    {
                        "start_datetime": f"{today}T14:00:00+01:00",
                        "end_datetime": f"{today}T15:00:00+01:00",
                        "casquette": "enseignant",
                        "status": "confirmed",
                    }
                ),
                "created_at": datetime.now(timezone.utc),
            },
            {
                "id": str(uuid4()),
                "name": "Event 3 - 18:00",
                "properties": json.dumps(
                    {
                        "start_datetime": f"{today}T18:00:00+01:00",
                        "end_datetime": f"{today}T19:00:00+01:00",
                        "casquette": "chercheur",
                        "status": "confirmed",
                    }
                ),
                "created_at": datetime.now(timezone.utc),
            },
        ]
        mock_conn.fetch.return_value = sorted_events

        provider = ContextProvider(mock_context_manager, pool)
        events = await provider.get_todays_events()

        assert len(events) == 3
        assert events[0].name == "Event 1 - 08:00"
        assert events[1].name == "Event 2 - 14:00"
        assert events[2].name == "Event 3 - 18:00"

    @pytest.mark.asyncio
    async def test_get_todays_events_empty_list_when_no_events(
        self, mock_context_manager, mock_db_pool
    ):
        """Test aucun événement -> liste vide (pas d'erreur)."""
        pool, mock_conn = mock_db_pool
        mock_conn.fetch.return_value = []

        provider = ContextProvider(mock_context_manager, pool)
        events = await provider.get_todays_events()

        assert events == []
        assert isinstance(events, list)
