"""
Tests Unitaires - Conflict Callbacks

Story 7.3: Multi-casquettes & Conflits Calendrier (AC6)

Tests :
- Annulation événement + sync Google Calendar
- Dialogue déplacement step-by-step
- Ignorer conflit
- Validation date/heure invalide
- Conflit résolu marqué DB
- Notification après résolution
- Trust Layer ActionResult
"""

import json
import os
from datetime import date, datetime, time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from bot.handlers.conflict_callbacks import (
    handle_conflict_button,
    handle_conflict_cancel,
    handle_conflict_ignore,
    handle_conflict_move,
    handle_move_date_response,
    handle_move_time_response,
)
from telegram import CallbackQuery, Chat, Message, Update, User
from telegram.ext import ContextTypes

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def set_owner_user_id():
    """Patch OWNER_USER_ID pour tous les tests (user.id = 123456789)."""
    with patch.dict(os.environ, {"OWNER_USER_ID": "123456789"}):
        yield


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg.Pool."""
    pool = MagicMock()
    conn = AsyncMock()
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = acquire_cm
    return pool, conn


@pytest.fixture
def mock_redis_client():
    """Mock redis.Redis."""
    redis = AsyncMock()
    return redis


@pytest.fixture
def mock_telegram_update():
    """Mock Telegram Update avec CallbackQuery."""
    update = MagicMock(spec=Update)
    query = MagicMock(spec=CallbackQuery)
    user = MagicMock(spec=User)

    user.id = 123456789
    user.first_name = "Antonio"

    query.from_user = user
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    update.callback_query = query

    return update


@pytest.fixture
def mock_telegram_message_update():
    """Mock Telegram Update avec Message (pour dialogue déplacement)."""
    update = MagicMock(spec=Update)
    message = MagicMock(spec=Message)
    user = MagicMock(spec=User)
    chat = MagicMock(spec=Chat)

    user.id = 123456789
    user.first_name = "Antonio"

    message.from_user = user
    message.chat = chat
    message.reply_text = AsyncMock()

    update.message = message

    return update


@pytest.fixture
def mock_context(mock_db_pool, mock_redis_client):
    """Mock ContextTypes.DEFAULT_TYPE."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    db_pool, conn = mock_db_pool

    context.bot_data = {
        "db_pool": db_pool,
        "redis_client": mock_redis_client,
        "google_calendar_sync": AsyncMock(),
    }

    return context


# ============================================================================
# Tests Annulation Événement (AC6)
# ============================================================================


@pytest.mark.asyncio
async def test_conflict_cancel_success(mock_telegram_update, mock_context, mock_db_pool):
    """Test AC6: Annulation événement via button [Annuler X]."""
    update = mock_telegram_update
    query = update.callback_query
    query.data = f"conflict:cancel:{uuid4()}"

    db_pool, conn = mock_db_pool

    # Mock DB responses
    conn.fetchrow = AsyncMock(
        return_value={
            "name": "Consultation Dr Dupont",
            "properties": {
                "google_event_id": "google_123",
                "casquette": "medecin",
                "start_datetime": "2026-02-17T14:30:00",
            },
        }
    )

    conn.execute = AsyncMock(return_value="UPDATE 1")

    # Mock Google Calendar sync
    sync_manager = mock_context.bot_data["google_calendar_sync"]
    sync_manager.delete_event_from_google = AsyncMock()

    # Mock Redis xadd
    redis_client = mock_context.bot_data["redis_client"]
    redis_client.xadd = AsyncMock()

    # Call handler
    await handle_conflict_button(update, mock_context)

    # Assertions: DB updated
    assert conn.execute.call_count >= 2  # UPDATE status + UPDATE conflicts
    query.edit_message_text.assert_called_once()

    message_text = query.edit_message_text.call_args[0][0]
    assert "✅" in message_text
    assert "Événement annulé" in message_text
    assert "Consultation Dr Dupont" in message_text

    # Assertions: Google Calendar deleted
    sync_manager.delete_event_from_google.assert_called_once_with(
        google_event_id="google_123", casquette="medecin"
    )

    # Assertions: Redis Streams published
    redis_client.xadd.assert_called_once()
    assert redis_client.xadd.call_args[0][0] == "calendar:conflict.resolved"


@pytest.mark.asyncio
async def test_conflict_cancel_event_not_found(mock_telegram_update, mock_context, mock_db_pool):
    """Test AC6: Annulation événement introuvable → erreur."""
    update = mock_telegram_update
    query = update.callback_query
    query.data = f"conflict:cancel:{uuid4()}"

    db_pool, conn = mock_db_pool
    conn.fetchrow = AsyncMock(return_value=None)

    await handle_conflict_button(update, mock_context)

    query.edit_message_text.assert_called_once()
    message_text = query.edit_message_text.call_args[0][0]
    assert "❌" in message_text
    assert "introuvable" in message_text


