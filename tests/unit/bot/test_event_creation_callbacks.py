"""
Tests unitaires pour event_creation_callbacks.py

Story 7.4 AC3: Confirmation creation + Sync Google Calendar + Detection conflits
14 tests couvrant:
- Creation evenement confirme (status='confirmed') (2 tests)
- Sync Google Calendar mock (2 tests)
- Detection conflits immediate (2 tests)
- Notification "Evenement cree" formatee (2 tests)
- Annulation evenement (2 tests)
- Cas erreur et edge cases (4 tests)
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bot.handlers.event_creation_callbacks import (
    _check_conflicts_immediate,
    _confirm_event,
    _sync_to_google_calendar,
    handle_event_cancel_callback,
    handle_event_create_callback,
    register_event_creation_callbacks,
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
    return update


@pytest.fixture
def mock_context():
    """Mock Telegram context with db_pool and bot."""
    context = MagicMock()
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()
    context.bot_data = {}
    return context


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg pool."""
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.fixture
def sample_event_id():
    """UUID valide pour tests."""
    return str(uuid.uuid4())


@pytest.fixture
def sample_event_row(sample_event_id):
    """Row retournee par PostgreSQL apres UPDATE."""
    return {
        "id": uuid.UUID(sample_event_id),
        "name": "Consultation Dr Martin",
        "entity_type": "EVENT",
        "properties": {
            "status": "confirmed",
            "start_datetime": "2026-02-17T14:00:00",
            "end_datetime": "2026-02-17T15:00:00",
            "casquette": "medecin",
            "location": "Cabinet",
        },
    }


# ============================================================================
# TESTS CREATION EVENEMENT (status='confirmed') — 2 tests
# ============================================================================


