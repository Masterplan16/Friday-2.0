"""Unit tests pour notifications Telegram Calendar Sync (Story 7.2 Task 6)."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from bot.handlers.event_notifications import (
    send_calendar_sync_success,
    send_calendar_modification_detected,
)


@pytest.fixture
def mock_bot():
    """Create mock Telegram Bot."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=Mock(message_id=123))
    return bot


@pytest.fixture
def sample_event_created():
    """Sample event data after Google Calendar creation."""
    return {
        "event_id": str(uuid4()),
        "title": "Consultation cardio",
        "start_datetime": "2026-02-17T14:00:00+01:00",
        "end_datetime": "2026-02-17T15:00:00+01:00",
        "casquette": "medecin",
        "location": "Cabinet médical",
        "html_link": "https://calendar.google.com/event?eid=abc123",
    }


@pytest.fixture
def sample_event_modification():
    """Sample event modification detected."""
    return {
        "event_id": str(uuid4()),
        "old_data": {
            "title": "Réunion pédagogique",
            "start_datetime": "2026-02-18T14:00:00+01:00",
            "end_datetime": "2026-02-18T15:00:00+01:00",
            "location": "Salle A",
        },
        "new_data": {
            "title": "Réunion pédagogique - URGENT",
            "start_datetime": "2026-02-18T15:00:00+01:00",  # Changed hour
            "end_datetime": "2026-02-18T16:00:00+01:00",
            "location": "Salle B",  # Changed location
        },
        "html_link": "https://calendar.google.com/event?eid=def456",
    }


class TestCalendarSyncNotifications:
    """Test suite for Google Calendar sync notifications."""

    @pytest.mark.asyncio
    async def test_send_calendar_sync_success(
        self, mock_bot, sample_event_created
    ):
        """Test notification création Google Calendar (Topic Actions)."""
        # Arrange
        supergroup_id = -1001234567890
        topic_actions_id = 123

        # Act
        result = await send_calendar_sync_success(
            bot=mock_bot,
            topic_id=topic_actions_id,
            supergroup_id=supergroup_id,
            event_data=sample_event_created,
        )

        # Assert
        assert result is True
        mock_bot.send_message.assert_called_once()

        call_kwargs = mock_bot.send_message.call_args[1]
        assert call_kwargs["chat_id"] == supergroup_id
        assert call_kwargs["message_thread_id"] == topic_actions_id
        assert call_kwargs["parse_mode"] == "HTML"

        # Verify message content
        message = call_kwargs["text"]
        assert "✅" in message or "Événement ajouté" in message
        assert "Google Calendar" in message
        assert sample_event_created["title"] in message
        assert sample_event_created["html_link"] in message

    @pytest.mark.asyncio
    async def test_send_calendar_modification_detected(
        self, mock_bot, sample_event_modification
    ):
        """Test notification modification détectée (Topic Email & Communications)."""
        # Arrange
        supergroup_id = -1001234567890
        topic_email_id = 456

        # Act
        result = await send_calendar_modification_detected(
            bot=mock_bot,
            topic_id=topic_email_id,
            supergroup_id=supergroup_id,
            modification_data=sample_event_modification,
        )

        # Assert
        assert result is True
        mock_bot.send_message.assert_called_once()

        call_kwargs = mock_bot.send_message.call_args[1]
        assert call_kwargs["chat_id"] == supergroup_id
        assert call_kwargs["message_thread_id"] == topic_email_id
        assert call_kwargs["parse_mode"] == "HTML"

        # Verify message content
        message = call_kwargs["text"]
        assert "🔄" in message or "modifié" in message
        assert "Google Calendar" in message

        # Verify diff is present (old vs new)
        old_title = sample_event_modification["old_data"]["title"]
        new_title = sample_event_modification["new_data"]["title"]
        assert old_title in message or new_title in message

        # Verify html_link is present
        assert sample_event_modification["html_link"] in message

    @pytest.mark.asyncio
    async def test_unicode_emojis_rendering(
        self, mock_bot, sample_event_created
    ):
        """Test Unicode emojis rendering correctement."""
        # Arrange
        # Add unicode emojis in event data
        sample_event_created["title"] = "Réunion 🎯 importante"
        sample_event_created["location"] = "Café ☕ du centre"

        supergroup_id = -1001234567890
        topic_id = 123

        # Act
        result = await send_calendar_sync_success(
            bot=mock_bot,
            topic_id=topic_id,
            supergroup_id=supergroup_id,
            event_data=sample_event_created,
        )

        # Assert
        assert result is True
        mock_bot.send_message.assert_called_once()

        # Verify emojis are present in message (not escaped/broken)
        message = mock_bot.send_message.call_args[1]["text"]
        assert "🎯" in message
        assert "☕" in message
        # Verify French accents
        assert "Réunion" in message
        assert "Café" in message

    @pytest.mark.asyncio
    async def test_notification_fails_gracefully_on_telegram_error(
        self, mock_bot, sample_event_created
    ):
        """Test notification échoue gracieusement si erreur Telegram."""
        # Arrange
        from telegram.error import TelegramError

        mock_bot.send_message.side_effect = TelegramError("Network error")

        # Act
        result = await send_calendar_sync_success(
            bot=mock_bot,
            topic_id=123,
            supergroup_id=-1001234567890,
            event_data=sample_event_created,
        )

        # Assert
        assert result is False  # Should return False on error, not raise exception