# ============================================================================
# Tests Déplacement Événement (AC6)
# ============================================================================


@pytest.mark.asyncio
async def test_conflict_move_step1_start_dialogue(mock_telegram_update, mock_context, mock_db_pool):
    """Test AC6: Déplacement step 1 → demande nouvelle date."""
    update = mock_telegram_update
    query = update.callback_query
    event_id = str(uuid4())
    query.data = f"conflict:move:{event_id}"

    db_pool, conn = mock_db_pool
    conn.fetchrow = AsyncMock(
        return_value={
            "name": "Cours L2 Anatomie",
            "properties": {"start_datetime": "2026-02-17T14:00:00"},
        }
    )

    redis_client = mock_context.bot_data["redis_client"]
    redis_client.set = AsyncMock()

    await handle_conflict_button(update, mock_context)

    # Assertions: État Redis créé
    redis_client.set.assert_called_once()
    state_key, state_json, ex = (
        redis_client.set.call_args[0][0],
        redis_client.set.call_args[0][1],
        redis_client.set.call_args[1]["ex"],
    )

    assert state_key == f"state:conflict:move:{query.from_user.id}"
    assert ex == 300  # TTL 5 minutes

    state = json.loads(state_json)
    assert state["event_id"] == event_id
    assert state["step"] == "waiting_date"
    assert state["event_name"] == "Cours L2 Anatomie"

    # Assertions: Message édité avec demande date
    query.edit_message_text.assert_called_once()
    message_text = query.edit_message_text.call_args[0][0]
    assert "📆" in message_text
    assert "Étape 1/2" in message_text
    assert "JJ/MM/AAAA" in message_text


@pytest.mark.asyncio
async def test_conflict_move_step2_validate_date(mock_telegram_message_update, mock_context):
    """Test AC6: Déplacement step 2 → validation date + demande heure."""
    update = mock_telegram_message_update
    message = update.message
    message.text = "20/02/2026"
    user_id = message.from_user.id

    redis_client = mock_context.bot_data["redis_client"]

    # Mock état Redis (step 1)
    state_key = f"state:conflict:move:{user_id}"
    state = {
        "event_id": str(uuid4()),
        "step": "waiting_date",
        "event_name": "Consultation Dr Dupont",
        "original_start": "2026-02-17T14:30:00",
    }
    redis_client.get = AsyncMock(return_value=json.dumps(state))
    redis_client.set = AsyncMock()

    # Call handler
    handled = await handle_move_date_response(update, mock_context)

    # Assertions: Message traité
    assert handled is True

    # Assertions: État Redis updated (step 2)
    redis_client.set.assert_called_once()
    new_state_json = redis_client.set.call_args[0][1]
    new_state = json.loads(new_state_json)

    assert new_state["step"] == "waiting_time"
    assert new_state["new_date"] == "20/02/2026"

    # Assertions: Message demande heure
    message.reply_text.assert_called_once()
    reply_text = message.reply_text.call_args[0][0]
    assert "✅" in reply_text
    assert "Date validée" in reply_text
    assert "Étape 2/2" in reply_text
    assert "HH:MM" in reply_text


@pytest.mark.asyncio
async def test_conflict_move_step2_invalid_date_format(mock_telegram_message_update, mock_context):
    """Test AC6: Validation date invalide (format incorrect) → erreur."""
    update = mock_telegram_message_update
    message = update.message
    message.text = "20-02-2026"  # Format incorrect (tirets au lieu de slashes)
    user_id = message.from_user.id

    redis_client = mock_context.bot_data["redis_client"]

    state_key = f"state:conflict:move:{user_id}"
    state = {
        "event_id": str(uuid4()),
        "step": "waiting_date",
        "event_name": "Consultation",
        "original_start": "2026-02-17T14:30:00",
    }
    redis_client.get = AsyncMock(return_value=json.dumps(state))

    handled = await handle_move_date_response(update, mock_context)

    assert handled is True

    # Assertions: Message erreur
    message.reply_text.assert_called_once()
    reply_text = message.reply_text.call_args[0][0]
    assert "❌" in reply_text
    assert "Date invalide" in reply_text
    assert "JJ/MM/AAAA" in reply_text


