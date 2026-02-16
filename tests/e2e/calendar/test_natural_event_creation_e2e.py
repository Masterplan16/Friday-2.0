"""
Tests E2E pipeline creation evenements via message naturel Telegram

Story 7.4 AC7: Tests E2E pipeline complet
5 tests couvrant:
- E2E message naturel -> event propose -> confirmation (1 test)
- E2E detection conflit immediate apres creation (1 test)
- E2E commande /creer_event guidee -> event cree (1 test)
- E2E modification evenement propose -> re-proposal (1 test)
- E2E latence totale pipeline <10s (NFR) (1 test)

NOTE: Ces tests sont des E2E qui mockent les couches externes (Telegram, Google Calendar, PostgreSQL)
mais testent le pipeline complet bout-en-bout (extraction -> entite -> notification -> callback -> confirmation).
Tests avec vrais services necessitent infra deployee (marques @pytest.mark.e2e_infra).
"""

import json
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# FIXTURES E2E
# ============================================================================


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg pool avec async context manager correct."""
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.fixture
def mock_telegram_update():
    """Mock Telegram Update complet."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 12345
    update.message = MagicMock()
    update.message.text = ""
    update.message.reply_text = AsyncMock()
    update.message.message_id = 42
    return update


@pytest.fixture
def mock_telegram_context(mock_db_pool):
    """Mock Telegram context avec db_pool, redis, bot."""
    pool, conn = mock_db_pool
    context = MagicMock()
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()
    context.bot_data = {
        "db_pool": pool,
        "redis_client": AsyncMock(),
    }
    return context, pool, conn


@pytest.fixture
def sample_claude_response():
    """Reponse Claude extraction evenement."""
    return {
        "event_detected": True,
        "title": "Consultation Dr Martin",
        "start_datetime": "2026-02-17T14:00:00",
        "end_datetime": "2026-02-17T15:00:00",
        "location": "Cabinet medical",
        "participants": ["Dr Martin"],
        "event_type": "medical",
        "casquette": "medecin",
        "confidence": 0.88,
    }


def _make_claude_response(data: dict) -> AsyncMock:
    """Create mock Claude API response."""
    mock_response = AsyncMock()
    mock_content = MagicMock()
    mock_content.text = json.dumps(data)
    mock_response.content = [mock_content]
    return mock_response


# ============================================================================
# TEST E2E: MESSAGE NATUREL -> EVENT PROPOSE -> CONFIRMATION
# ============================================================================


