"""
Tests unitaires pour message_event_detector.py

Story 7.4 AC1: Extraction evenement depuis message naturel Telegram
18 tests couvrant:
- Detection intention (5 tests)
- Extraction simple (1 test)
- Dates relatives parametrized (6 tests)
- Influence contexte casquette (2 tests AC5)
- Anonymisation Presidio (2 tests)
- Confidence <0.70 (1 test)
- Circuit breaker (1 test)
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.agents.calendar.message_event_detector import (
    CONFIDENCE_THRESHOLD,
    MessageEventResult,
    detect_event_intention,
    extract_event_from_message,
)
from agents.src.agents.calendar.models import EventExtractionError

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_anthropic_client():
    """Mock AsyncAnthropic client."""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_anonymize():
    """Mock anonymize_text returning text unchanged (no PII detected)."""
    result = MagicMock()
    result.anonymized_text = ""  # Will be set per test
    result.mapping = {}
    result.entities_found = []
    result.confidence_min = 1.0
    return result


def _make_claude_response(event_data: dict) -> AsyncMock:
    """Helper to create mock Claude response."""
    mock_response = AsyncMock()
    mock_content = MagicMock()
    mock_content.text = json.dumps(event_data)
    mock_response.content = [mock_content]
    return mock_response


# ============================================================================
# TESTS DETECTION INTENTION (5 tests)
# ============================================================================


class TestDetectEventIntention:
    """Tests pour detect_event_intention()."""

    def test_detect_verb_plus_time(self):
        """Verbe + indicateur temporel = intention detectee."""
        assert detect_event_intention("Ajoute un RDV demain 14h") is True

    def test_detect_context_plus_time(self):
        """Contexte evenement + temps = intention detectee."""
        assert detect_event_intention("Reunion lundi prochain 10h") is True

    def test_detect_verb_plus_context(self):
        """Verbe + contexte evenement = intention detectee."""
        assert detect_event_intention("Planifie une consultation avec Dr Martin") is True

    def test_no_intention_simple_message(self):
        """Message sans intention evenement = pas detecte."""
        assert detect_event_intention("Bonjour, comment vas-tu ?") is False

    def test_no_intention_empty_message(self):
        """Message vide = pas detecte."""
        assert detect_event_intention("") is False
        assert detect_event_intention("abc") is False


# ============================================================================
# TEST EXTRACTION SIMPLE
# ============================================================================


class TestExtractEventSimple:
    """Test extraction evenement simple depuis message Telegram."""

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_extract_simple_rdv(self, mock_anon, mock_anthropic_client):
        """Extraction RDV simple: 'RDV demain 14h'."""
        # Setup anonymize mock
        anon_result = MagicMock()
        anon_result.anonymized_text = "RDV demain 14h"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        # Setup Claude response
        claude_response = {
            "event_detected": True,
            "title": "Rendez-vous",
            "start_datetime": "2026-02-11T14:00:00",
            "end_datetime": "2026-02-11T15:00:00",
            "location": None,
            "participants": [],
            "event_type": "medical",
            "casquette": "medecin",
            "confidence": 0.88,
        }
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_response)
        )

        result = await extract_event_from_message(
            message="RDV demain 14h",
            user_id=12345,
            current_date="2026-02-10",
            anthropic_client=mock_anthropic_client,
        )

        assert result.event_detected is True
        assert result.event is not None
        assert result.event.title == "Rendez-vous"
        assert result.event.casquette.value == "medecin"
        assert result.confidence >= CONFIDENCE_THRESHOLD


# ============================================================================
# TESTS DATES RELATIVES PARAMETRIZED (6 tests)
# ============================================================================


class TestRelativeDateParsing:
    """Tests dates relatives converties par Claude."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "message,expected_date,expected_casquette",
        [
            ("RDV demain 10h", "2026-02-11T10:00:00", "medecin"),
            ("Cours lundi prochain 14h", "2026-02-17T14:00:00", "enseignant"),
            ("Seminaire dans 2 semaines", "2026-02-24T09:00:00", "chercheur"),
            ("Reunion jeudi 16h", "2026-02-13T16:00:00", "enseignant"),
            ("Diner samedi soir 20h", "2026-02-15T20:00:00", "personnel"),
            ("Deadline soumission article 28 fevrier", "2026-02-28T23:59:59", "chercheur"),
        ],
    )
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_relative_date(
        self,
        mock_anon,
        message,
        expected_date,
        expected_casquette,
        mock_anthropic_client,
    ):
        """Test que Claude convertit correctement les dates relatives."""
        # Setup anonymize
        anon_result = MagicMock()
        anon_result.anonymized_text = message
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        # Setup Claude response avec date attendue
        claude_response = {
            "event_detected": True,
            "title": f"Evenement: {message[:20]}",
            "start_datetime": expected_date,
            "end_datetime": None,
            "location": None,
            "participants": [],
            "event_type": "meeting",
            "casquette": expected_casquette,
            "confidence": 0.85,
        }
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_response)
        )

        result = await extract_event_from_message(
            message=message,
            current_date="2026-02-10",
            anthropic_client=mock_anthropic_client,
        )

        assert result.event_detected is True
        assert result.event is not None
        assert result.event.casquette.value == expected_casquette


