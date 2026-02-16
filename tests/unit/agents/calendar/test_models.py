"""
Tests unitaires Pydantic models Event & EventDetectionResult

Story 7.1 Task 7.2: Validation models (3 tests)
"""

from datetime import datetime, timezone

import pytest
from agents.src.agents.calendar.models import (
    Casquette,
    Event,
    EventDetectionResult,
    EventStatus,
    EventType,
)
from pydantic import ValidationError

# ============================================================================
# TESTS EVENT MODEL
# ============================================================================


def test_event_valid_all_fields():
    """
    Test AC1: Event avec tous les champs valides DOIT être créé
    """
    event = Event(
        title="Consultation Dr Dupont",
        start_datetime=datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        end_datetime=datetime(2026, 2, 15, 15, 0, tzinfo=timezone.utc),
        location="Cabinet Dr Dupont",
        participants=["Dr Dupont", "Dr Martin"],
        event_type=EventType.MEDICAL,
        casquette=Casquette.MEDECIN,
        confidence=0.92,
        context="Email de Jean: RDV cardio",
    )

    assert event.title == "Consultation Dr Dupont"
    assert event.start_datetime.year == 2026
    assert event.end_datetime.hour == 15
    assert event.location == "Cabinet Dr Dupont"
    assert len(event.participants) == 2
    assert event.event_type == EventType.MEDICAL
    assert event.casquette == Casquette.MEDECIN
    assert event.confidence == 0.92


def test_event_end_before_start_should_fail():
    """
    Test validation: end_datetime AVANT start_datetime DOIT échouer
    """
    with pytest.raises(ValidationError) as exc_info:
        Event(
            title="Événement invalide",
            start_datetime=datetime(2026, 2, 15, 15, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 2, 15, 14, 0, tzinfo=timezone.utc),  # AVANT start
            casquette=Casquette.MEDECIN,
            confidence=0.8,
        )

    assert "end_datetime doit etre apres start_datetime" in str(exc_info.value)


def test_event_confidence_out_of_range_should_fail():
    """
    Test validation: confidence hors range [0.0, 1.0] DOIT échouer
    """
    # Confidence > 1.0
    with pytest.raises(ValidationError) as exc_info:
        Event(
            title="Test",
            start_datetime=datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
            casquette=Casquette.ENSEIGNANT,
            confidence=1.5,  # INVALIDE
        )

    assert "confidence" in str(exc_info.value).lower()

    # Confidence < 0.0
    with pytest.raises(ValidationError) as exc_info:
        Event(
            title="Test",
            start_datetime=datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
            casquette=Casquette.CHERCHEUR,
            confidence=-0.1,  # INVALIDE
        )

    assert "confidence" in str(exc_info.value).lower()


def test_event_title_empty_should_fail():
    """
    Test validation: title vide DOIT échouer
    """
    with pytest.raises(ValidationError) as exc_info:
        Event(
            title="   ",  # Whitespace uniquement
            start_datetime=datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
            casquette=Casquette.MEDECIN,
            confidence=0.8,
        )

    assert "title ne peut pas etre vide" in str(exc_info.value)


def test_event_optional_fields_defaults():
    """
    Test AC1: Champs optionnels (end_datetime, location, participants, context)
    DOIVENT avoir des valeurs par défaut
    """
    event = Event(
        title="Événement minimal",
        start_datetime=datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        casquette=Casquette.ENSEIGNANT,
        confidence=0.85,
    )

    assert event.end_datetime is None
    assert event.location is None
    assert event.participants == []  # Liste vide par défaut
    assert event.context is None
    assert event.event_type == EventType.OTHER  # Default


# ============================================================================
# TESTS EVENT DETECTION RESULT MODEL
# ============================================================================


def test_event_detection_result_empty():
    """
    Test AC1: EventDetectionResult avec 0 événement détecté
    """
    result = EventDetectionResult(
        events_detected=[], confidence_overall=0.0, email_id="550e8400-e29b-41d4-a716-446655440000"
    )

    assert len(result.events_detected) == 0
    assert result.confidence_overall == 0.0
    assert result.email_id == "550e8400-e29b-41d4-a716-446655440000"
    assert result.model_used == "claude-sonnet-4-5-20250929"  # Default


def test_event_detection_result_multiple_events():
    """
    Test AC1: EventDetectionResult avec plusieurs événements
    """
    event1 = Event(
        title="Consultation",
        start_datetime=datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        casquette=Casquette.MEDECIN,
        confidence=0.95,
    )

    event2 = Event(
        title="Réunion",
        start_datetime=datetime(2026, 2, 16, 10, 0, tzinfo=timezone.utc),
        casquette=Casquette.ENSEIGNANT,
        confidence=0.82,
    )

    result = EventDetectionResult(
        events_detected=[event1, event2],
        confidence_overall=0.82,  # Min des deux
        email_id="test-email-id",
    )

    assert len(result.events_detected) == 2
    assert result.events_detected[0].title == "Consultation"
    assert result.events_detected[1].title == "Réunion"
    assert result.confidence_overall == 0.82


def test_event_detection_result_confidence_mismatch_should_fail():
    """
    Test validation: confidence_overall DOIT être min(events.confidence)
    """
    event1 = Event(
        title="Event 1",
        start_datetime=datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        casquette=Casquette.MEDECIN,
        confidence=0.90,
    )

    event2 = Event(
        title="Event 2",
        start_datetime=datetime(2026, 2, 16, 10, 0, tzinfo=timezone.utc),
        casquette=Casquette.ENSEIGNANT,
        confidence=0.75,
    )

    # confidence_overall incorrect (devrait être 0.75, le min)
    with pytest.raises(ValidationError) as exc_info:
        EventDetectionResult(
            events_detected=[event1, event2],
            confidence_overall=0.90,  # INCORRECT (devrait être 0.75)
            email_id="test",
        )

    assert "confidence_overall" in str(exc_info.value)
    assert "min" in str(exc_info.value).lower()


# ============================================================================
# TESTS ENUMS
# ============================================================================


def test_casquette_enum_values():
    """
    Test AC5: Enum Casquette contient les 3 valeurs (medecin, enseignant, chercheur)
    """
    assert Casquette.MEDECIN.value == "medecin"
    assert Casquette.ENSEIGNANT.value == "enseignant"
    assert Casquette.CHERCHEUR.value == "chercheur"


def test_event_status_enum_values():
    """
    Test AC2: Enum EventStatus contient (proposed, confirmed, cancelled)
    """
    assert EventStatus.PROPOSED.value == "proposed"
    assert EventStatus.CONFIRMED.value == "confirmed"
    assert EventStatus.CANCELLED.value == "cancelled"
