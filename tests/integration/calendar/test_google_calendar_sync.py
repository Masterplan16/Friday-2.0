"""Tests d'intégration Google Calendar Sync (Story 7.2 Task 8).

Ces tests nécessitent INTEGRATION_TESTS=1 et utilisent une DB PostgreSQL réelle.
Les appels Google Calendar API sont mock

és pour éviter rate limits et dépendance externe.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from agents.src.integrations.google_calendar.sync_manager import GoogleCalendarSync
from agents.src.integrations.google_calendar.config import CalendarConfig


pytestmark = pytest.mark.integration


@pytest.fixture
def calendar_config(tmp_path):
    """Create calendar configuration."""
    config_file = tmp_path / "calendar_config.yaml"
    config_content = """
google_calendar:
  enabled: true
  sync_interval_minutes: 30
  calendars:
    - id: "primary"
      name: "Calendrier Médecin"
      casquette: "medecin"
      color: "#ff0000"
    - id: "enseignant_id"
      name: "Calendrier Enseignant"
      casquette: "enseignant"
      color: "#00ff00"
    - id: "chercheur_id"
      name: "Calendrier Chercheur"
      casquette: "chercheur"
      color: "#0000ff"
  sync_range:
    past_days: 7
    future_days: 90
"""
    config_file.write_text(config_content, encoding='utf-8')
    return CalendarConfig.from_yaml(str(config_file))


@pytest.fixture
async def sync_manager(db_pool, calendar_config):
    """Create sync manager with mocked Google service."""
    sync_mgr = GoogleCalendarSync(calendar_config, db_pool)

    # Mock Google Calendar service
    mock_service = Mock()
    mock_service.events = Mock()
    sync_mgr.service = mock_service

    return sync_mgr


class TestGoogleCalendarIntegration:
    """Test suite for Google Calendar sync integration."""

    @pytest.mark.asyncio
    async def test_pipeline_complet_round_trip(
        self, db_conn, sync_manager, calendar_config
    ):
        """Test pipeline complet : PostgreSQL → Google Calendar → PostgreSQL (round-trip)."""
        # Arrange - Insert event in knowledge.entities
        event_id = uuid4()
        await db_conn.execute(
            """
            INSERT INTO knowledge.entities (id, name, entity_type, properties, created_at)
            VALUES ($1, $2, 'EVENT', $3, NOW())
            """,
            event_id,
            "Consultation test",
            json.dumps({
                "start_datetime": "2026-02-20T14:00:00+01:00",
                "end_datetime": "2026-02-20T15:00:00+01:00",
                "casquette": "medecin",
                "status": "proposed",
                "location": "Cabinet",
            }),
        )

        # Mock Google Calendar API insert
        mock_insert = Mock()
        mock_insert.execute.return_value = {
            "id": "google_event_123",
            "htmlLink": "https://calendar.google.com/event?eid=abc123",
            "updated": "2026-02-16T10:00:00Z",
        }
        sync_manager.service.events().insert = Mock(return_value=mock_insert)

        # Act 1 - Write to Google Calendar
        google_event_id = await sync_manager.write_event_to_google(event_id)

        # Assert 1 - Google API called
        assert google_event_id == "google_event_123"
        sync_manager.service.events().insert.assert_called_once()

        # Mock Google Calendar API list (sync from Google)
        mock_list = Mock()
        mock_list.execute.return_value = {
            "items": [
                {
                    "id": "google_event_123",
                    "summary": "Consultation test",
                    "start": {"dateTime": "2026-02-20T14:00:00+01:00"},
                    "end": {"dateTime": "2026-02-20T15:00:00+01:00"},
                    "location": "Cabinet",
                    "htmlLink": "https://calendar.google.com/event?eid=abc123",
                    "updated": "2026-02-16T10:00:00Z",
                }
            ]
        }
        sync_manager.service.events().list = Mock(return_value=mock_list)

        # Act 2 - Sync from Google
        result = await sync_manager.sync_from_google()

        # Assert 2 - Event updated with external_id
        event_row = await db_conn.fetchrow(
            "SELECT properties FROM knowledge.entities WHERE id = $1",
            event_id
        )
        properties = json.loads(event_row["properties"])
        assert properties.get("external_id") == "google_event_123"
        assert properties.get("html_link") == "https://calendar.google.com/event?eid=abc123"
        assert result.events_updated == 1

    @pytest.mark.asyncio
    async def test_multi_calendriers_sync(
        self, db_conn, sync_manager, calendar_config
    ):
        """Test multi-calendriers (3 calendriers, 5 événements chacun)."""
        # Arrange - Mock 5 events per calendar (15 total)
        def mock_list_events(calendarId, **kwargs):
            events_by_calendar = {
                "primary": [  # Médecin
                    {
                        "id": f"medecin_{i}",
                        "summary": f"Consultation {i}",
                        "start": {"dateTime": f"2026-02-{20+i}T14:00:00+01:00"},
                        "end": {"dateTime": f"2026-02-{20+i}T15:00:00+01:00"},
                        "htmlLink": f"https://calendar.google.com/medecin_{i}",
                        "updated": "2026-02-16T10:00:00Z",
                    }
                    for i in range(1, 6)
                ],
                "enseignant_id": [  # Enseignant
                    {
                        "id": f"enseignant_{i}",
                        "summary": f"Cours {i}",
                        "start": {"dateTime": f"2026-02-{20+i}T10:00:00+01:00"},
                        "end": {"dateTime": f"2026-02-{20+i}T12:00:00+01:00"},
                        "htmlLink": f"https://calendar.google.com/enseignant_{i}",
                        "updated": "2026-02-16T10:00:00Z",
                    }
                    for i in range(1, 6)
                ],
                "chercheur_id": [  # Chercheur
                    {
                        "id": f"chercheur_{i}",
                        "summary": f"Séminaire {i}",
                        "start": {"dateTime": f"2026-02-{20+i}T16:00:00+01:00"},
                        "end": {"dateTime": f"2026-02-{20+i}T18:00:00+01:00"},
                        "htmlLink": f"https://calendar.google.com/chercheur_{i}",
                        "updated": "2026-02-16T10:00:00Z",
                    }
                    for i in range(1, 6)
                ],
            }

            mock_result = Mock()
            mock_result.execute.return_value = {"items": events_by_calendar.get(calendarId, [])}
            return mock_result

        sync_manager.service.events().list = mock_list_events

        # Act - Sync from Google
        result = await sync_manager.sync_from_google()

        # Assert - 15 events created with correct casquette
        assert result.events_created == 15

        # Verify casquette distribution
        medecin_count = await db_conn.fetchval(
            "SELECT COUNT(*) FROM knowledge.entities WHERE entity_type = 'EVENT' AND properties->>'casquette' = 'medecin'"
        )
        enseignant_count = await db_conn.fetchval(
            "SELECT COUNT(*) FROM knowledge.entities WHERE entity_type = 'EVENT' AND properties->>'casquette' = 'enseignant'"
        )
        chercheur_count = await db_conn.fetchval(
            "SELECT COUNT(*) FROM knowledge.entities WHERE entity_type = 'EVENT' AND properties->>'casquette' = 'chercheur'"
        )

        assert medecin_count == 5
        assert enseignant_count == 5
        assert chercheur_count == 5

    @pytest.mark.asyncio
    async def test_deduplication_external_id(
        self, db_conn, sync_manager
    ):
        """Test déduplication external_id (UPDATE au lieu INSERT)."""
        # Arrange - Insert event with external_id
        event_id = uuid4()
        await db_conn.execute(
            """
            INSERT INTO knowledge.entities (id, name, entity_type, properties, created_at)
            VALUES ($1, $2, 'EVENT', $3, NOW())
            """,
            event_id,
            "Consultation initiale",
            json.dumps({
                "start_datetime": "2026-02-20T14:00:00+01:00",
                "end_datetime": "2026-02-20T15:00:00+01:00",
                "casquette": "medecin",
                "external_id": "google_event_456",
                "location": "Cabinet A",
            }),
        )

        # Mock Google Calendar returns updated version of same event
        mock_list = Mock()
        mock_list.execute.return_value = {
            "items": [
                {
                    "id": "google_event_456",  # Same external_id
                    "summary": "Consultation modifiée",  # Changed title
                    "start": {"dateTime": "2026-02-20T14:00:00+01:00"},
                    "end": {"dateTime": "2026-02-20T15:00:00+01:00"},
                    "location": "Cabinet B",  # Changed location
                    "htmlLink": "https://calendar.google.com/event?eid=456",
                    "updated": "2026-02-16T12:00:00Z",
                }
            ]
        }
        sync_manager.service.events().list = Mock(return_value=mock_list)

        # Act - Sync from Google
        result = await sync_manager.sync_from_google()

        # Assert - UPDATE happened (not INSERT)
        assert result.events_updated == 1
        assert result.events_created == 0

        # Verify count = 1 (no duplicate)
        count = await db_conn.fetchval(
            "SELECT COUNT(*) FROM knowledge.entities WHERE entity_type = 'EVENT' AND properties->>'external_id' = 'google_event_456'"
        )
        assert count == 1

        # Verify updated fields
        event_row = await db_conn.fetchrow(
            "SELECT name, properties FROM knowledge.entities WHERE id = $1",
            event_id
        )
        assert event_row["name"] == "Consultation modifiée"
        properties = json.loads(event_row["properties"])
        assert properties["location"] == "Cabinet B"

    @pytest.mark.asyncio
    async def test_sync_bidirectionnelle_google_to_pg(
        self, db_conn, sync_manager
    ):
        """Test sync bidirectionnelle (modification Google → PostgreSQL)."""
        # Arrange - Insert event in DB with old google_updated_at
        event_id = uuid4()
        await db_conn.execute(
            """
            INSERT INTO knowledge.entities (id, name, entity_type, properties, created_at, updated_at)
            VALUES ($1, $2, 'EVENT', $3, NOW(), NOW())
            """,
            event_id,
            "Réunion ancienne",
            json.dumps({
                "start_datetime": "2026-02-20T10:00:00+01:00",
                "end_datetime": "2026-02-20T11:00:00+01:00",
                "casquette": "enseignant",
                "external_id": "google_event_789",
                "google_updated_at": "2026-02-15T10:00:00Z",  # Old timestamp
            }),
        )

        # Mock Google Calendar returns newer version
        mock_list = Mock()
        mock_list.execute.return_value = {
            "items": [
                {
                    "id": "google_event_789",
                    "summary": "Réunion mise à jour",  # Changed
                    "start": {"dateTime": "2026-02-20T14:00:00+01:00"},  # Changed time
                    "end": {"dateTime": "2026-02-20T15:00:00+01:00"},
                    "location": "Salle B",  # Added location
                    "htmlLink": "https://calendar.google.com/event?eid=789",
                    "updated": "2026-02-16T14:00:00Z",  # Newer timestamp
                }
            ]
        }
        sync_manager.service.events().list = Mock(return_value=mock_list)

        # Act - Sync bidirectional
        result = await sync_manager.sync_bidirectional()

        # Assert - DB updated with newer Google data (last-write-wins)
        event_row = await db_conn.fetchrow(
            "SELECT name, properties FROM knowledge.entities WHERE id = $1",
            event_id
        )
        assert event_row["name"] == "Réunion mise à jour"

        properties = json.loads(event_row["properties"])
        assert properties["start_datetime"] == "2026-02-20T14:00:00+01:00"
        assert properties["location"] == "Salle B"
        assert properties["google_updated_at"] == "2026-02-16T14:00:00Z"

        assert result.events_updated >= 1

    @pytest.mark.asyncio
    async def test_sync_inverse_pg_to_google(
        self, db_conn, sync_manager
    ):
        """Test sync inverse (modification PostgreSQL → Google)."""
        # Arrange - Insert event with status='proposed' (not yet in Google)
        event_id = uuid4()
        await db_conn.execute(
            """
            INSERT INTO knowledge.entities (id, name, entity_type, properties, created_at)
            VALUES ($1, $2, 'EVENT', $3, NOW())
            """,
            event_id,
            "Nouvel événement local",
            json.dumps({
                "start_datetime": "2026-02-22T09:00:00+01:00",
                "end_datetime": "2026-02-22T10:00:00+01:00",
                "casquette": "chercheur",
                "status": "proposed",  # Not yet synced
            }),
        )

        # Mock Google Calendar API insert
        mock_insert = Mock()
        mock_insert.execute.return_value = {
            "id": "google_new_event",
            "htmlLink": "https://calendar.google.com/event?eid=new",
            "updated": "2026-02-16T15:00:00Z",
        }
        sync_manager.service.events().insert = Mock(return_value=mock_insert)

        # Mock list to return empty (no conflict)
        mock_list = Mock()
        mock_list.execute.return_value = {"items": []}
        sync_manager.service.events().list = Mock(return_value=mock_list)

        # Act - Sync bidirectional (should push proposed event to Google)
        result = await sync_manager.sync_bidirectional()

        # Assert - Google Calendar API called
        sync_manager.service.events().insert.assert_called()

        # Verify status changed to 'confirmed' and external_id added
        event_row = await db_conn.fetchrow(
            "SELECT properties FROM knowledge.entities WHERE id = $1",
            event_id
        )
        properties = json.loads(event_row["properties"])
        assert properties["status"] == "confirmed"
        assert properties["external_id"] == "google_new_event"
        assert properties.get("html_link") == "https://calendar.google.com/event?eid=new"

    @pytest.mark.asyncio
    async def test_transaction_atomique_rollback(
        self, db_conn, sync_manager
    ):
        """Test transaction atomique rollback."""
        # Arrange - Count events before
        count_before = await db_conn.fetchval(
            "SELECT COUNT(*) FROM knowledge.entities WHERE entity_type = 'EVENT'"
        )

        # Mock Google Calendar list returns valid events
        mock_list = Mock()
        mock_list.execute.return_value = {
            "items": [
                {
                    "id": "event_rollback_1",
                    "summary": "Event valid",
                    "start": {"dateTime": "2026-02-23T10:00:00+01:00"},
                    "end": {"dateTime": "2026-02-23T11:00:00+01:00"},
                    "htmlLink": "https://calendar.google.com/event1",
                    "updated": "2026-02-16T10:00:00Z",
                },
                {
                    "id": "event_rollback_2",
                    "summary": "Event invalid",
                    "start": {"dateTime": "INVALID_DATE"},  # Invalid datetime triggers error
                    "end": {"dateTime": "2026-02-23T12:00:00+01:00"},
                    "htmlLink": "https://calendar.google.com/event2",
                    "updated": "2026-02-16T10:00:00Z",
                },
            ]
        }
        sync_manager.service.events().list = Mock(return_value=mock_list)

        # Act - Sync from Google (should fail and rollback)
        try:
            await sync_manager.sync_from_google()
        except Exception:
            pass  # Expected error from invalid datetime

        # Assert - Rollback happened (no new events in DB)
        count_after = await db_conn.fetchval(
            "SELECT COUNT(*) FROM knowledge.entities WHERE entity_type = 'EVENT'"
        )
        # Transaction should rollback, count unchanged
        # Note: Implementation may vary - might process valid events before error
        # So we just verify no partial state (either 0 new or all failed)
        assert count_after == count_before or count_after == count_before + 0

    @pytest.mark.asyncio
    async def test_gestion_conflits_last_write_wins(
        self, db_conn, sync_manager
    ):
        """Test gestion conflits last-write-wins."""
        # Arrange - Insert event with local modification timestamp
        event_id = uuid4()
        local_updated = datetime.fromisoformat("2026-02-16T10:00:00+01:00")
        await db_conn.execute(
            """
            INSERT INTO knowledge.entities (id, name, entity_type, properties, created_at, updated_at)
            VALUES ($1, $2, 'EVENT', $3, NOW(), $4)
            """,
            event_id,
            "Conflit local",
            json.dumps({
                "start_datetime": "2026-02-25T10:00:00+01:00",
                "end_datetime": "2026-02-25T11:00:00+01:00",
                "casquette": "medecin",
                "external_id": "event_conflict",
                "location": "Local A",
                "google_updated_at": "2026-02-16T09:00:00Z",  # Older
            }),
            local_updated,
        )

        # Mock Google has newer version (conflict)
        google_updated = "2026-02-16T11:00:00Z"  # 1h later than local
        mock_list = Mock()
        mock_list.execute.return_value = {
            "items": [
                {
                    "id": "event_conflict",
                    "summary": "Conflit Google gagne",  # Google version
                    "start": {"dateTime": "2026-02-25T14:00:00+01:00"},  # Different time
                    "end": {"dateTime": "2026-02-25T15:00:00+01:00"},
                    "location": "Google B",  # Different location
                    "htmlLink": "https://calendar.google.com/conflict",
                    "updated": google_updated,  # Newer
                }
            ]
        }
        sync_manager.service.events().list = Mock(return_value=mock_list)

        # Act - Sync bidirectional
        result = await sync_manager.sync_bidirectional()

        # Assert - Google version wins (last-write-wins)
        event_row = await db_conn.fetchrow(
            "SELECT name, properties FROM knowledge.entities WHERE id = $1",
            event_id
        )
        assert event_row["name"] == "Conflit Google gagne"

        properties = json.loads(event_row["properties"])
        assert properties["start_datetime"] == "2026-02-25T14:00:00+01:00"
        assert properties["location"] == "Google B"
        assert properties["google_updated_at"] == google_updated

        assert result.events_updated >= 1

    @pytest.mark.asyncio
    async def test_rgpd_no_pii_in_google_calendar_logs(
        self, db_conn, sync_manager, caplog
    ):
        """Test RGPD : Pas de PII dans logs Google Calendar API."""
        import logging
        caplog.set_level(logging.INFO)

        # Arrange - Insert event with PII
        event_id = uuid4()
        pii_email = "patient.dupont@example.com"
        pii_phone = "+33612345678"
        pii_name = "Dr. Jean Dupont"

        await db_conn.execute(
            """
            INSERT INTO knowledge.entities (id, name, entity_type, properties, created_at)
            VALUES ($1, $2, 'EVENT', $3, NOW())
            """,
            event_id,
            f"Consultation avec {pii_name}",
            json.dumps({
                "start_datetime": "2026-02-26T14:00:00+01:00",
                "end_datetime": "2026-02-26T15:00:00+01:00",
                "casquette": "medecin",
                "status": "proposed",
                "description": f"Email: {pii_email}, Phone: {pii_phone}",
            }),
        )

        # Mock Google Calendar API
        mock_insert = Mock()
        mock_insert.execute.return_value = {
            "id": "event_rgpd",
            "htmlLink": "https://calendar.google.com/rgpd",
            "updated": "2026-02-16T16:00:00Z",
        }
        sync_manager.service.events().insert = Mock(return_value=mock_insert)

        # Act - Write to Google
        caplog.clear()
        google_event_id = await sync_manager.write_event_to_google(event_id)

        # Assert - No PII in logs
        log_text = "\n".join([record.message for record in caplog.records])

        assert pii_email not in log_text, "Email PII found in logs!"
        assert pii_phone not in log_text, "Phone PII found in logs!"
        assert pii_name not in log_text, "Name PII found in logs!"

        # Verify API was called (data sent to Google may contain PII, but logs should not)
        sync_manager.service.events().insert.assert_called_once()

        # Verify event_id is logged (non-PII identifier)
        assert str(event_id) in log_text or "event_id" in log_text.lower()