class TestE2ENaturalMessagePipeline:
    """Test E2E pipeline complet message naturel."""

    @pytest.mark.asyncio
    @patch("bot.handlers.natural_event_creation.OWNER_USER_ID", 12345)
    @patch("bot.handlers.natural_event_creation.TELEGRAM_SUPERGROUP_ID", -100123)
    @patch("bot.handlers.natural_event_creation.TOPIC_ACTIONS_ID", 456)
    async def test_e2e_natural_message_to_event_confirmed(
        self, mock_telegram_update, mock_telegram_context, sample_claude_response
    ):
        """
        E2E: Message naturel -> extraction Claude -> entite EVENT proposed ->
        notification inline buttons -> callback [Creer] -> status confirmed
        """
        context, pool, conn = mock_telegram_context
        mock_telegram_update.message.text = "Ajoute consultation Dr Martin demain 14h"

        # Etape 1: Handler message naturel (extraction + notification)
        from bot.handlers.natural_event_creation import handle_natural_event_message

        event_id = str(uuid.uuid4())

        # Mock anonymization + Claude
        with (
            patch(
                "agents.src.agents.calendar.message_event_detector.anonymize_text"
            ) as mock_anon,
            patch(
                "agents.src.agents.calendar.message_event_detector.AsyncAnthropic"
            ) as mock_anthropic_cls,
        ):
            anon_result = MagicMock()
            anon_result.anonymized_text = "Ajoute consultation [PERSON_1] demain 14h"
            anon_result.mapping = {"[PERSON_1]": "Dr Martin"}
            mock_anon.return_value = anon_result

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_make_claude_response(sample_claude_response)
            )
            mock_anthropic_cls.return_value = mock_client

            # Mock entity creation returns UUID
            conn.fetchval = AsyncMock(return_value=uuid.UUID(event_id))

            with patch("os.getenv", side_effect=lambda k, d=None: {
                "ANTHROPIC_API_KEY": "test-key",
                "OWNER_USER_ID": "12345",
                "TELEGRAM_SUPERGROUP_ID": "-100123",
                "TOPIC_ACTIONS_ID": "456",
            }.get(k, d)):
                await handle_natural_event_message(mock_telegram_update, context)

        # Verifier notification envoyee avec inline buttons
        assert context.bot.send_message.called or mock_telegram_update.message.reply_text.called

        # Etape 2: Callback [Creer] -> confirme evenement
        from bot.handlers.event_creation_callbacks import handle_event_create_callback

        callback_update = MagicMock()
        callback_update.callback_query = AsyncMock()
        callback_update.callback_query.answer = AsyncMock()
        callback_update.callback_query.edit_message_text = AsyncMock()
        callback_update.callback_query.data = f"evt_create:{event_id}"

        with (
            patch(
                "bot.handlers.event_creation_callbacks._confirm_event",
                new_callable=AsyncMock,
                return_value={
                    "id": event_id,
                    "name": "Consultation Dr Martin",
                    "properties": {
                        "status": "confirmed",
                        "start_datetime": "2026-02-17T14:00:00",
                        "casquette": "medecin",
                    },
                },
            ),
            patch(
                "bot.handlers.event_creation_callbacks._sync_to_google_calendar",
                new_callable=AsyncMock,
                return_value="google_cal_123",
            ),
            patch(
                "bot.handlers.event_creation_callbacks._check_conflicts_immediate",
                new_callable=AsyncMock,
            ),
        ):
            await handle_event_create_callback(callback_update, context)

        # Verification finale: notification confirmation
        confirm_msg = callback_update.callback_query.edit_message_text.call_args[0][0]
        assert "Evenement cree" in confirm_msg
        assert "Consultation Dr Martin" in confirm_msg
        assert "Google Calendar synchronise" in confirm_msg


# ============================================================================
# TEST E2E: DETECTION CONFLIT IMMEDIATE
# ============================================================================


class TestE2EConflictDetection:
    """Test E2E detection conflit apres creation."""

    @pytest.mark.asyncio
    @patch("bot.handlers.event_creation_callbacks.TELEGRAM_SUPERGROUP_ID", -100123)
    @patch("bot.handlers.event_creation_callbacks.TOPIC_SYSTEM_ID", 789)
    async def test_e2e_conflict_detected_after_creation(
        self, mock_telegram_context
    ):
        """
        E2E: [Creer] -> confirm -> detect conflict -> alerte Topic System
        """
        context, pool, conn = mock_telegram_context

        event_id = str(uuid.uuid4())
        callback_update = MagicMock()
        callback_update.callback_query = AsyncMock()
        callback_update.callback_query.answer = AsyncMock()
        callback_update.callback_query.edit_message_text = AsyncMock()
        callback_update.callback_query.data = f"evt_create:{event_id}"

        # Mock conflit
        mock_conflict = MagicMock()
        mock_conflict.event1.title = "Consultation"
        mock_conflict.event2.title = "Cours L2"
        mock_conflict.overlap_minutes = 30

        from bot.handlers.event_creation_callbacks import handle_event_create_callback

        with (
            patch(
                "bot.handlers.event_creation_callbacks._confirm_event",
                new_callable=AsyncMock,
                return_value={
                    "id": event_id,
                    "name": "Consultation",
                    "properties": {
                        "start_datetime": "2026-02-17T14:00:00",
                        "casquette": "medecin",
                    },
                },
            ),
            patch(
                "bot.handlers.event_creation_callbacks._sync_to_google_calendar",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "agents.src.agents.calendar.conflict_detector.detect_calendar_conflicts",
                new_callable=AsyncMock,
                return_value=[mock_conflict],
            ),
        ):
            await handle_event_create_callback(callback_update, context)

        # Verifier alerte conflit envoyee au Topic System
        conflict_calls = [
            c for c in context.bot.send_message.call_args_list
            if c.kwargs.get("message_thread_id") == 789
        ]
        assert len(conflict_calls) >= 1
        assert "Conflit calendrier" in conflict_calls[0].kwargs["text"]