# ============================================================================
# TESTS INFLUENCE CONTEXTE CASQUETTE (AC5 - 2 tests)
# ============================================================================


class TestContextInfluence:
    """Tests influence contexte casquette (Story 7.4 AC5)."""

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_context_medecin_bias(self, mock_anon, mock_anthropic_client):
        """Contexte=medecin + message ambigu -> bias vers medecin."""
        from agents.src.core.models import Casquette

        anon_result = MagicMock()
        anon_result.anonymized_text = "RDV demain 14h avec Jean"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        # Claude repond medecin (influence par contexte)
        claude_response = {
            "event_detected": True,
            "title": "Rendez-vous avec Jean",
            "start_datetime": "2026-02-11T14:00:00",
            "end_datetime": "2026-02-11T15:00:00",
            "location": None,
            "participants": ["Jean"],
            "event_type": "medical",
            "casquette": "medecin",
            "confidence": 0.85,
        }
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_response)
        )

        result = await extract_event_from_message(
            message="RDV demain 14h avec Jean",
            current_date="2026-02-10",
            anthropic_client=mock_anthropic_client,
            current_casquette=Casquette.MEDECIN,
        )

        assert result.event_detected is True
        assert result.event.casquette.value == "medecin"

        # Verifier que le prompt contient le contexte casquette
        call_args = mock_anthropic_client.messages.create.call_args
        prompt_content = call_args.kwargs["messages"][0]["content"]
        assert "Médecin" in prompt_content or "CONTEXTE ACTUEL" in prompt_content

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_context_override_explicit_keywords(self, mock_anon, mock_anthropic_client):
        """Contexte=medecin + mots-cles explicites enseignant -> override."""
        from agents.src.core.models import Casquette

        anon_result = MagicMock()
        anon_result.anonymized_text = "Cours L2 anatomie demain 14h amphi B"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        # Claude repond enseignant (mots-cles overrident contexte)
        claude_response = {
            "event_detected": True,
            "title": "Cours L2 anatomie",
            "start_datetime": "2026-02-11T14:00:00",
            "end_datetime": "2026-02-11T16:00:00",
            "location": "Amphi B",
            "participants": [],
            "event_type": "meeting",
            "casquette": "enseignant",
            "confidence": 0.92,
        }
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_response)
        )

        result = await extract_event_from_message(
            message="Cours L2 anatomie demain 14h amphi B",
            current_date="2026-02-10",
            anthropic_client=mock_anthropic_client,
            current_casquette=Casquette.MEDECIN,
        )

        assert result.event_detected is True
        assert result.event.casquette.value == "enseignant"


# ============================================================================
# TESTS ANONYMISATION PRESIDIO (2 tests)
# ============================================================================


