"""
Tests unitaires pour bot/handlers/callbacks.py (Story 1.10, Task 1 + Task 6).

Teste les handlers des boutons [Approve] et [Reject] pour les actions trust=propose.
"""

import os
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from telegram import CallbackQuery, Chat, Message, Update, User
from telegram.ext import ContextTypes

from bot.handlers.callbacks import CallbacksHandler, _cleanup_stale_attempts


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg Pool pour tests avec context managers imbriques.

    Pattern: pool.acquire() -> async context manager -> conn
             conn.transaction() -> async context manager
    """
    pool = MagicMock()
    conn = MagicMock()

    # acquire() returns sync, but __aenter__/__aexit__ are async
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    # transaction() returns sync, __aenter__/__aexit__ are async
    conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)

    conn.execute = AsyncMock(return_value="UPDATE 1")
    conn.fetchrow = AsyncMock(
        return_value={
            "id": "abc123-def4-5678-9012-345678901234",
            "status": "pending",
            "module": "email",
            "action_type": "classify",
            "input_summary": "Email de test@example.com",
            "output_summary": "medical (0.92)",
        }
    )
    return pool


@pytest.fixture
def owner_user_id():
    """Owner user ID pour tests."""
    return 12345


@pytest.fixture
def handler(mock_db_pool, owner_user_id):
    """Instance CallbacksHandler pour tests."""
    with patch.dict(os.environ, {"OWNER_USER_ID": str(owner_user_id)}):
        return CallbacksHandler(mock_db_pool)


@pytest.fixture
def handler_with_executor(mock_db_pool, owner_user_id):
    """Instance CallbacksHandler avec ActionExecutor mock."""
    mock_executor = AsyncMock()
    mock_executor.execute = AsyncMock(return_value=True)
    with patch.dict(os.environ, {"OWNER_USER_ID": str(owner_user_id)}):
        h = CallbacksHandler(mock_db_pool, action_executor=mock_executor)
    return h


def _make_callback_update(callback_data: str, user_id: int = 12345):
    """Helper pour creer un mock Update avec callback_query."""
    update = Mock(spec=Update)
    update.callback_query = Mock(spec=CallbackQuery)
    update.callback_query.answer = AsyncMock()
    update.callback_query.data = callback_data
    update.callback_query.from_user = Mock(spec=User)
    update.callback_query.from_user.id = user_id
    update.callback_query.message = Mock(spec=Message)
    update.callback_query.message.text = (
        "Action en attente de validation\n\n"
        "Module: email\nAction: classify\nConfidence: 0.92"
    )
    update.callback_query.message.chat = Mock(spec=Chat)
    update.callback_query.message.chat_id = -100123456
    update.callback_query.message.message_thread_id = 42
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Mock Context bot."""
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()
    return context


# =====================================================================
# Tests Approve Callback (AC2)
# =====================================================================


@pytest.mark.asyncio
async def test_approve_callback_updates_status(handler, mock_db_pool, mock_context):
    """
    Test AC2: Approve met a jour status='approved' + validated_by dans core.action_receipts.
    """
    update = _make_callback_update("approve_abc123-def4-5678-9012-345678901234")

    await handler.handle_approve_callback(update, mock_context)

    # Verifier SELECT FOR UPDATE (lock receipt)
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    select_call = conn.fetchrow.call_args
    assert "SELECT" in select_call[0][0]
    assert "FOR UPDATE" in select_call[0][0]
    assert select_call[0][1] == "abc123-def4-5678-9012-345678901234"

    # Verifier UPDATE status='approved' + validated_by (H4 fix)
    update_call = conn.execute.call_args
    assert "status = 'approved'" in update_call[0][0]
    assert "validated_by" in update_call[0][0]


@pytest.mark.asyncio
async def test_approve_callback_edits_message(handler, mock_db_pool, mock_context):
    """
    Test AC5: Approve remplace boutons par confirmation visuelle.
    """
    update = _make_callback_update("approve_abc123-def4-5678-9012-345678901234")

    await handler.handle_approve_callback(update, mock_context)

    # Verifier message edite avec confirmation
    update.callback_query.edit_message_reply_markup.assert_called_once_with(
        reply_markup=None
    )
    edit_call = update.callback_query.edit_message_text.call_args
    assert "Approuve" in edit_call[0][0]