# ============================================================================
# TEST E2E: COMMANDE /creer_event GUIDEE
# ============================================================================


class TestE2EGuidedCreation:
    """Test E2E commande /creer_event guidee."""

    @pytest.mark.asyncio
    @patch("bot.handlers.create_event_command.OWNER_USER_ID", 12345)
    async def test_e2e_guided_command_full_flow(self, mock_telegram_update, mock_telegram_context):
        """
        E2E: /creer_event -> 6 etapes -> resume -> [Creer] -> confirmed
        """
        context, pool, conn = mock_telegram_context
        redis = context.bot_data["redis_client"]

        from bot.handlers.create_event_command import (
            handle_create_event_command,
            handle_create_event_step,
        )

        # Etape 0: Lancer commande
        await handle_create_event_command(mock_telegram_update, context)
        assert redis.set.called

        # Simuler flow 6 etapes
        steps_data = [
            ("Consultation Dr Martin", 1),  # titre
            ("17/02/2026", 2),              # date
            ("14:00", 3),                   # heure debut
            ("15:00", 4),                   # heure fin
            ("Cabinet medical", 5),         # lieu
            ("Dr Martin", 6),               # participants
        ]

        for step_input, step_num in steps_data:
            state = {"step": step_num, "data": {}}
            # Remplir data avec steps precedents
            if step_num > 1:
                state["data"]["title"] = "Consultation Dr Martin"
            if step_num > 2:
                state["data"]["date"] = "17/02/2026"
            if step_num > 3:
                state["data"]["start_time"] = "14:00"
            if step_num > 4:
                state["data"]["end_time"] = "15:00"
            if step_num > 5:
                state["data"]["location"] = "Cabinet medical"

            redis.get = AsyncMock(return_value=json.dumps(state))
            mock_telegram_update.message.text = step_input

            result = await handle_create_event_step(mock_telegram_update, context)
            assert result is True

        # Verifier resume envoye apres etape 6
        last_call = mock_telegram_update.message.reply_text.call_args
        msg = last_call[0][0]
        assert "Resume" in msg or "Consultation" in msg


# ============================================================================
# TEST E2E: MODIFICATION EVENEMENT
# ============================================================================


