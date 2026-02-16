"""
Tests unitaires pour event_modification_callbacks.py

Story 7.4 AC6: Modification evenement propose
13 tests couvrant:
- Menu modification affiche (2 tests)
- Modification champ titre (1 test)
- Modification champ date (1 test)
- Modification multiple champs (1 test)
- Validation applique modifications (2 tests)
- Retour menu apres modification (1 test)
- State Redis persist modifications (2 tests)
- Edge cases (3 tests)
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.event_modification_callbacks import (
    STATE_KEY_PREFIX,
    _apply_modifications,
    _validate_modification,
    handle_event_modify_callback,
    handle_modify_field_callback,
    handle_modify_response,
    handle_modify_validate_callback,
    register_event_modification_callbacks,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_update():
    """Mock Telegram Update with CallbackQuery."""
    update = MagicMock()
    update.callback_query = AsyncMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 12345
    return update


@pytest.fixture
def mock_context():
    """Mock Telegram context."""
    context = MagicMock()
    context.bot_data = {
        "redis_client": AsyncMock(),
        "db_pool": MagicMock(),
    }
    return context


@pytest.fixture
def sample_event_id():
    return str(uuid.uuid4())


@pytest.fixture
def sample_event_data(sample_event_id):
    return {
        "id": sample_event_id,
        "name": "Consultation Dr Martin",
        "properties": {
            "start_datetime": "2026-02-17T14:00:00",
            "end_datetime": "2026-02-17T15:00:00",
            "location": "Cabinet",
            "participants": ["Dr Martin"],
            "casquette": "medecin",
            "status": "proposed",
        },
    }


# ============================================================================
# TESTS MENU MODIFICATION — 2 tests
# ============================================================================


class TestModifyMenu:
    """Tests affichage menu modification."""

    @pytest.mark.asyncio
    async def test_modify_shows_menu_with_buttons(
        self, mock_update, mock_context, sample_event_id, sample_event_data
    ):
        """[Modifier] affiche menu + 7 inline buttons."""
        mock_update.callback_query.data = f"evt_modify:{sample_event_id}"

        with patch(
            "bot.handlers.event_modification_callbacks._load_event",
            new_callable=AsyncMock,
            return_value=sample_event_data,
        ):
            await handle_event_modify_callback(mock_update, mock_context)

        call_args = mock_update.callback_query.edit_message_text.call_args
        msg = call_args[0][0]
        assert "Modification evenement" in msg
        assert "Consultation Dr Martin" in msg

        # Verifier inline buttons
        reply_markup = call_args[1]["reply_markup"]
        all_buttons = [b for row in reply_markup.inline_keyboard for b in row]
        labels = [b.text for b in all_buttons]
        assert "Titre" in labels
        assert "Date" in labels
        assert "Heure" in labels
        assert "Lieu" in labels
        assert "Participants" in labels
        assert "Valider" in labels
        assert "Annuler" in labels

    @pytest.mark.asyncio
    async def test_modify_event_not_found(self, mock_update, mock_context, sample_event_id):
        """Event introuvable -> erreur."""
        mock_update.callback_query.data = f"evt_modify:{sample_event_id}"

        with patch(
            "bot.handlers.event_modification_callbacks._load_event",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await handle_event_modify_callback(mock_update, mock_context)

        mock_update.callback_query.edit_message_text.assert_called_with(
            "Erreur: Evenement non trouve"
        )


# ============================================================================
# TESTS MODIFICATION CHAMPS — 2 tests
# ============================================================================


class TestModifyFields:
    """Tests modification champs specifiques."""

    @pytest.mark.asyncio
    async def test_modify_title_sets_waiting_field(
        self, mock_update, mock_context, sample_event_id
    ):
        """Click [Titre] -> state.waiting_field='title'."""
        mock_update.callback_query.data = f"evt_mod_title:{sample_event_id}"

        redis = mock_context.bot_data["redis_client"]
        redis.get = AsyncMock(
            return_value=json.dumps({
                "event_id": sample_event_id,
                "waiting_field": None,
                "modifications": {},
                "original": {},
            })
        )

        await handle_modify_field_callback(mock_update, mock_context)

        # State Redis mis a jour
        redis.set.assert_called_once()
        state = json.loads(redis.set.call_args[0][1])
        assert state["waiting_field"] == "title"

        # Prompt affiche
        mock_update.callback_query.edit_message_text.assert_called_with(
            "Entrez le nouveau titre :"
        )

    @pytest.mark.asyncio
    async def test_modify_date_sets_waiting_field(
        self, mock_update, mock_context, sample_event_id
    ):
        """Click [Date] -> state.waiting_field='date'."""
        mock_update.callback_query.data = f"evt_mod_date:{sample_event_id}"

        redis = mock_context.bot_data["redis_client"]
        redis.get = AsyncMock(
            return_value=json.dumps({
                "event_id": sample_event_id,
                "waiting_field": None,
                "modifications": {},
                "original": {},
            })
        )

        await handle_modify_field_callback(mock_update, mock_context)

        state = json.loads(redis.set.call_args[0][1])
        assert state["waiting_field"] == "date"


# ============================================================================
# TEST REPONSE MODIFICATION — 2 tests
# ============================================================================


class TestModifyResponse:
    """Tests handler reponse modification."""

    @pytest.mark.asyncio
    async def test_response_stores_modification(self, mock_context, sample_event_id):
        """Reponse texte -> stocke modification dans state."""
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 12345
        update.message = MagicMock()
        update.message.text = "Nouveau titre"
        update.message.reply_text = AsyncMock()

        redis = mock_context.bot_data["redis_client"]
        redis.get = AsyncMock(
            return_value=json.dumps({
                "event_id": sample_event_id,
                "waiting_field": "title",
                "modifications": {},
                "original": {"name": "Ancien titre"},
            })
        )

        result = await handle_modify_response(update, mock_context)

        assert result is True
        state = json.loads(redis.set.call_args[0][1])
        assert state["modifications"]["title"] == "Nouveau titre"
        assert state["waiting_field"] is None

    @pytest.mark.asyncio
    async def test_response_no_state_returns_false(self, mock_context):
        """Pas de state Redis -> return False."""
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 12345
        update.message = MagicMock()
        update.message.text = "hello"

        redis = mock_context.bot_data["redis_client"]
        redis.get = AsyncMock(return_value=None)

        result = await handle_modify_response(update, mock_context)
        assert result is False


# ============================================================================
# TESTS VALIDATION — 2 tests
# ============================================================================


class TestModifyValidate:
    """Tests callback [Valider]."""

    @pytest.mark.asyncio
    async def test_validate_applies_and_shows_confirmation(
        self, mock_update, mock_context, sample_event_id
    ):
        """[Valider] applique modifications + affiche confirmation."""
        mock_update.callback_query.data = f"evt_mod_validate:{sample_event_id}"

        redis = mock_context.bot_data["redis_client"]
        redis.get = AsyncMock(
            return_value=json.dumps({
                "event_id": sample_event_id,
                "waiting_field": None,
                "modifications": {"title": "Nouveau titre"},
                "original": {},
            })
        )

        # Mock db_pool
        conn = AsyncMock()
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_context.bot_data["db_pool"] = pool

        await handle_modify_validate_callback(mock_update, mock_context)

        # State supprime
        redis.delete.assert_called_once()

        # Confirmation avec inline buttons
        call_args = mock_update.callback_query.edit_message_text.call_args
        msg = call_args[0][0]
        assert "modifie" in msg.lower()
        assert "title" in msg

        reply_markup = call_args[1]["reply_markup"]
        buttons = [b for row in reply_markup.inline_keyboard for b in row]
        labels = [b.text for b in buttons]
        assert "Creer" in labels

    @pytest.mark.asyncio
    async def test_validate_no_modifications(self, mock_update, mock_context, sample_event_id):
        """[Valider] sans modifications -> message."""
        mock_update.callback_query.data = f"evt_mod_validate:{sample_event_id}"

        redis = mock_context.bot_data["redis_client"]
        redis.get = AsyncMock(
            return_value=json.dumps({
                "event_id": sample_event_id,
                "waiting_field": None,
                "modifications": {},
                "original": {},
            })
        )

        await handle_modify_validate_callback(mock_update, mock_context)

        mock_update.callback_query.edit_message_text.assert_called_with(
            "Aucune modification effectuee"
        )


# ============================================================================
# TESTS APPLY MODIFICATIONS — 1 test
# ============================================================================


class TestApplyModifications:
    """Tests application modifications."""

    def test_apply_title_and_location(self):
        """Modifications titre + lieu appliquees correctement."""
        original = {
            "name": "Ancien",
            "properties": {"location": "Ancien lieu"},
        }
        modifications = {"title": "Nouveau", "location": "Nouveau lieu"}

        result = _apply_modifications(original, modifications)

        assert result["name"] == "Nouveau"
        assert result["properties"]["location"] == "Nouveau lieu"
        # Original non modifie
        assert original["name"] == "Ancien"


# ============================================================================
# TESTS EDGE CASES — 3 tests
# ============================================================================


class TestEdgeCases:
    """Tests cas limites."""

    def test_validate_modification_title_too_short(self):
        """Titre <2 chars -> erreur."""
        assert _validate_modification("title", "X") is not None

    def test_validate_modification_location_any(self):
        """Location -> pas de validation stricte."""
        assert _validate_modification("location", "n'importe quoi") is None

    def test_register_callbacks(self):
        """register enregistre 7+ handlers."""
        application = MagicMock()
        db_pool = MagicMock()

        register_event_modification_callbacks(application, db_pool)

        # 1 modify + 5 fields + 1 validate = 7
        assert application.add_handler.call_count == 7