@pytest.mark.asyncio
async def test_approve_callback_notifies_metrics(handler, mock_db_pool, mock_context):
    """
    Test AC2: Approve envoie notification dans topic Metrics & Logs.
    """
    update = _make_callback_update("approve_abc123-def4-5678-9012-345678901234")

    with patch.dict(
        os.environ,
        {
            "TOPIC_METRICS_ID": "99",
            "TELEGRAM_SUPERGROUP_ID": "-100123456",
            "OWNER_USER_ID": "12345",
        },
    ):
        handler._metrics_topic_id = 99
        handler._supergroup_id = -100123456
        await handler.handle_approve_callback(update, mock_context)

    # Verifier notification envoyee au topic Metrics
    context = mock_context
    context.bot.send_message.assert_called_once()
    send_call = context.bot.send_message.call_args
    assert send_call[1]["message_thread_id"] == 99
    assert "approuvee" in send_call[1]["text"].lower() or "approved" in send_call[1]["text"].lower()


@pytest.mark.asyncio
async def test_approve_callback_executes_action(handler_with_executor, mock_db_pool, mock_context):
    """
    Test C1 fix: Approve declenche l'execution via ActionExecutor.
    """
    update = _make_callback_update("approve_abc123-def4-5678-9012-345678901234")

    await handler_with_executor.handle_approve_callback(update, mock_context)

    # Verifier que ActionExecutor.execute() a ete appele
    handler_with_executor.action_executor.execute.assert_called_once_with(
        "abc123-def4-5678-9012-345678901234"
    )

    # Message doit indiquer "execute"
    edit_call = update.callback_query.edit_message_text.call_args
    assert "execute" in edit_call[0][0].lower()


# =====================================================================
# Tests Reject Callback (AC3)
# =====================================================================


@pytest.mark.asyncio
async def test_reject_callback_updates_status(handler, mock_db_pool, mock_context):
    """
    Test AC3: Reject met a jour status='rejected' + validated_by.
    """
    update = _make_callback_update("reject_abc123-def4-5678-9012-345678901234")

    await handler.handle_reject_callback(update, mock_context)

    # Verifier UPDATE status='rejected' + validated_by
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    update_call = conn.execute.call_args
    assert "status = 'rejected'" in update_call[0][0]
    assert "validated_by" in update_call[0][0]


@pytest.mark.asyncio
async def test_reject_callback_does_not_execute(handler, mock_db_pool, mock_context):
    """
    Test AC3: Reject N'execute PAS l'action.
    """
    update = _make_callback_update("reject_abc123-def4-5678-9012-345678901234")
    await handler.handle_reject_callback(update, mock_context)

    # Pas d'executor appele
    assert handler.action_executor is None


@pytest.mark.asyncio
async def test_reject_callback_edits_message(handler, mock_db_pool, mock_context):
    """
    Test AC5: Reject remplace boutons par confirmation visuelle.
    """
    update = _make_callback_update("reject_abc123-def4-5678-9012-345678901234")

    await handler.handle_reject_callback(update, mock_context)

    # Verifier message edite
    update.callback_query.edit_message_reply_markup.assert_called_once_with(
        reply_markup=None
    )
    edit_call = update.callback_query.edit_message_text.call_args
    assert "Rejete" in edit_call[0][0]


# =====================================================================
# Tests Double Click Prevention (AC5, BUG-1.10.2)
# =====================================================================


@pytest.mark.asyncio
async def test_double_click_prevention_already_approved(
    handler, mock_db_pool, mock_context
):
    """
    Test BUG-1.10.2: 2e clic sur bouton deja valide -> erreur gracieuse.
    """
    # Simuler receipt deja approuve
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = {
        "id": "abc123-def4-5678-9012-345678901234",
        "status": "approved",  # Deja approuve
        "module": "email",
        "action_type": "classify",
        "input_summary": "test",
        "output_summary": "test",
    }

    update = _make_callback_update("approve_abc123-def4-5678-9012-345678901234")
    await handler.handle_approve_callback(update, mock_context)

    # Pas d'UPDATE SQL (receipt deja valide)
    conn.execute.assert_not_called()

    # Callback answer avec message d'erreur
    update.callback_query.answer.assert_called()
    answer_call = update.callback_query.answer.call_args
    assert "approved" in answer_call[0][0].lower() or "deja" in answer_call[0][0].lower()


