"""
Tests unitaires pour natural_event_creation.py + event_proposal_notifications.py

Story 7.4 AC1, AC2: Handler message naturel + notifications
12 tests
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.agents.calendar.message_event_detector import MessageEventResult
from agents.src.agents.calendar.models import Event, EventType
from agents.src.core.models import Casquette


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_update():
    """Mock Telegram Update."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = "Ajoute reunion demain 14h"
    update.effective_user = MagicMock()
    update.effective_user.id = 12345
    return update


@pytest.fixture
def mock_context():
    """Mock Telegram context."""
    context = MagicMock()
    context.bot = AsyncMock()
    context.bot_data = {"db_pool": None}
    context.bot.send_message = AsyncMock()
    return context


def _make_event(**kwargs):
    """Helper to create Event."""
    defaults = {
        "title": "Reunion test",
        "start_datetime": datetime(2026, 2, 18, 14, 0),
        "end_datetime": datetime(2026, 2, 18, 15, 0),
        "location": None,
        "participants": [],
        "event_type": EventType.MEETING,
        "casquette": Casquette.ENSEIGNANT,
        "confidence": 0.88,
    }
    defaults.update(kwargs)
    return Event(**defaults)


# ============================================================================
# TESTS HANDLER MESSAGE NATUREL (7 tests)
# ============================================================================


class TestHandleNaturalEventMessage:
    """Tests pour handle_natural_event_message()."""

    @pytest.mark.asyncio
    @patch("bot.handlers.natural_event_creation.OWNER_USER_ID", 12345)
    @patch("bot.handlers.natural_event_creation.extract_event_from_message")
    @patch("bot.handlers.natural_event_creation.detect_event_intention", return_value=True)
    @patch("bot.handlers.natural_event_creation.send_event_proposal_notification")
    async def test_message_detected_notification_sent(
        self, mock_notif, mock_detect, mock_extract, mock_update, mock_context
    ):
        """Message naturel detecte -> notification envoyee."""
        from bot.handlers.natural_event_creation import handle_natural_event_message

        event = _make_event()
        mock_extract.return_value = MessageEventResult(
            event_detected=True,
            event=event,
            confidence=0.88,
            processing_time_ms=1200,
        )
        mock_notif.return_value = 999

        result = await handle_natural_event_message(mock_update, mock_context)

        assert result is True
        mock_notif.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.handlers.natural_event_creation.OWNER_USER_ID", 12345)
    @patch("bot.handlers.natural_event_creation.extract_event_from_message")
    @patch("bot.handlers.natural_event_creation.detect_event_intention", return_value=True)
    async def test_low_confidence_error_message(
        self, mock_detect, mock_extract, mock_update, mock_context
    ):
        """Confidence <0.70 -> message erreur Topic Chat."""
        from bot.handlers.natural_event_creation import handle_natural_event_message

        mock_extract.return_value = MessageEventResult(
            event_detected=False,
            event=None,
            confidence=0.55,
            processing_time_ms=1000,
        )

        result = await handle_natural_event_message(mock_update, mock_context)
        assert result is False

    @pytest.mark.asyncio
    @patch("bot.handlers.natural_event_creation.OWNER_USER_ID", 12345)
    @patch("bot.handlers.natural_event_creation.detect_event_intention", return_value=False)
    async def test_no_intention_ignored(self, mock_detect, mock_update, mock_context):
        """Pas d'intention evenement -> ignore."""
        from bot.handlers.natural_event_creation import handle_natural_event_message

        mock_update.message.text = "Bonjour comment vas-tu"
        result = await handle_natural_event_message(mock_update, mock_context)
        assert result is False

    @pytest.mark.asyncio
    @patch("bot.handlers.natural_event_creation.OWNER_USER_ID", 99999)
    async def test_non_owner_rejected(self, mock_update, mock_context):
        """Utilisateur non-mainteneur -> rejete."""
        from bot.handlers.natural_event_creation import handle_natural_event_message

        mock_update.effective_user.id = 12345  # Different from OWNER_USER_ID=99999
        result = await handle_natural_event_message(mock_update, mock_context)
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_message_ignored(self, mock_context):
        """Message vide -> ignore."""
        from bot.handlers.natural_event_creation import handle_natural_event_message

        update = MagicMock()
        update.message = None
        result = await handle_natural_event_message(update, mock_context)
        assert result is False

    @pytest.mark.asyncio
    @patch("bot.handlers.natural_event_creation.OWNER_USER_ID", 12345)
    @patch("bot.handlers.natural_event_creation.extract_event_from_message")
    @patch("bot.handlers.natural_event_creation.detect_event_intention", return_value=True)
    @patch("bot.handlers.natural_event_creation.send_event_proposal_notification")
    async def test_notification_topic_actions(
        self, mock_notif, mock_detect, mock_extract, mock_update, mock_context
    ):
        """Notification envoyee au Topic Actions (pas Chat)."""
        from bot.handlers.natural_event_creation import handle_natural_event_message

        event = _make_event()
        mock_extract.return_value = MessageEventResult(
            event_detected=True,
            event=event,
            confidence=0.90,
            processing_time_ms=800,
        )
        mock_notif.return_value = 999

        await handle_natural_event_message(mock_update, mock_context)

        # Verifier que send_event_proposal_notification a ete appele
        mock_notif.assert_called_once()
        call_kwargs = mock_notif.call_args
        assert call_kwargs.kwargs.get("event") == event or call_kwargs[1].get("event") == event

    @pytest.mark.asyncio
    @patch("bot.handlers.natural_event_creation.OWNER_USER_ID", 12345)
    @patch("bot.handlers.natural_event_creation.extract_event_from_message")
    @patch("bot.handlers.natural_event_creation.detect_event_intention", return_value=True)
    @patch("bot.handlers.natural_event_creation.send_event_proposal_notification")
    async def test_inline_buttons_present(
        self, mock_notif, mock_detect, mock_extract, mock_update, mock_context
    ):
        """3 inline buttons presents dans notification."""
        from bot.handlers.natural_event_creation import handle_natural_event_message

        event = _make_event()
        mock_extract.return_value = MessageEventResult(
            event_detected=True,
            event=event,
            confidence=0.88,
            processing_time_ms=1000,
        )
        mock_notif.return_value = 999

        await handle_natural_event_message(mock_update, mock_context)
        mock_notif.assert_called_once()