class TestHandleEventCreateCallback:
    """Tests callback [Creer]."""

    @pytest.mark.asyncio
    async def test_create_confirms_event_and_sends_notification(
        self, mock_update, mock_context, mock_db_pool, sample_event_id, sample_event_row
    ):
        """[Creer] button: confirme event + envoie notification formatee."""
        pool, conn = mock_db_pool
        mock_context.bot_data["db_pool"] = pool

        mock_update.callback_query.data = f"evt_create:{sample_event_id}"

        # Mock _confirm_event
        conn.fetchrow = AsyncMock(return_value=sample_event_row)

        with (
            patch(
                "bot.handlers.event_creation_callbacks._confirm_event",
                new_callable=AsyncMock,
                return_value={
                    "id": sample_event_id,
                    "name": "Consultation Dr Martin",
                    "properties": sample_event_row["properties"],
                },
            ),
            patch(
                "bot.handlers.event_creation_callbacks._sync_to_google_calendar",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "bot.handlers.event_creation_callbacks._check_conflicts_immediate",
                new_callable=AsyncMock,
            ),
        ):
            await handle_event_create_callback(mock_update, mock_context)

        # Verifie notification envoyee
        mock_update.callback_query.edit_message_text.assert_called_once()
        msg = mock_update.callback_query.edit_message_text.call_args[0][0]
        assert "Evenement cree" in msg
        assert "Consultation Dr Martin" in msg

    @pytest.mark.asyncio
    async def test_create_event_not_found(
        self, mock_update, mock_context, mock_db_pool, sample_event_id
    ):
        """[Creer] avec event introuvable -> erreur."""
        pool, _ = mock_db_pool
        mock_context.bot_data["db_pool"] = pool
        mock_update.callback_query.data = f"evt_create:{sample_event_id}"

        with patch(
            "bot.handlers.event_creation_callbacks._confirm_event",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await handle_event_create_callback(mock_update, mock_context)

        mock_update.callback_query.edit_message_text.assert_called_with(
            "Erreur: Evenement non trouve"
        )


# ============================================================================
# TESTS SYNC GOOGLE CALENDAR — 2 tests
# ============================================================================


class TestGoogleCalendarSync:
    """Tests sync Google Calendar via callback."""

    @pytest.mark.asyncio
    async def test_google_sync_returns_external_id(
        self, mock_update, mock_context, mock_db_pool, sample_event_id, sample_event_row
    ):
        """Sync Google Calendar retourne external_id -> affiche dans notification."""
        pool, conn = mock_db_pool
        mock_context.bot_data["db_pool"] = pool
        mock_update.callback_query.data = f"evt_create:{sample_event_id}"

        with (
            patch(
                "bot.handlers.event_creation_callbacks._confirm_event",
                new_callable=AsyncMock,
                return_value={
                    "id": sample_event_id,
                    "name": "RDV",
                    "properties": sample_event_row["properties"],
                },
            ),
            patch(
                "bot.handlers.event_creation_callbacks._sync_to_google_calendar",
                new_callable=AsyncMock,
                return_value="google_cal_abc123",
            ),
            patch(
                "bot.handlers.event_creation_callbacks._check_conflicts_immediate",
                new_callable=AsyncMock,
            ),
        ):
            await handle_event_create_callback(mock_update, mock_context)

        msg = mock_update.callback_query.edit_message_text.call_args[0][0]
        assert "Google Calendar synchronise" in msg

    @pytest.mark.asyncio
    async def test_google_sync_import_error_skipped(self, mock_db_pool, sample_event_id):
        """ImportError Google Calendar = skip silencieux (non-blocking)."""
        pool, _ = mock_db_pool
        event_data = {"id": sample_event_id, "name": "Test", "properties": {}}

        with patch(
            "bot.handlers.event_creation_callbacks._sync_to_google_calendar",
            wraps=_sync_to_google_calendar,
        ):
            # Simuler ImportError en patchant le module
            with patch.dict(
                "sys.modules",
                {
                    "agents.src.integrations.google_calendar.config": None,
                    "agents.src.integrations.google_calendar.sync_manager": None,
                },
            ):
                result = await _sync_to_google_calendar(pool, sample_event_id, event_data)

        assert result is None


# ============================================================================
# TESTS DETECTION CONFLITS — 2 tests
# ============================================================================


class TestConflictDetection:
    """Tests detection conflits immediate apres creation."""

    @pytest.mark.asyncio
    @patch("bot.handlers.event_creation_callbacks.TELEGRAM_SUPERGROUP_ID", 12345)
    @patch("bot.handlers.event_creation_callbacks.TOPIC_SYSTEM_ID", 67890)
    async def test_conflicts_detected_sends_alert(self, mock_db_pool):
        """Conflits detectes -> alerte Topic System."""
        pool, _ = mock_db_pool
        bot = AsyncMock()

        event_data = {
            "id": "test-id",
            "properties": {"start_datetime": "2026-02-17T14:00:00"},
        }

        # Mock conflit
        mock_conflict = MagicMock()
        mock_conflict.event1.title = "Consultation"
        mock_conflict.event2.title = "Cours L2"
        mock_conflict.overlap_minutes = 30

        with patch(
            "agents.src.agents.calendar.conflict_detector.detect_calendar_conflicts",
            new_callable=AsyncMock,
            return_value=[mock_conflict],
        ):
            await _check_conflicts_immediate(pool, event_data, bot)

        bot.send_message.assert_called_once()
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 12345
        assert call_kwargs["message_thread_id"] == 67890
        assert "Conflit calendrier detecte" in call_kwargs["text"]
        assert "Consultation" in call_kwargs["text"]
        assert "Cours L2" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_no_conflicts_no_alert(self, mock_db_pool):
        """Aucun conflit -> pas d'alerte envoyee."""
        pool, _ = mock_db_pool
        bot = AsyncMock()

        event_data = {
            "id": "test-id",
            "properties": {"start_datetime": "2026-02-17T14:00:00"},
        }

        with patch(
            "agents.src.agents.calendar.conflict_detector.detect_calendar_conflicts",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await _check_conflicts_immediate(pool, event_data, bot)

        bot.send_message.assert_not_called()


# ============================================================================
# TESTS NOTIFICATION FORMATEE — 2 tests
# ============================================================================


class TestNotificationFormat:
    """Tests format notification confirmation."""

    @pytest.mark.asyncio
    async def test_notification_includes_date_and_casquette(
        self, mock_update, mock_context, mock_db_pool, sample_event_id
    ):
        """Notification contient date FR + casquette formatee."""
        pool, _ = mock_db_pool
        mock_context.bot_data["db_pool"] = pool
        mock_update.callback_query.data = f"evt_create:{sample_event_id}"

        with (
            patch(
                "bot.handlers.event_creation_callbacks._confirm_event",
                new_callable=AsyncMock,
                return_value={
                    "id": sample_event_id,
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
                "bot.handlers.event_creation_callbacks._check_conflicts_immediate",
                new_callable=AsyncMock,
            ),
        ):
            await handle_event_create_callback(mock_update, mock_context)

        msg = mock_update.callback_query.edit_message_text.call_args[0][0]
        assert "Date :" in msg
        assert "Casquette :" in msg

    @pytest.mark.asyncio
    async def test_notification_without_optional_fields(
        self, mock_update, mock_context, mock_db_pool, sample_event_id
    ):
        """Notification sans date ni casquette = message minimal."""
        pool, _ = mock_db_pool
        mock_context.bot_data["db_pool"] = pool
        mock_update.callback_query.data = f"evt_create:{sample_event_id}"

        with (
            patch(
                "bot.handlers.event_creation_callbacks._confirm_event",
                new_callable=AsyncMock,
                return_value={
                    "id": sample_event_id,
                    "name": "Evenement",
                    "properties": {},
                },
            ),
            patch(
                "bot.handlers.event_creation_callbacks._sync_to_google_calendar",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "bot.handlers.event_creation_callbacks._check_conflicts_immediate",
                new_callable=AsyncMock,
            ),
        ):
            await handle_event_create_callback(mock_update, mock_context)

        msg = mock_update.callback_query.edit_message_text.call_args[0][0]
        assert "Evenement cree" in msg
        assert "Date :" not in msg
        assert "Casquette :" not in msg


# ============================================================================
# TESTS ANNULATION EVENEMENT — 2 tests
# ============================================================================


class TestHandleEventCancelCallback:
    """Tests callback [Annuler]."""

    @pytest.mark.asyncio
    async def test_cancel_updates_status_and_confirms(
        self, mock_update, mock_context, sample_event_id
    ):
        """[Annuler] button: UPDATE status='cancelled' + message confirmation."""
        conn = AsyncMock()
        conn.execute = AsyncMock()

        # asyncpg pool.acquire() returns an async context manager directly (not a coroutine)
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_context.bot_data["db_pool"] = pool
        mock_update.callback_query.data = f"evt_cancel:{sample_event_id}"

        await handle_event_cancel_callback(mock_update, mock_context)

        # Verifie UPDATE execute
        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0]
        assert "cancelled" in sql
        assert "knowledge.entities" in sql

        # Verifie message confirmation
        mock_update.callback_query.edit_message_text.assert_called_with("Creation annulee")

    @pytest.mark.asyncio
    async def test_cancel_without_db_pool(self, mock_update, mock_context, sample_event_id):
        """[Annuler] sans db_pool -> message confirmation quand meme."""
        mock_context.bot_data = {}  # Pas de db_pool
        mock_update.callback_query.data = f"evt_cancel:{sample_event_id}"

        await handle_event_cancel_callback(mock_update, mock_context)

        mock_update.callback_query.edit_message_text.assert_called_with("Creation annulee")


# ============================================================================
# TESTS CAS ERREUR ET EDGE CASES — 4 tests
# ============================================================================


class TestEdgeCases:
    """Tests edge cases et erreurs."""

    @pytest.mark.asyncio
    async def test_create_missing_event_id(self, mock_update, mock_context):
        """callback_data sans event_id -> erreur."""
        mock_context.bot_data["db_pool"] = AsyncMock()
        mock_update.callback_query.data = "evt_create:none"

        await handle_event_create_callback(mock_update, mock_context)

        mock_update.callback_query.edit_message_text.assert_called_with(
            "Erreur: ID evenement manquant"
        )

    @pytest.mark.asyncio
    async def test_create_wrong_prefix_ignored(self, mock_update, mock_context):
        """callback_data avec mauvais prefix -> ignore (return)."""
        mock_update.callback_query.data = "wrong_prefix:123"

        await handle_event_create_callback(mock_update, mock_context)

        # edit_message_text jamais appele (return silencieux)
        mock_update.callback_query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_no_db_pool(self, mock_update, mock_context, sample_event_id):
        """Pas de db_pool -> message erreur."""
        mock_context.bot_data = {}
        mock_update.callback_query.data = f"evt_create:{sample_event_id}"

        await handle_event_create_callback(mock_update, mock_context)

        mock_update.callback_query.edit_message_text.assert_called_with(
            "Erreur: Base de donnees non disponible"
        )

    @pytest.mark.asyncio
    async def test_register_callbacks(self):
        """register_event_creation_callbacks enregistre 2 handlers."""
        application = MagicMock()
        db_pool = MagicMock()

        register_event_creation_callbacks(application, db_pool)

        assert application.add_handler.call_count == 2
