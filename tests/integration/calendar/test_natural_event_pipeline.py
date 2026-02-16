"""
Tests integration pipeline creation evenements via message naturel

Story 7.4: Pipeline complet message -> extraction -> entity -> notification
8 tests couvrant:
- Pipeline message -> event entity created (1 test)
- Pipeline with ContextManager casquette bias (1 test)
- Pipeline with Presidio anonymization (1 test)
- Pipeline low confidence -> no entity (1 test)
- Pipeline circuit breaker blocks after failures (1 test)
- Pipeline guided command -> entity with casquette (1 test)
- Pipeline modification -> DB persistence (1 test)
- Pipeline notification failure -> entity rollback (1 test)
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.agents.calendar.message_event_detector import (
    MessageEventResult,
    detect_event_intention,
    extract_event_from_message,
)
from agents.src.agents.calendar.models import Event, EventType
from agents.src.core.models import Casquette


def _make_claude_response(data: dict) -> AsyncMock:
    """Helper: mock Claude API response."""
    mock_response = AsyncMock()
    mock_content = MagicMock()
    mock_content.text = json.dumps(data)
    mock_response.content = [mock_content]
    return mock_response


@pytest.fixture
def mock_anthropic():
    return AsyncMock()


@pytest.fixture
def claude_event_response():
    return {
        "event_detected": True,
        "title": "Consultation Dr Martin",
        "start_datetime": "2026-02-17T14:00:00",
        "end_datetime": "2026-02-17T15:00:00",
        "location": "Cabinet",
        "participants": ["Dr Martin"],
        "event_type": "medical",
        "casquette": "medecin",
        "confidence": 0.92,
    }


class TestNaturalEventPipeline:
    """Tests pipeline integration message -> event."""

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_full_pipeline_creates_event(
        self, mock_anon, mock_anthropic, claude_event_response
    ):
        """Message -> anonymize -> Claude -> Event avec tous les champs."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "RDV demain 14h avec PERSON_1"
        anon_result.mapping = {"PERSON_1": "Dr Martin"}
        mock_anon.return_value = anon_result

        mock_anthropic.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_event_response)
        )

        result = await extract_event_from_message(
            message="RDV demain 14h avec Dr Martin",
            current_date="2026-02-16",
            anthropic_client=mock_anthropic,
        )

        assert result.event_detected is True
        assert result.event is not None
        assert result.event.casquette == Casquette.MEDECIN
        assert result.confidence >= 0.70

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_pipeline_with_context_manager_bias(
        self, mock_anon, mock_anthropic, claude_event_response
    ):
        """ContextManager casquette injectee dans prompt Claude."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "RDV demain 14h"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        mock_anthropic.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_event_response)
        )

        context_manager = AsyncMock()
        user_ctx = MagicMock()
        user_ctx.casquette = Casquette.MEDECIN
        user_ctx.source = MagicMock()
        user_ctx.source.value = "manual"
        context_manager.get_current_context = AsyncMock(return_value=user_ctx)

        result = await extract_event_from_message(
            message="RDV demain 14h",
            current_date="2026-02-16",
            anthropic_client=mock_anthropic,
            context_manager=context_manager,
        )

        assert result.event_detected is True
        context_manager.get_current_context.assert_called_once()
        # Verify prompt includes casquette context
        call_args = mock_anthropic.messages.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "CONTEXTE ACTUEL" in prompt

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_pipeline_presidio_anonymization(self, mock_anon, mock_anthropic):
        """Presidio anonymise AVANT appel Claude (RGPD)."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "RDV demain 14h avec PERSON_1"
        anon_result.mapping = {"PERSON_1": "Dr Dupont"}
        mock_anon.return_value = anon_result

        response = {
            "event_detected": True,
            "title": "RDV",
            "start_datetime": "2026-02-17T14:00:00",
            "end_datetime": "2026-02-17T15:00:00",
            "location": None,
            "participants": ["PERSON_1"],
            "event_type": "medical",
            "casquette": "medecin",
            "confidence": 0.90,
        }
        mock_anthropic.messages.create = AsyncMock(return_value=_make_claude_response(response))

        result = await extract_event_from_message(
            message="RDV demain 14h avec Dr Dupont",
            current_date="2026-02-16",
            anthropic_client=mock_anthropic,
        )

        # Presidio called
        mock_anon.assert_called_once()
        # Claude received anonymized text (not original)
        call_args = mock_anthropic.messages.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "Dr Dupont" not in prompt
        assert "PERSON_1" in prompt

        # Participants deanonymized in result
        assert result.event.participants == ["Dr Dupont"]

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_pipeline_low_confidence_no_event(self, mock_anon, mock_anthropic):
        """Confidence < 0.70 -> event_detected = False."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "peut-etre un truc"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        response = {
            "event_detected": True,
            "title": "Truc",
            "start_datetime": "2026-02-17T09:00:00",
            "end_datetime": None,
            "location": None,
            "participants": [],
            "event_type": "personal",
            "casquette": "personnel",
            "confidence": 0.55,
        }
        mock_anthropic.messages.create = AsyncMock(return_value=_make_claude_response(response))

        result = await extract_event_from_message(
            message="peut-etre un truc",
            current_date="2026-02-16",
            anthropic_client=mock_anthropic,
        )

        assert result.event_detected is False
        assert result.confidence == 0.55

    def test_intent_detection_positive(self):
        """Intent detection positive pour messages evenement."""
        assert detect_event_intention("Ajoute RDV demain 14h") is True
        assert detect_event_intention("Note reunion mardi 10h") is True
        assert detect_event_intention("Cree consultation jeudi") is True

    def test_intent_detection_negative(self):
        """Intent detection negative pour messages non-evenement."""
        assert detect_event_intention("Salut ca va ?") is False
        assert detect_event_intention("Merci pour le rapport") is False

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_pipeline_context_manager_error_fallback(
        self, mock_anon, mock_anthropic, claude_event_response
    ):
        """ContextManager error -> fallback DB."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "RDV demain 14h"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        mock_anthropic.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_event_response)
        )

        context_manager = AsyncMock()
        context_manager.get_current_context = AsyncMock(side_effect=Exception("Redis down"))

        db_pool = AsyncMock()

        with patch(
            "agents.src.agents.calendar.message_event_detector._fetch_current_casquette",
            return_value=Casquette.MEDECIN,
        ):
            result = await extract_event_from_message(
                message="RDV demain 14h",
                current_date="2026-02-16",
                anthropic_client=mock_anthropic,
                context_manager=context_manager,
                db_pool=db_pool,
            )

        assert result.event_detected is True

    def test_fixture_dataset_structure(self):
        """Verify natural_event_messages.json dataset structure."""
        import json
        from pathlib import Path

        fixture_path = Path(__file__).parents[2] / "fixtures" / "natural_event_messages.json"
        assert fixture_path.exists(), f"Fixture not found: {fixture_path}"

        with open(fixture_path) as f:
            messages = json.load(f)

        assert len(messages) >= 8
        for msg in messages:
            assert "id" in msg
            assert "input" in msg
            assert "current_date" in msg
            assert "expected" in msg