class TestPresidioAnonymization:
    """Tests anonymisation Presidio integree."""

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_anonymize_called_before_claude(self, mock_anon, mock_anthropic_client):
        """Anonymise AVANT appel Claude (RGPD)."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "RDV demain 14h avec [PERSON_1]"
        anon_result.mapping = {"[PERSON_1]": "Dr Dupont"}
        mock_anon.return_value = anon_result

        claude_response = {
            "event_detected": True,
            "title": "RDV avec [PERSON_1]",
            "start_datetime": "2026-02-11T14:00:00",
            "end_datetime": "2026-02-11T15:00:00",
            "location": None,
            "participants": ["[PERSON_1]"],
            "event_type": "medical",
            "casquette": "medecin",
            "confidence": 0.90,
        }
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_response)
        )

        result = await extract_event_from_message(
            message="RDV demain 14h avec Dr Dupont",
            current_date="2026-02-10",
            anthropic_client=mock_anthropic_client,
        )

        # Verifier anonymize_text appele avec message original
        mock_anon.assert_called_once_with("RDV demain 14h avec Dr Dupont")

        # Verifier participants deanonymises
        assert result.event_detected is True
        assert "Dr Dupont" in result.event.participants

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_presidio_mapping_restored(self, mock_anon, mock_anthropic_client):
        """Mapping Presidio restaure les vrais noms participants."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "Reunion avec [PERSON_1] et [PERSON_2]"
        anon_result.mapping = {
            "[PERSON_1]": "Marie",
            "[PERSON_2]": "Jean",
        }
        mock_anon.return_value = anon_result

        claude_response = {
            "event_detected": True,
            "title": "Reunion",
            "start_datetime": "2026-02-11T10:00:00",
            "end_datetime": "2026-02-11T11:00:00",
            "location": None,
            "participants": ["[PERSON_1]", "[PERSON_2]"],
            "event_type": "meeting",
            "casquette": "enseignant",
            "confidence": 0.85,
        }
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_response)
        )

        result = await extract_event_from_message(
            message="Reunion avec Marie et Jean demain 10h",
            current_date="2026-02-10",
            anthropic_client=mock_anthropic_client,
        )

        assert result.event_detected is True
        assert "Marie" in result.event.participants
        assert "Jean" in result.event.participants


# ============================================================================
# TEST CONFIDENCE < 0.70 (1 test)
# ============================================================================


class TestLowConfidence:
    """Test confidence en dessous du seuil."""

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_confidence_below_threshold(self, mock_anon, mock_anthropic_client):
        """Confidence <0.70 -> event_detected = False."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "peut-etre un truc demain"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        claude_response = {
            "event_detected": True,
            "title": "Truc",
            "start_datetime": "2026-02-11T09:00:00",
            "end_datetime": None,
            "location": None,
            "participants": [],
            "event_type": "other",
            "casquette": "personnel",
            "confidence": 0.55,
        }
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_response)
        )

        result = await extract_event_from_message(
            message="peut-etre un truc demain",
            current_date="2026-02-10",
            anthropic_client=mock_anthropic_client,
        )

        assert result.event_detected is False
        assert result.confidence < CONFIDENCE_THRESHOLD


# ============================================================================
# TEST CIRCUIT BREAKER (1 test)
# ============================================================================


class TestCircuitBreaker:
    """Test circuit breaker Claude API."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self):
        """Circuit breaker s'ouvre apres 3 echecs consecutifs (within timeout)."""
        import time

        import agents.src.agents.calendar.message_event_detector as mod

        # Sauvegarder etat original
        original_failures = mod._circuit_breaker_failures
        original_last_failure = mod._circuit_breaker_last_failure

        try:
            # Simuler circuit breaker ouvert avec timestamp recent
            mod._circuit_breaker_failures = 3
            mod._circuit_breaker_last_failure = time.time()  # Just now

            with pytest.raises(EventExtractionError, match="Circuit breaker ouvert"):
                await extract_event_from_message(
                    message="RDV demain 14h",
                    anthropic_client=AsyncMock(),
                )
        finally:
            # Restaurer etat original
            mod._circuit_breaker_failures = original_failures
            mod._circuit_breaker_last_failure = original_last_failure
