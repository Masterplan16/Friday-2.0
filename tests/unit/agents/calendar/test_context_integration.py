"""
Tests integration ContextManager dans message_event_detector.py

Story 7.4 AC5: Influence contexte casquette via ContextManager (Story 7.3)
6 tests couvrant:
- Contexte=medecin via ContextManager -> bias medecin (1 test)
- Contexte=enseignant via ContextManager -> bias enseignant (1 test)
- Override contexte si mots-cles explicites (1 test)
- Contexte=null (ContextManager) -> pas de bias (1 test)
- ContextManager error -> fallback DB query (1 test)
- Logging trace contexte + casquette finale (1 test)
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.agents.calendar.message_event_detector import (
    extract_event_from_message,
)
from agents.src.core.models import Casquette


def _make_claude_response(event_data: dict) -> AsyncMock:
    """Helper to create mock Claude response."""
    mock_response = AsyncMock()
    mock_content = MagicMock()
    mock_content.text = json.dumps(event_data)
    mock_response.content = [mock_content]
    return mock_response


@pytest.fixture
def mock_anthropic_client():
    """Mock AsyncAnthropic client."""
    return AsyncMock()


@pytest.fixture
def mock_context_manager():
    """Mock ContextManager Story 7.3."""
    cm = AsyncMock()
    return cm


# ============================================================================
# TESTS CONTEXT MANAGER INTEGRATION — 6 tests
# ============================================================================


class TestContextManagerIntegration:
    """Tests integration ContextManager dans message extraction."""

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_context_medecin_from_context_manager(
        self, mock_anon, mock_anthropic_client, mock_context_manager
    ):
        """ContextManager retourne medecin -> bias medecin dans prompt."""
        # Setup anonymize
        anon_result = MagicMock()
        anon_result.anonymized_text = "RDV demain 14h"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        # Setup ContextManager retourne medecin
        user_context = MagicMock()
        user_context.casquette = Casquette.MEDECIN
        user_context.source = MagicMock()
        user_context.source.value = "manual"
        mock_context_manager.get_current_context = AsyncMock(return_value=user_context)

        # Claude responds with medecin
        claude_response = {
            "event_detected": True,
            "title": "Rendez-vous",
            "start_datetime": "2026-02-17T14:00:00",
            "end_datetime": "2026-02-17T15:00:00",
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
            current_date="2026-02-16",
            anthropic_client=mock_anthropic_client,
            context_manager=mock_context_manager,
        )

        assert result.event_detected is True
        assert result.event.casquette == Casquette.MEDECIN

        # ContextManager.get_current_context() appele
        mock_context_manager.get_current_context.assert_called_once()

        # Verify prompt includes casquette context
        call_args = mock_anthropic_client.messages.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "CONTEXTE ACTUEL" in prompt or "Médecin" in prompt

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_context_enseignant_from_context_manager(
        self, mock_anon, mock_anthropic_client, mock_context_manager
    ):
        """ContextManager retourne enseignant -> bias enseignant."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "Reunion demain 10h"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        user_context = MagicMock()
        user_context.casquette = Casquette.ENSEIGNANT
        user_context.source = MagicMock()
        user_context.source.value = "time_based"
        mock_context_manager.get_current_context = AsyncMock(return_value=user_context)

        claude_response = {
            "event_detected": True,
            "title": "Reunion",
            "start_datetime": "2026-02-17T10:00:00",
            "end_datetime": "2026-02-17T11:00:00",
            "location": None,
            "participants": [],
            "event_type": "meeting",
            "casquette": "enseignant",
            "confidence": 0.85,
        }
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_response)
        )

        result = await extract_event_from_message(
            message="Reunion demain 10h",
            current_date="2026-02-16",
            anthropic_client=mock_anthropic_client,
            context_manager=mock_context_manager,
        )

        assert result.event_detected is True
        assert result.event.casquette == Casquette.ENSEIGNANT

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_context_override_explicit_keywords(
        self, mock_anon, mock_anthropic_client, mock_context_manager
    ):
        """Contexte=medecin + mots-cles cours -> Claude override en enseignant."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "Cours L2 anatomie demain 14h"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        user_context = MagicMock()
        user_context.casquette = Casquette.MEDECIN
        user_context.source = MagicMock()
        user_context.source.value = "manual"
        mock_context_manager.get_current_context = AsyncMock(return_value=user_context)

        claude_response = {
            "event_detected": True,
            "title": "Cours L2 anatomie",
            "start_datetime": "2026-02-17T14:00:00",
            "end_datetime": "2026-02-17T16:00:00",
            "location": None,
            "participants": [],
            "event_type": "meeting",
            "casquette": "enseignant",
            "confidence": 0.92,
        }
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_response)
        )

        result = await extract_event_from_message(
            message="Cours L2 anatomie demain 14h",
            current_date="2026-02-16",
            anthropic_client=mock_anthropic_client,
            context_manager=mock_context_manager,
        )

        assert result.event_detected is True
        assert result.event.casquette == Casquette.ENSEIGNANT

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_context_null_no_bias(
        self, mock_anon, mock_anthropic_client, mock_context_manager
    ):
        """ContextManager retourne casquette=None -> pas de bias."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "RDV demain 14h"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        user_context = MagicMock()
        user_context.casquette = None
        user_context.source = MagicMock()
        user_context.source.value = "default"
        mock_context_manager.get_current_context = AsyncMock(return_value=user_context)

        claude_response = {
            "event_detected": True,
            "title": "Rendez-vous",
            "start_datetime": "2026-02-17T14:00:00",
            "end_datetime": None,
            "location": None,
            "participants": [],
            "event_type": "personal",
            "casquette": "personnel",
            "confidence": 0.80,
        }
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_response)
        )

        result = await extract_event_from_message(
            message="RDV demain 14h",
            current_date="2026-02-16",
            anthropic_client=mock_anthropic_client,
            context_manager=mock_context_manager,
        )

        assert result.event_detected is True
        # Pas de bias specifique - Claude decide
        assert result.event.casquette == Casquette.PERSONNEL

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    @patch("agents.src.agents.calendar.message_event_detector._fetch_current_casquette")
    async def test_context_manager_error_fallback_db(
        self, mock_fetch, mock_anon, mock_anthropic_client, mock_context_manager
    ):
        """ContextManager error -> fallback DB query."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "RDV demain 14h"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        # ContextManager raises exception
        mock_context_manager.get_current_context = AsyncMock(
            side_effect=Exception("Redis connection error")
        )

        # DB fallback retourne medecin
        mock_fetch.return_value = Casquette.MEDECIN

        claude_response = {
            "event_detected": True,
            "title": "Rendez-vous",
            "start_datetime": "2026-02-17T14:00:00",
            "end_datetime": None,
            "location": None,
            "participants": [],
            "event_type": "medical",
            "casquette": "medecin",
            "confidence": 0.88,
        }
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_response)
        )

        db_pool = AsyncMock()

        result = await extract_event_from_message(
            message="RDV demain 14h",
            current_date="2026-02-16",
            anthropic_client=mock_anthropic_client,
            context_manager=mock_context_manager,
            db_pool=db_pool,
        )

        assert result.event_detected is True
        # Fallback DB query appele
        mock_fetch.assert_called_once_with(db_pool)

    @pytest.mark.asyncio
    @patch("agents.src.agents.calendar.message_event_detector.anonymize_text")
    async def test_logging_traces_context_source(
        self, mock_anon, mock_anthropic_client, mock_context_manager
    ):
        """Logging trace casquette_input + casquette_output + context_source."""
        anon_result = MagicMock()
        anon_result.anonymized_text = "RDV demain 14h"
        anon_result.mapping = {}
        mock_anon.return_value = anon_result

        user_context = MagicMock()
        user_context.casquette = Casquette.CHERCHEUR
        user_context.source = MagicMock()
        user_context.source.value = "event_based"
        mock_context_manager.get_current_context = AsyncMock(return_value=user_context)

        claude_response = {
            "event_detected": True,
            "title": "Seminaire",
            "start_datetime": "2026-02-17T14:00:00",
            "end_datetime": None,
            "location": None,
            "participants": [],
            "event_type": "conference",
            "casquette": "chercheur",
            "confidence": 0.90,
        }
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_claude_response(claude_response)
        )

        with patch("agents.src.agents.calendar.message_event_detector.logger") as mock_logger:
            result = await extract_event_from_message(
                message="RDV demain 14h",
                current_date="2026-02-16",
                anthropic_client=mock_anthropic_client,
                context_manager=mock_context_manager,
            )

        assert result.event_detected is True

        # Verifier que le log contient casquette_input + context_source
        info_calls = [c for c in mock_logger.info.call_args_list if "terminee" in str(c)]
        assert len(info_calls) >= 1

        log_extra = info_calls[-1].kwargs.get("extra", {})
        assert log_extra.get("casquette_input") == "chercheur"
        assert log_extra.get("casquette_output") == "chercheur"
        assert log_extra.get("context_source") == "event_based"