class TestE2EModification:
    """Test E2E modification evenement propose."""

    @pytest.mark.asyncio
    async def test_e2e_modify_title_and_validate(self, mock_telegram_context):
        """
        E2E: [Modifier] -> click [Titre] -> saisie -> [Valider]
        """
        context, pool, conn = mock_telegram_context
        redis = context.bot_data["redis_client"]
        event_id = str(uuid.uuid4())

        from bot.handlers.event_modification_callbacks import (
            handle_event_modify_callback,
            handle_modify_field_callback,
            handle_modify_response,
            handle_modify_validate_callback,
        )

        # Etape 1: [Modifier] -> menu
        update1 = MagicMock()
        update1.callback_query = AsyncMock()
        update1.callback_query.answer = AsyncMock()
        update1.callback_query.edit_message_text = AsyncMock()
        update1.callback_query.data = f"evt_modify:{event_id}"
        update1.effective_user = MagicMock()
        update1.effective_user.id = 12345

        with patch(
            "bot.handlers.event_modification_callbacks._load_event",
            new_callable=AsyncMock,
            return_value={
                "id": event_id,
                "name": "Consultation",
                "properties": {"start_datetime": "2026-02-17T14:00:00"},
            },
        ):
            await handle_event_modify_callback(update1, context)

        # Verifier menu affiche
        msg = update1.callback_query.edit_message_text.call_args[0][0]
        assert "Modification" in msg

        # Etape 2: Click [Titre]
        update2 = MagicMock()
        update2.callback_query = AsyncMock()
        update2.callback_query.answer = AsyncMock()
        update2.callback_query.edit_message_text = AsyncMock()
        update2.callback_query.data = f"evt_mod_title:{event_id}"
        update2.effective_user = MagicMock()
        update2.effective_user.id = 12345

        redis.get = AsyncMock(
            return_value=json.dumps({
                "event_id": event_id,
                "waiting_field": None,
                "modifications": {},
                "original": {"name": "Consultation"},
            })
        )
        await handle_modify_field_callback(update2, context)

        # Etape 3: Saisie nouveau titre
        update3 = MagicMock()
        update3.effective_user = MagicMock()
        update3.effective_user.id = 12345
        update3.message = MagicMock()
        update3.message.text = "Consultation Dr Dupont"
        update3.message.reply_text = AsyncMock()

        redis.get = AsyncMock(
            return_value=json.dumps({
                "event_id": event_id,
                "waiting_field": "title",
                "modifications": {},
                "original": {"name": "Consultation"},
            })
        )
        result = await handle_modify_response(update3, context)
        assert result is True

        # Etape 4: [Valider]
        update4 = MagicMock()
        update4.callback_query = AsyncMock()
        update4.callback_query.answer = AsyncMock()
        update4.callback_query.edit_message_text = AsyncMock()
        update4.callback_query.data = f"evt_mod_validate:{event_id}"
        update4.effective_user = MagicMock()
        update4.effective_user.id = 12345

        redis.get = AsyncMock(
            return_value=json.dumps({
                "event_id": event_id,
                "waiting_field": None,
                "modifications": {"title": "Consultation Dr Dupont"},
                "original": {"name": "Consultation"},
            })
        )

        await handle_modify_validate_callback(update4, context)

        # Verifier confirmation avec boutons
        msg = update4.callback_query.edit_message_text.call_args[0][0]
        assert "modifie" in msg.lower()


# ============================================================================
# TEST E2E: LATENCE PIPELINE <10s (NFR)
# ============================================================================


class TestE2EPerformance:
    """Test NFR latence pipeline."""

    @pytest.mark.asyncio
    async def test_e2e_pipeline_under_10s(self, mock_telegram_context):
        """
        NFR: Pipeline complet extraction -> notification doit etre <10s.
        (Avec mocks, devrait etre <1s)
        """
        context, pool, conn = mock_telegram_context

        start = time.time()

        # Simuler extraction
        from agents.src.agents.calendar.message_event_detector import (
            detect_event_intention,
            extract_event_from_message,
        )

        message = "Ajoute reunion demain 14h"
        assert detect_event_intention(message) is True

        claude_response = {
            "event_detected": True,
            "title": "Reunion",
            "start_datetime": "2026-02-17T14:00:00",
            "end_datetime": "2026-02-17T15:00:00",
            "location": None,
            "participants": [],
            "event_type": "meeting",
            "casquette": "enseignant",
            "confidence": 0.85,
        }

        with patch(
            "agents.src.agents.calendar.message_event_detector.anonymize_text"
        ) as mock_anon:
            anon_result = MagicMock()
            anon_result.anonymized_text = message
            anon_result.mapping = {}
            mock_anon.return_value = anon_result

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_make_claude_response(claude_response)
            )

            result = await extract_event_from_message(
                message=message,
                current_date="2026-02-16",
                anthropic_client=mock_client,
            )

        elapsed = time.time() - start
        assert result.event_detected is True
        assert elapsed < 10.0  # NFR: <10s total
        # Avec mocks, devrait etre beaucoup plus rapide
        assert elapsed < 2.0
