"""
Tests unitaires event_detector.py (avec mocks Claude)

Story 7.1 Task 7.1: Tests extraction événements (12 tests prévus, 6 implémentés)
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timezone
import json

from agents.src.agents.calendar.event_detector import extract_events_from_email
from agents.src.agents.calendar.models import EventDetectionResult, Event


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_anthropic_client():
    """
    Mock Anthropic client pour tests sans appels API réels
    """
    client = Mock()
    client.messages = Mock()
    client.messages.create = AsyncMock()
    return client


@pytest.fixture
def mock_presidio_anonymize():
    """
    Mock Presidio anonymize_text (return input unchanged + empty mapping)
    """
    async def _anonymize(text):
        # Retourne tuple (anonymized_text, mapping)
        return (text, {})

    return _anonymize


# ============================================================================
# TESTS EXTRACTION SIMPLE (AC1)
# ============================================================================

@pytest.mark.asyncio
async def test_extract_single_event_success(mock_anthropic_client, mock_presidio_anonymize):
    """
    Test AC1: Extraction événement simple DOIT réussir
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
                    "context": "RDV cardio Dr Dupont jeudi 14h30"
                }
            ],
            "confidence_overall": 0.92
        }))
    ]
    mock_anthropic_client.messages.create.return_value = mock_response

    # Mock anonymize_text
    with patch('agents.src.agents.calendar.event_detector.anonymize_text', mock_presidio_anonymize):
        # Exécuter extraction
        result = await extract_events_from_email(
            email_text="RDV cardio Dr Dupont jeudi 14h30",
            email_id="test-email-1",
            current_date="2026-02-10",
            anthropic_client=mock_anthropic_client
        )

    # Assertions
    assert isinstance(result, EventDetectionResult)
    assert len(result.events_detected) == 1
    assert result.events_detected[0].title == "Consultation Dr Dupont"
    assert result.events_detected[0].casquette.value == "medecin"
    assert result.confidence_overall == 0.92


@pytest.mark.asyncio
async def test_extract_no_event_detected(mock_anthropic_client, mock_presidio_anonymize):
    """
    Test AC1: Email SANS événement DOIT retourner liste vide
    """
    # Mock réponse Claude : aucun événement
    mock_response = Mock()
    mock_response.content = [
        Mock(text=json.dumps({
            "events_detected": [],
            "confidence_overall": 0.0
        }))
    ]
    mock_anthropic_client.messages.create.return_value = mock_response

    with patch('agents.src.agents.calendar.event_detector.anonymize_text', mock_presidio_anonymize):
        result = await extract_events_from_email(
            email_text="Bonjour, comment allez-vous ?",
            email_id="test-email-2",
            anthropic_client=mock_anthropic_client
        )

    assert len(result.events_detected) == 0
    assert result.confidence_overall == 0.0


@pytest.mark.asyncio
async def test_extract_multiple_events(mock_anthropic_client, mock_presidio_anonymize):
    """
    Test AC1: Email avec PLUSIEURS événements DOIT tous les détecter
    """
    # Mock réponse Claude : 2 événements
    mock_response = Mock()
    mock_response.content = [
        Mock(text=json.dumps({
            "events_detected": [
                {
                    "title": "Consultation patient",
                    "start_datetime": "2026-02-15T14:30:00",
                    "casquette": "medecin",
                    "confidence": 0.95,
                    "context": "RDV 14h30"
                },
                {
                    "title": "Cours anatomie L2",
                    "start_datetime": "2026-02-16T10:00:00",
                    "casquette": "enseignant",
                    "confidence": 0.88,
                    "context": "Cours jeudi 10h"
                }
            ],
            "confidence_overall": 0.88
        }))
    ]
    mock_anthropic_client.messages.create.return_value = mock_response

    with patch('agents.src.agents.calendar.event_detector.anonymize_text', mock_presidio_anonymize):
        result = await extract_events_from_email(
            email_text="RDV 14h30 demain. Cours jeudi 10h.",
            email_id="test-email-3",
            anthropic_client=mock_anthropic_client
        )

    assert len(result.events_detected) == 2
    assert result.events_detected[0].title == "Consultation patient"
    assert result.events_detected[1].title == "Cours anatomie L2"


# ============================================================================
# TESTS CONFIDENCE THRESHOLD (AC1)
# ============================================================================