@pytest.mark.asyncio
async def test_double_click_prevention_already_rejected(
    handler, mock_db_pool, mock_context
):
    """
    Test: 2e clic reject sur action deja rejetee -> erreur gracieuse.
    """
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = {
        "id": "abc123",
        "status": "rejected",
        "module": "email",
        "action_type": "classify",
        "input_summary": "test",
        "output_summary": "test",
    }

    update = _make_callback_update("reject_abc123")
    await handler.handle_reject_callback(update, mock_context)

    conn.execute.assert_not_called()


# =====================================================================
# Tests Invalid Callback Data
# =====================================================================


@pytest.mark.asyncio
async def test_approve_callback_receipt_not_found(handler, mock_db_pool, mock_context):
    """
    Test: Receipt introuvable -> erreur gracieuse.
    """
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = None  # Receipt introuvable

    update = _make_callback_update("approve_nonexistent-receipt-id")
    await handler.handle_approve_callback(update, mock_context)

    # Pas d'UPDATE
    conn.execute.assert_not_called()

    # Message d'erreur
    update.callback_query.answer.assert_called()


# =====================================================================
# Tests Security: User ID Authorization (Task 6, BUG-1.10.4)
# =====================================================================


@pytest.mark.asyncio
async def test_callback_unauthorized_user_rejected(handler, mock_db_pool, mock_context):
    """
    Test BUG-1.10.4: User_id different de owner -> rejete.
    """
    update = _make_callback_update(
        "approve_abc123-def4-5678-9012-345678901234",
        user_id=99999,  # Pas le owner
    )

    await handler.handle_approve_callback(update, mock_context)

    # Aucun UPDATE SQL
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.assert_not_called()
    conn.execute.assert_not_called()

    # Callback answer with unauthorized message
    update.callback_query.answer.assert_called()
    answer_call = update.callback_query.answer.call_args
    assert answer_call[1].get("show_alert", False) is True


@pytest.mark.asyncio
async def test_callback_authorized_user_accepted(handler, mock_db_pool, mock_context):
    """
    Test: User_id = owner -> action acceptee.
    """
    update = _make_callback_update(
        "approve_abc123-def4-5678-9012-345678901234",
        user_id=12345,  # Owner
    )

    await handler.handle_approve_callback(update, mock_context)

    # UPDATE SQL execute (owner autorise)
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.execute.assert_called()


@pytest.mark.asyncio
async def test_reject_unauthorized_user_rejected(handler, mock_db_pool, mock_context):
    """
    Test BUG-1.10.4: User_id different de owner pour reject -> rejete.
    """
    update = _make_callback_update(
        "reject_abc123-def4-5678-9012-345678901234",
        user_id=88888,
    )

    await handler.handle_reject_callback(update, mock_context)

    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.assert_not_called()
    conn.execute.assert_not_called()


# =====================================================================
# Tests Callback on Expired Receipt (AC6)
# =====================================================================


@pytest.mark.asyncio
async def test_callback_on_expired_receipt(handler, mock_db_pool, mock_context):
    """
    Test AC6: Clic bouton expire -> erreur gracieuse.
    """
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = {
        "id": "abc123",
        "status": "expired",
        "module": "email",
        "action_type": "classify",
        "input_summary": "test",
        "output_summary": "test",
    }

    update = _make_callback_update("approve_abc123")
    await handler.handle_approve_callback(update, mock_context)

    conn.execute.assert_not_called()
    update.callback_query.answer.assert_called()


# =====================================================================
# Tests L1: Parsing defensif callback_data
# =====================================================================


def test_parse_receipt_id_valid():
    """Test L1: Parsing normal callback_data."""
    assert CallbacksHandler._parse_receipt_id("approve_abc-123") == "abc-123"
    assert CallbacksHandler._parse_receipt_id("reject_xyz") == "xyz"


def test_parse_receipt_id_invalid():
    """Test L1: Parsing invalide retourne None."""
    assert CallbacksHandler._parse_receipt_id("invalid") is None
    assert CallbacksHandler._parse_receipt_id("approve_") is None
    assert CallbacksHandler._parse_receipt_id("") is None