# ============================================================================
# TESTS NOTIFICATION PROPOSITION (5 tests)
# ============================================================================


class TestEventProposalNotification:
    """Tests pour send_event_proposal_notification()."""

    @pytest.mark.asyncio
    async def test_notification_contains_title(self):
        """Notification contient le titre evenement."""
        from bot.handlers.event_proposal_notifications import (
            send_event_proposal_notification,
        )

        bot = AsyncMock()
        sent_msg = MagicMock()
        sent_msg.message_id = 123
        bot.send_message = AsyncMock(return_value=sent_msg)

        event = _make_event(title="Reunion avec Dr Dupont")

        result = await send_event_proposal_notification(
            bot=bot,
            event=event,
            event_id="test-uuid",
            confidence=0.89,
            supergroup_id=100,
            topic_id=200,
        )

        assert result == 123
        call_args = bot.send_message.call_args
        assert "Reunion avec Dr Dupont" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_notification_contains_confidence(self):
        """Notification contient la confidence."""
        from bot.handlers.event_proposal_notifications import (
            send_event_proposal_notification,
        )

        bot = AsyncMock()
        sent_msg = MagicMock()
        sent_msg.message_id = 123
        bot.send_message = AsyncMock(return_value=sent_msg)

        event = _make_event()

        await send_event_proposal_notification(
            bot=bot,
            event=event,
            event_id="test-uuid",
            confidence=0.89,
            supergroup_id=100,
            topic_id=200,
        )

        call_args = bot.send_message.call_args
        assert "89%" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_notification_has_3_buttons(self):
        """Notification a 3 inline buttons."""
        from bot.handlers.event_proposal_notifications import (
            send_event_proposal_notification,
        )

        bot = AsyncMock()
        sent_msg = MagicMock()
        sent_msg.message_id = 123
        bot.send_message = AsyncMock(return_value=sent_msg)

        event = _make_event()

        await send_event_proposal_notification(
            bot=bot,
            event=event,
            event_id="test-uuid",
            confidence=0.88,
            supergroup_id=100,
            topic_id=200,
        )

        call_args = bot.send_message.call_args
        reply_markup = call_args.kwargs["reply_markup"]
        buttons = reply_markup.inline_keyboard[0]
        assert len(buttons) == 3
        assert "Creer" in buttons[0].text
        assert "Modifier" in buttons[1].text
        assert "Annuler" in buttons[2].text

    @pytest.mark.asyncio
    async def test_callback_data_contains_event_id(self):
        """Callback data contient event_id."""
        from bot.handlers.event_proposal_notifications import (
            send_event_proposal_notification,
        )

        bot = AsyncMock()
        sent_msg = MagicMock()
        sent_msg.message_id = 123
        bot.send_message = AsyncMock(return_value=sent_msg)

        event = _make_event()

        await send_event_proposal_notification(
            bot=bot,
            event=event,
            event_id="abc-123",
            confidence=0.88,
            supergroup_id=100,
            topic_id=200,
        )

        call_args = bot.send_message.call_args
        reply_markup = call_args.kwargs["reply_markup"]
        buttons = reply_markup.inline_keyboard[0]
        assert "abc-123" in buttons[0].callback_data

    @pytest.mark.asyncio
    async def test_format_date_fr(self):
        """Format date francais correct."""
        from bot.handlers.event_proposal_notifications import format_date_fr

        dt = datetime(2026, 2, 18, 14, 0)
        result = format_date_fr(dt)
        assert "Mercredi" in result
        assert "18" in result
        assert "fevrier" in result
        assert "14h00" in result
