"""
Tests unitaires pour create_event_command.py

Story 7.4 AC4: Commande /creer_event guidee en 6 etapes
16 tests couvrant:
- Flow complet 6 etapes (2 tests)
- Validation date (3 tests)
- Validation heure (3 tests)
- Skip optionnel avec "." (1 test)
- Resume apres etape 6 (1 test)
- Inline buttons resume (1 test)
- Timeout state Redis (1 test)
- State Redis cree/modifie (2 tests)
- Edge cases (2 tests)
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.create_event_command import (
    STATE_KEY_PREFIX,
    STATE_TTL,
    STEPS,
    _build_datetime,
    _validate_date,
    _validate_step_input,
    _validate_time,
    handle_create_event_command,
    handle_create_event_step,
    handle_restart_callback,
    register_create_event_command,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_update():
    """Mock Telegram Update."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 12345
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.text = ""
    return update


@pytest.fixture
def mock_context():
    """Mock Telegram context avec redis_client et db_pool."""
    context = MagicMock()
    context.bot_data = {
        "redis_client": AsyncMock(),
        "db_pool": AsyncMock(),
    }
    return context


@pytest.fixture
def mock_redis(mock_context):
    """Raccourci vers redis_client mock."""
    return mock_context.bot_data["redis_client"]


# ============================================================================
# TESTS FLOW COMPLET — 2 tests
# ============================================================================


class TestCreateEventCommand:
    """Tests lancement commande /creer_event."""

    @pytest.mark.asyncio
    @patch("bot.handlers.create_event_command.OWNER_USER_ID", 12345)
    async def test_command_starts_dialog(self, mock_update, mock_context, mock_redis):
        """Commande cree state Redis step 1 + envoie question."""
        await handle_create_event_command(mock_update, mock_context)

        # State Redis cree
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        key = call_args[0][0]
        assert key == f"{STATE_KEY_PREFIX}:12345"

        state = json.loads(call_args[0][1])
        assert state["step"] == 1
        assert state["data"] == {}

        # TTL 10 min
        assert call_args[1]["ex"] == STATE_TTL

        # Message envoye
        msg = mock_update.message.reply_text.call_args[0][0]
        assert "Etape 1/6" in msg
        assert "titre" in msg.lower()

    @pytest.mark.asyncio
    @patch("bot.handlers.create_event_command.OWNER_USER_ID", 12345)
    async def test_command_ignored_non_owner(self, mock_update, mock_context, mock_redis):
        """Non-owner -> commande ignoree."""
        mock_update.effective_user.id = 99999

        await handle_create_event_command(mock_update, mock_context)

        mock_redis.set.assert_not_called()
        mock_update.message.reply_text.assert_not_called()


# ============================================================================
# TESTS STEP HANDLER — 2 tests
# ============================================================================


