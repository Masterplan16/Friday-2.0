"""
Tests intégration pipeline détection événements

Story 7.1 Task 8.1: Pipeline email → detection → entité EVENT → Redis
"""

import pytest
import asyncpg
import json
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timezone

from agents.src.agents.calendar.event_detector import extract_events_from_email


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
async def db_pool():
    """
    Fixture PostgreSQL pool pour tests intégration
    NOTE: Requiert DB PostgreSQL test accessible
    """
    pool = await asyncpg.create_pool(
        host="localhost",
        port=5432,
        user="friday_test",
        password="friday_test",
        database="friday_test",
        min_size=1,
        max_size=5
    )
    yield pool
    await pool.close()


@pytest.fixture
def mock_anthropic_client():
    """Mock Anthropic client"""
    client = Mock()
    client.messages = Mock()
    client.messages.create = AsyncMock()
    return client


# ============================================================================
# TEST PIPELINE COMPLET (AC2)
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
async def test_event_detection_creates_entity_in_db(db_pool, mock_anthropic_client):
    """
    Test AC2: Pipeline complet email → detection → entité EVENT créée

    Flow:
    1. extract_events_from_email (mock Claude)
    2. Créer entité EVENT dans knowledge.entities
    3. Vérifier entité créée avec properties correctes
    """
    # Mock réponse Claude
    mock_response = Mock()
    mock_response.content = [
        Mock(text=json.dumps({
            "events_detected": [
                {
                    "title": "Consultation Dr Dupont",
                    "start_datetime": "2026-02-15T14:30:00",
                    "end_datetime": "2026-02-15T15:00:00",
                    "location": "Cabinet Dr Dupont",
                    "participants": ["Dr Dupont"],
                    "event_type": "medical",
                    "casquette": "medecin",
                    "confidence": 0.92,
                    "context": "RDV cardio"
                }
            ],
            "confidence_overall": 0.92
        }))
    ]
    mock_anthropic_client.messages.create.return_value = mock_response

    # 1. Extraction événement
    with patch('agents.src.agents.calendar.event_detector.anonymize_text',
               AsyncMock(return_value=("RDV cardio Dr Dupont jeudi 14h30", {}))):

        result = await extract_events_from_email(
            email_text="RDV cardio Dr Dupont jeudi 14h30",
            email_id="integration-test-email-1",
            current_date="2026-02-10",
            anthropic_client=mock_anthropic_client
        )

    assert len(result.events_detected) == 1
    event = result.events_detected[0]

    # 2. Créer entité EVENT dans DB (simulation consumer)
    async with db_pool.acquire() as conn:
        # Nettoyer données test précédentes
        await conn.execute(
            "DELETE FROM knowledge.entities WHERE source_id = $1",
            "integration-test-email-1"
        )

        # Créer entité EVENT
        event_properties = {
            "start_datetime": event.start_datetime.isoformat(),
            "end_datetime": event.end_datetime.isoformat() if event.end_datetime else None,
            "location": event.location,
            "participants": event.participants,
            "event_type": event.event_type.value,
            "casquette": event.casquette.value,
            "email_id": "integration-test-email-1",
            "confidence": event.confidence,
            "status": "proposed",
            "calendar_id": None
        }

        event_id = await conn.fetchval(
            """
            INSERT INTO knowledge.entities (
                name, entity_type, properties, confidence,
                source_type, source_id
            ) VALUES ($1, 'EVENT', $2, $3, 'email', $4)
            RETURNING id
            """,
            event.title,
            json.dumps(event_properties),
            event.confidence,
            "integration-test-email-1"
        )

        # 3. Vérifier entité créée
        event_row = await conn.fetchrow(
            "SELECT * FROM knowledge.entities WHERE id = $1",
            event_id
        )

        assert event_row is not None
        assert event_row["name"] == "Consultation Dr Dupont"
        assert event_row["entity_type"] == "EVENT"
        assert event_row["confidence"] == 0.92
        assert event_row["source_type"] == "email"

        # Vérifier properties JSON
        props = event_row["properties"]
        assert props["status"] == "proposed"
        assert props["casquette"] == "medecin"
        assert props["start_datetime"] == "2026-02-15T14:30:00"
        assert props["location"] == "Cabinet Dr Dupont"

        # Cleanup
        await conn.execute("DELETE FROM knowledge.entities WHERE id = $1", event_id)


# ============================================================================
# TEST TRANSACTION ATOMIQUE (AC2 Task 4.4)
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
async def test_event_creation_rollback_on_error(db_pool):
    """
    Test AC2 Task 4.4: Transaction atomique DOIT rollback si erreur

    Simule erreur pendant création relation → transaction rollback
    """
    async with db_pool.acquire() as conn:
        try:
            async with conn.transaction():
                # Créer entité EVENT
                event_id = await conn.fetchval(
                    """
                    INSERT INTO knowledge.entities (
                        name, entity_type, properties, confidence,
                        source_type, source_id
                    ) VALUES ($1, 'EVENT', $2, $3, 'email', $4)
                    RETURNING id
                    """,
                    "Test Event Rollback",
                    json.dumps({
                        "start_datetime": "2026-02-15T14:30:00",
                        "status": "proposed"
                    }),
                    0.9,
                    "rollback-test-email"
                )

                # Simuler erreur (tentative insert relation avec FK invalide)
                await conn.execute(
                    """
                    INSERT INTO knowledge.entity_relations (
                        source_entity_id, target_entity_id, relation_type, confidence
                    ) VALUES ($1, $2, 'MENTIONED_IN', $3)
                    """,
                    event_id,
                    "00000000-0000-0000-0000-000000000000",  # UUID invalide → FK error
                    0.9
                )

        except Exception:
            pass  # Expected error

        # Vérifier que transaction a rollback (entité PAS créée)
        event_exists = await conn.fetchval(
            "SELECT COUNT(*) FROM knowledge.entities WHERE source_id = $1",
            "rollback-test-email"
        )

        assert event_exists == 0  # Rollback réussi


# ============================================================================
# TEST RGPD: PII ANONYMISÉES DANS LOGS (AC1)
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
async def test_event_detection_logs_sanitized(mock_anthropic_client, caplog):
    """
    Test RGPD AC1: Logs DOIVENT être sanitisés (pas de PII)
    """
    import logging
    caplog.set_level(logging.DEBUG)

    # Mock Claude
    mock_response = Mock()
    mock_response.content = [
        Mock(text=json.dumps({
            "events_detected": [],
            "confidence_overall": 0.0
        }))
    ]
    mock_anthropic_client.messages.create.return_value = mock_response

    # Mock Presidio avec PII mapping
    mock_anon_result2 = Mock()
    mock_anon_result2.anonymized_text = "RDV PERSON_1 jeudi"
    mock_anon_result2.mapping = {"PERSON_1": "Dr Dupont"}  # PII réelle
    mock_anonymize = AsyncMock(return_value=mock_anon_result2)

    with patch('agents.src.agents.calendar.event_detector.anonymize_text', mock_anonymize):
        await extract_events_from_email(
            email_text="RDV Dr Dupont jeudi",
            email_id="test-rgpd",
            anthropic_client=mock_anthropic_client
        )

    # Vérifier que logs ne contiennent PAS "Dr Dupont" (PII réelle)
    log_messages = [record.message for record in caplog.records]
    for msg in log_messages:
        assert "Dr Dupont" not in str(msg), f"PII leak in logs: {msg}"