@pytest.mark.asyncio
async def test_conflict_move_step3_finalize(
    mock_telegram_message_update, mock_context, mock_db_pool
):
    """Test AC6: Déplacement step 3 → finalisation (UPDATE DB + PATCH Google)."""
    update = mock_telegram_message_update
    message = update.message
    message.text = "15:30"
    user_id = message.from_user.id

    event_id = str(uuid4())
    event_uuid = event_id

    redis_client = mock_context.bot_data["redis_client"]
    db_pool, conn = mock_db_pool

    # Mock état Redis (step 2)
    state_key = f"state:conflict:move:{user_id}"
    state = {
        "event_id": event_id,
        "step": "waiting_time",
        "new_date": "20/02/2026",
        "event_name": "Consultation Dr Dupont",
        "original_start": "2026-02-17T14:30:00",
    }
    redis_client.get = AsyncMock(return_value=json.dumps(state))
    redis_client.set = AsyncMock()
    redis_client.delete = AsyncMock()
    redis_client.xadd = AsyncMock()

    # Mock DB
    conn.fetchrow = AsyncMock(
        return_value={
            "name": "Consultation Dr Dupont",
            "properties": {
                "google_event_id": "google_123",
                "casquette": "medecin",
                "start_datetime": "2026-02-17T14:30:00",
                "end_datetime": "2026-02-17T15:30:00",
            },
        }
    )
    conn.execute = AsyncMock()

    # Mock Google Calendar sync
    sync_manager = mock_context.bot_data["google_calendar_sync"]
    sync_manager.update_event_in_google = AsyncMock()

    # Call handler
    handled = await handle_move_time_response(update, mock_context)

    # Assertions: Message traité
    assert handled is True

    # Assertions: DB updated
    assert conn.execute.call_count >= 2  # UPDATE event + UPDATE conflicts

    # Assertions: Google Calendar updated
    sync_manager.update_event_in_google.assert_called_once()

    # Assertions: Redis Streams published
    redis_client.xadd.assert_called_once()
    assert redis_client.xadd.call_args[0][0] == "calendar:conflict.resolved"

    # Assertions: État Redis supprimé
    redis_client.delete.assert_called_once_with(state_key)

    # Assertions: Message succès
    message.reply_text.assert_called_once()
    reply_text = message.reply_text.call_args[0][0]
    assert "✅" in reply_text
    assert "Événement déplacé avec succès" in reply_text
    assert "20/02/2026" in reply_text
    assert "15:30" in reply_text


@pytest.mark.asyncio
async def test_conflict_move_step3_invalid_time_format(mock_telegram_message_update, mock_context):
    """Test AC6: Validation heure invalide (format incorrect) → erreur."""
    update = mock_telegram_message_update
    message = update.message
    message.text = "15h30"  # Format incorrect (avec 'h')
    user_id = message.from_user.id

    redis_client = mock_context.bot_data["redis_client"]

    state_key = f"state:conflict:move:{user_id}"
    state = {
        "event_id": str(uuid4()),
        "step": "waiting_time",
        "new_date": "20/02/2026",
        "event_name": "Consultation",
        "original_start": "2026-02-17T14:30:00",
    }
    redis_client.get = AsyncMock(return_value=json.dumps(state))

    handled = await handle_move_time_response(update, mock_context)

    assert handled is True

    # Assertions: Message erreur
    message.reply_text.assert_called_once()
    reply_text = message.reply_text.call_args[0][0]
    assert "❌" in reply_text
    assert "Heure invalide" in reply_text
    assert "HH:MM" in reply_text


# ============================================================================
# Tests Ignorer Conflit (AC6)
# ============================================================================


@pytest.mark.asyncio
async def test_conflict_ignore_success(mock_telegram_update, mock_context, mock_db_pool):
    """Test AC6: Ignorer conflit via button [Ignorer conflit]."""
    update = mock_telegram_update
    query = update.callback_query
    conflict_id = str(uuid4())
    query.data = f"conflict:ignore:{conflict_id}"

    db_pool, conn = mock_db_pool
    conn.execute = AsyncMock(return_value="UPDATE 1")

    await handle_conflict_button(update, mock_context)

    # Assertions: DB updated (resolved=true)
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "resolved = true" in sql
    assert "resolution_action = 'ignore'" in sql

    # Assertions: Message succès
    query.edit_message_text.assert_called_once()
    message_text = query.edit_message_text.call_args[0][0]
    assert "✅" in message_text
    assert "Conflit ignoré" in message_text


@pytest.mark.asyncio
async def test_conflict_ignore_not_found(mock_telegram_update, mock_context, mock_db_pool):
    """Test AC6: Ignorer conflit introuvable → erreur."""
    update = mock_telegram_update
    query = update.callback_query
    conflict_id = str(uuid4())
    query.data = f"conflict:ignore:{conflict_id}"

    db_pool, conn = mock_db_pool
    conn.execute = AsyncMock(return_value="UPDATE 0")

    await handle_conflict_button(update, mock_context)

    query.edit_message_text.assert_called_once()
    message_text = query.edit_message_text.call_args[0][0]
    assert "❌" in message_text
    assert "introuvable" in message_text
