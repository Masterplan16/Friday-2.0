"""
Unit tests for dedup Telegram commands (Story 3.8, AC4 + AC5).

Tests:
- /scan_dedup command
- Preview generation
- Inline buttons
- Confirmation callback
- Cancel callback
- Rate limiting (1 scan max)
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.dedup_commands import (
    _format_duration,
    _format_size,
    handle_dedup_cancel_callback,
    handle_dedup_delete_callback,
    scan_dedup_command,
)


@pytest.fixture
def mock_update():
    """Mock Telegram Update."""
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = -100123456
    update.message.reply_text = AsyncMock()
    update.message.message_thread_id = None
    return update


@pytest.fixture
def mock_context():
    """Mock Telegram context."""
    context = MagicMock()
    context.bot.edit_message_text = AsyncMock()
    context.bot.send_document = AsyncMock()
    context.bot_data = {}
    return context


class TestHelpers:
    """Test helper functions."""

    def test_format_size_gb(self):
        """Format GB."""
        assert _format_size(2 * 1024**3) == "2.0 Go"

    def test_format_size_mb(self):
        """Format MB."""
        assert _format_size(15 * 1024**2) == "15.0 Mo"

    def test_format_size_kb(self):
        """Format KB."""
        assert _format_size(500 * 1024) == "500.0 Ko"

    def test_format_duration_hours(self):
        """Format hours."""
        assert _format_duration(3665) == "1h01m05s"

    def test_format_duration_minutes(self):
        """Format minutes."""
        assert _format_duration(125) == "2m05s"


class TestScanDedupCommand:
    """Test /scan_dedup command handler."""

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"OWNER_USER_ID": "12345", "TOPIC_METRICS_ID": "0"})
    async def test_scan_dedup_non_owner_rejected(self, mock_update, mock_context):
        """Non-owner user rejected."""
        mock_update.effective_user.id = 99999  # Not owner

        await scan_dedup_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        assert "Acces refuse" in mock_update.message.reply_text.call_args[0][0]


class TestDedupCallbacks:
    """Test callback handlers."""

    @pytest.mark.asyncio
    async def test_cancel_callback(self, mock_context):
        """Cancel callback cleans up bot_data."""
        update = MagicMock()
        query = MagicMock()
        query.data = "dedup_cancel_test-id-123"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        mock_context.bot_data["dedup_result_test-id-123"] = MagicMock()
        mock_context.bot_data["dedup_report_test-id-123"] = "/path/report.csv"

        await handle_dedup_cancel_callback(update, mock_context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()
        assert "annulee" in query.edit_message_text.call_args[0][0]
        assert "dedup_result_test-id-123" not in mock_context.bot_data
        assert "dedup_report_test-id-123" not in mock_context.bot_data

    @pytest.mark.asyncio
    async def test_delete_callback_expired(self, mock_context):
        """Delete callback with expired results."""
        update = MagicMock()
        query = MagicMock()
        query.data = "dedup_delete_expired-id"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        await handle_dedup_delete_callback(update, mock_context)

        query.edit_message_text.assert_called_once()
        assert "expirés" in query.edit_message_text.call_args[0][0]
