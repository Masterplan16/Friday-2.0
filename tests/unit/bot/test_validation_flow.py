"""
Tests unitaires pour le flow complet de validation inline buttons.

Story 1.10, Task 5.2: Tests du flow approve/reject/correct.
"""

import os
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from telegram import CallbackQuery, Message, Update, User
from telegram.ext import ContextTypes

from bot.action_executor import ActionExecutor
from bot.handlers.callbacks import CallbacksHandler
from services.metrics.expire_validations import expire_pending_validations


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg Pool pour tests."""
    pool = MagicMock()
    conn = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(
        return_value={
            "id": "test-receipt-001",
            "status": "pending",
            "module": "email",
            "action_type": "classify",
            "input_summary": "Email from test@example.com",
            "output_summary": "medical (0.92)",
            "payload": '{"action_func": "email.classify", "args": {}}',
        }
    )
    return pool


def _make_update(callback_data: str, user_id: int = 12345):
    """Helper pour creer Update mock."""
    update = Mock(spec=Update)
    update.callback_query = Mock(spec=CallbackQuery)
    update.callback_query.answer = AsyncMock()
    update.callback_query.data = callback_data
    update.callback_query.from_user = Mock(spec=User)
    update.callback_query.from_user.id = user_id
    update.callback_query.message = Mock(spec=Message)
    update.callback_query.message.text = "Test validation message"
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Mock Context."""
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()
    return context


# =====================================================================
# Flow Tests
# =====================================================================


@pytest.mark.asyncio
async def test_full_validation_flow_approve(mock_db_pool, mock_context):
    """
    Test flow complet: Action propose -> Approve -> Status approved.
    """
    with patch.dict(os.environ, {"OWNER_USER_ID": "12345"}):
        handler = CallbacksHandler(mock_db_pool)

    update = _make_update("approve_test-receipt-001")
    await handler.handle_approve_callback(update, mock_context)

    # Receipt doit etre mis a jour avec validated_by
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.execute.assert_called()
    sql = conn.execute.call_args[0][0]
    assert "validated_by" in sql

    # Message edite avec confirmation
    update.callback_query.edit_message_text.assert_called_once()
    text = update.callback_query.edit_message_text.call_args[0][0]
    assert "Approuve" in text


@pytest.mark.asyncio
async def test_full_validation_flow_reject(mock_db_pool, mock_context):
    """
    Test flow complet: Action propose -> Reject -> Status rejected, action NON executee.
    """
    with patch.dict(os.environ, {"OWNER_USER_ID": "12345"}):
        handler = CallbacksHandler(mock_db_pool)

    update = _make_update("reject_test-receipt-001")
    await handler.handle_reject_callback(update, mock_context)

    # Receipt doit etre rejete avec validated_by
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    update_call = conn.execute.call_args
    assert "rejected" in update_call[0][0]
    assert "validated_by" in update_call[0][0]

    # Message edite
    text = update.callback_query.edit_message_text.call_args[0][0]
    assert "Rejete" in text


@pytest.mark.asyncio
async def test_full_validation_flow_with_executor(mock_db_pool):
    """
    Test flow: Approve -> Execute action -> Status executed (H2 fix).
    """
    executor = ActionExecutor(mock_db_pool)

    # Simuler action approuvee
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = {
        "id": "test-receipt-001",
        "status": "approved",
        "module": "email",
        "action_type": "classify",
        "payload": '{"action_func": "email.classify", "args": {}}',
    }

    # Enregistrer une action mock
    mock_action = AsyncMock()
    executor.register_action("email.classify", mock_action)

    result = await executor.execute("test-receipt-001")
    assert result is True
    mock_action.assert_called_once()

    # H2 fix: Verifier status='executed' (pas 'auto')
    calls = conn.execute.call_args_list
    success_call = [c for c in calls if "status = 'executed'" in str(c)]
    assert len(success_call) > 0


@pytest.mark.asyncio
async def test_validation_timeout_expiration(mock_db_pool):
    """
    Test AC6: Receipts expires apres timeout configurable.
    """
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetch.return_value = [
        {
            "id": "expired-001",
            "module": "email",
            "action_type": "classify",
            "created_at": "2026-02-08T10:00:00",
        },
        {
            "id": "expired-002",
            "module": "archiviste",
            "action_type": "rename",
            "created_at": "2026-02-08T08:00:00",
        },
    ]

    count = await expire_pending_validations(mock_db_pool, timeout_hours=24)
    assert count == 2

    # SQL doit filtrer les pending depasses
    sql = conn.fetch.call_args[0][0]
    assert "status = 'expired'" in sql
    assert "status = 'pending'" in sql