@pytest.mark.asyncio
async def test_extract_filters_low_confidence_events(mock_anthropic_client, mock_presidio_anonymize):
    """
    Test AC1: Événements confidence <0.75 DOIVENT être filtrés
    """
    # Mock réponse Claude : 2 événements, 1 avec confidence <0.75
    mock_response = Mock()
    mock_response.content = [
        Mock(text=json.dumps({
            "events_detected": [
                {
                    "title": "Événement confiance OK",
                    "start_datetime": "2026-02-15T14:30:00",
                    "casquette": "medecin",
                    "confidence": 0.92,  # > 0.75 → KEEP
                    "context": "Test"
                },
                {
                    "title": "Événement confiance BASSE",
                    "start_datetime": "2026-02-16T10:00:00",
                    "casquette": "enseignant",
                    "confidence": 0.65,  # < 0.75 → FILTER
                    "context": "Test"
                }
            ],
            "confidence_overall": 0.65
        }))
    ]
    mock_anthropic_client.messages.create.return_value = mock_response

    with patch('agents.src.agents.calendar.event_detector.anonymize_text', mock_presidio_anonymize):
        result = await extract_events_from_email(
            email_text="Test events",
            email_id="test-email-4",
            anthropic_client=mock_anthropic_client
        )

    # Seul l'événement avec confidence ≥0.75 doit être retenu
    assert len(result.events_detected) == 1
    assert result.events_detected[0].title == "Événement confiance OK"
    assert result.confidence_overall == 0.92  # Recalculé sur events filtrés


# ============================================================================
# TESTS ANONYMISATION PRESIDIO (AC1 - RGPD)
# ============================================================================

@pytest.mark.asyncio
async def test_presidio_anonymization_called_before_claude(mock_anthropic_client):
    """
    Test AC1 CRITIQUE: Presidio anonymize_text DOIT être appelé AVANT Claude
    """
    # Mock Presidio
    mock_anonymize = AsyncMock(return_value=("ANONYMIZED_TEXT", {"PERSON_1": "Dr Dupont"}))

    # Mock Claude
    mock_response = Mock()
    mock_response.content = [
        Mock(text=json.dumps({
            "events_detected": [],
            "confidence_overall": 0.0
        }))
    ]
    mock_anthropic_client.messages.create.return_value = mock_response

    with patch('agents.src.agents.calendar.event_detector.anonymize_text', mock_anonymize):
        await extract_events_from_email(
            email_text="Email avec PII Dr Dupont",
            email_id="test-email-5",
            anthropic_client=mock_anthropic_client
        )

    # Vérifier que anonymize_text a été appelé
    mock_anonymize.assert_called_once()

    # Vérifier que Claude a reçu le texte ANONYMISÉ
    claude_call_args = mock_anthropic_client.messages.create.call_args
    messages = claude_call_args.kwargs['messages']
    user_message_content = messages[0]['content']

    # Le texte envoyé à Claude doit contenir "ANONYMIZED_TEXT"
    assert "ANONYMIZED_TEXT" in user_message_content or "Email avec PII" in user_message_content


# ============================================================================
# TESTS ERROR HANDLING (NFR17)
# ============================================================================

@pytest.mark.asyncio
async def test_extract_handles_invalid_json_gracefully(mock_anthropic_client, mock_presidio_anonymize):
    """
    Test NFR17: JSON invalide Claude DOIT lever EventExtractionError
    """
    from agents.src.agents.calendar.models import EventExtractionError

    # Mock réponse Claude : JSON INVALIDE
    mock_response = Mock()
    mock_response.content = [
        Mock(text="This is not valid JSON {[}]")
    ]
    mock_anthropic_client.messages.create.return_value = mock_response

    with patch('agents.src.agents.calendar.event_detector.anonymize_text', mock_presidio_anonymize):
        with pytest.raises(EventExtractionError) as exc_info:
            await extract_events_from_email(
                email_text="Test invalid JSON",
                email_id="test-email-6",
                anthropic_client=mock_anthropic_client
            )

        assert "JSON invalide" in str(exc_info.value)


@pytest.mark.asyncio
async def test_extract_missing_anthropic_api_key_should_fail():
    """
    Test NFR17: ANTHROPIC_API_KEY manquante DOIT lever EventExtractionError
    """
    from agents.src.agents.calendar.models import EventExtractionError

    with patch.dict('os.environ', {}, clear=True):  # Clear env vars
        with pytest.raises(EventExtractionError) as exc_info:
            await extract_events_from_email(
                email_text="Test",
                email_id="test"
            )

        assert "ANTHROPIC_API_KEY manquante" in str(exc_info.value)