class TestCreateEventStep:
    """Tests handler etapes dialogue."""

    @pytest.mark.asyncio
    async def test_step_advances_to_next(self, mock_update, mock_context, mock_redis):
        """Reponse valide step 1 -> avance step 2."""
        # State actuel : step 1
        state = {"step": 1, "data": {}}
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        mock_update.message.text = "Consultation Dr Martin"

        result = await handle_create_event_step(mock_update, mock_context)

        assert result is True
        # State mis a jour
        mock_redis.set.assert_called_once()
        new_state = json.loads(mock_redis.set.call_args[0][1])
        assert new_state["step"] == 2
        assert new_state["data"]["title"] == "Consultation Dr Martin"

        # Question step 2 envoyee
        msg = mock_update.message.reply_text.call_args[0][0]
        assert "Etape 2/6" in msg

    @pytest.mark.asyncio
    async def test_step_returns_false_no_state(self, mock_update, mock_context, mock_redis):
        """Pas de state Redis -> return False (pas de dialogue actif)."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_update.message.text = "hello"

        result = await handle_create_event_step(mock_update, mock_context)

        assert result is False


# ============================================================================
# TESTS VALIDATION DATE — 3 tests
# ============================================================================


class TestValidateDate:
    """Tests validation format date."""

    def test_valid_date_full_format(self):
        """JJ/MM/AAAA valide."""
        assert _validate_date("17/02/2026") is None

    def test_valid_date_short_format(self):
        """JJ/MM valide (annee courante)."""
        assert _validate_date("17/02") is None

    def test_invalid_date(self):
        """Date invalide -> message erreur."""
        result = _validate_date("32/13/2026")
        assert result is not None
        assert "invalide" in result.lower() or "format" in result.lower()

    def test_invalid_date_format(self):
        """Format non reconnu."""
        result = _validate_date("demain")
        assert result is not None
        assert "format" in result.lower()


# ============================================================================
# TESTS VALIDATION HEURE — 3 tests
# ============================================================================


class TestValidateTime:
    """Tests validation format heure."""

    def test_valid_time_colon(self):
        """HH:MM valide."""
        assert _validate_time("14:30") is None

    def test_valid_time_h_format(self):
        """HHhMM valide."""
        assert _validate_time("14h30") is None

    def test_invalid_time(self):
        """Heure invalide -> message erreur."""
        result = _validate_time("25:00")
        assert result is not None
        assert "invalide" in result.lower() or "format" in result.lower()


# ============================================================================
# TEST SKIP OPTIONNEL — 1 test
# ============================================================================


class TestSkipOptional:
    """Tests champs optionnels skippes avec '.'."""

    @pytest.mark.asyncio
    async def test_skip_optional_with_dot(self, mock_update, mock_context, mock_redis):
        """'.' sur champ optionnel -> skip et avance."""
        # State : step 4 (end_time = optionnel)
        state = {"step": 4, "data": {"title": "RDV", "date": "17/02", "start_time": "14:00"}}
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        mock_update.message.text = "."

        result = await handle_create_event_step(mock_update, mock_context)

        assert result is True
        new_state = json.loads(mock_redis.set.call_args[0][1])
        assert new_state["step"] == 5
        assert new_state["data"]["end_time"] is None


# ============================================================================
# TESTS RESUME — 2 tests
# ============================================================================


class TestEventSummary:
    """Tests resume apres etape 6."""

    @pytest.mark.asyncio
    async def test_summary_sent_after_step_6(self, mock_update, mock_context, mock_redis):
        """Apres step 6 -> resume avec inline buttons."""
        state = {
            "step": 6,
            "data": {
                "title": "Consultation",
                "date": "17/02/2026",
                "start_time": "14:00",
                "end_time": "15:00",
                "location": "Cabinet",
            },
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        mock_update.message.text = "Dr Martin"

        # Mock db_pool pour creation entite
        conn = AsyncMock()
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_context.bot_data["db_pool"] = pool

        result = await handle_create_event_step(mock_update, mock_context)

        assert result is True
        # State Redis supprime
        mock_redis.delete.assert_called_once()

        # Resume envoye avec inline buttons
        call_args = mock_update.message.reply_text.call_args
        msg = call_args[0][0]
        assert "Resume" in msg
        assert "Consultation" in msg

        # Inline buttons
        reply_markup = call_args[1]["reply_markup"]
        buttons = reply_markup.inline_keyboard[0]
        labels = [b.text for b in buttons]
        assert "Creer" in labels
        assert "Recommencer" in labels
        assert "Annuler" in labels

    @pytest.mark.asyncio
    async def test_summary_includes_all_fields(self, mock_update, mock_context, mock_redis):
        """Resume inclut tous les champs remplis."""
        state = {
            "step": 6,
            "data": {
                "title": "Reunion",
                "date": "20/02/2026",
                "start_time": "10:00",
                "end_time": "11:00",
                "location": "Salle A",
            },
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        mock_update.message.text = "Alice, Bob"

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_context.bot_data["db_pool"] = pool

        await handle_create_event_step(mock_update, mock_context)

        msg = mock_update.message.reply_text.call_args[0][0]
        assert "Reunion" in msg
        assert "Salle A" in msg
        assert "Alice, Bob" in msg


# ============================================================================
# TEST BUILD DATETIME — 1 test
# ============================================================================


class TestBuildDatetime:
    """Tests construction datetime."""

    def test_build_datetime_full(self):
        """date + time -> datetime correct."""
        result = _build_datetime("17/02/2026", "14:30")
        assert result is not None
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 17
        assert result.hour == 14
        assert result.minute == 30

    def test_build_datetime_h_format(self):
        """Format HHhMM."""
        result = _build_datetime("17/02/2026", "14h30")
        assert result is not None
        assert result.hour == 14
        assert result.minute == 30

    def test_build_datetime_invalid(self):
        """Inputs invalides -> None."""
        assert _build_datetime("", "14:00") is None
        assert _build_datetime("17/02/2026", None) is None


# ============================================================================
# TESTS EDGE CASES — 2 tests
# ============================================================================


class TestEdgeCases:
    """Tests cas limites."""

    @pytest.mark.asyncio
    async def test_no_redis_returns_error(self, mock_update, mock_context):
        """Pas de redis_client -> message erreur."""
        mock_context.bot_data = {}

        with patch("bot.handlers.create_event_command.OWNER_USER_ID", 12345):
            await handle_create_event_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_with("Erreur: Redis non disponible")

    @pytest.mark.asyncio
    async def test_register_command(self):
        """register_create_event_command enregistre 2 handlers."""
        application = MagicMock()
        db_pool = MagicMock()

        register_create_event_command(application, db_pool)

        assert application.add_handler.call_count == 2

    @pytest.mark.asyncio
    async def test_restart_callback(self):
        """Callback [Recommencer] reinitialise state."""
        update = MagicMock()
        update.callback_query = AsyncMock()
        update.callback_query.data = "evt_restart"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 12345

        context = MagicMock()
        redis_client = AsyncMock()
        context.bot_data = {"redis_client": redis_client}

        await handle_restart_callback(update, context)

        # State Redis reinitialise
        redis_client.set.assert_called_once()
        state = json.loads(redis_client.set.call_args[0][1])
        assert state["step"] == 1
        assert state["data"] == {}

        # Message step 1
        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Etape 1/6" in msg


class TestValidateStepInput:
    """Tests validation generique."""

    def test_title_too_short(self):
        """Titre < 2 chars -> erreur."""
        result = _validate_step_input("title", "X")
        assert result is not None

    def test_title_valid(self):
        """Titre valide."""
        assert _validate_step_input("title", "Consultation") is None

    def test_date_valid(self):
        """Date valide via step input."""
        assert _validate_step_input("date", "17/02/2026") is None

    def test_skip_dot_on_required_field_rejected(self):
        """'.' sur titre (requis) -> validation normale."""
        result = _validate_step_input("title", ".")
        assert result is not None  # Too short
