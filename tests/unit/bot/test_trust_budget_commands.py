"""
Tests unitaires pour bot/handlers/trust_budget_commands.py

Story 1.11 - Task 5.1 : Tests des 6 commandes /confiance, /receipt, /journal,
/status, /budget, /stats.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Message, Update, User
from telegram.ext import ContextTypes

# ────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_update():
    """Fixture : Mock Telegram Update."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 12345
    update.message = MagicMock(spec=Message)
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture(autouse=True)
def patch_owner_user_id(mock_update):
    """Patch _OWNER_USER_ID pour tous les tests (sauf ceux qui le patchent explicitement)."""
    with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", mock_update.effective_user.id):
        yield


@pytest.fixture
def mock_context():
    """Fixture : Mock Telegram Context."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []
    context.bot_data = {}
    return context


@pytest.fixture
def mock_db_conn():
    """Fixture : Mock asyncpg connection."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=1)
    conn.close = AsyncMock()
    return conn


@pytest.fixture
def mock_pool(mock_db_conn):
    """Fixture : Mock asyncpg pool avec acquire() context manager.

    pool.acquire() est synchrone (retourne un context manager),
    donc pool doit etre MagicMock (pas AsyncMock).
    """
    pool = MagicMock()
    acm = AsyncMock()
    acm.__aenter__.return_value = mock_db_conn
    pool.acquire.return_value = acm
    return pool


# ────────────────────────────────────────────────────────────
# Authorization (H5 fix)
# ────────────────────────────────────────────────────────────


class TestAuthorization:
    """Tests pour verification OWNER_USER_ID."""

    @pytest.mark.asyncio
    async def test_unauthorized_user_rejected(self, mock_update, mock_context):
        """Commande refusee si user != OWNER_USER_ID."""
        from bot.handlers.trust_budget_commands import confiance_command

        mock_update.effective_user.id = 99999

        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            await confiance_command(mock_update, mock_context)

            text = mock_update.message.reply_text.call_args[0][0]
            assert "Non autorise" in text

    @pytest.mark.asyncio
    async def test_owner_zero_allows_all(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """OWNER_USER_ID=0 (non configure) autorise tout le monde."""
        from bot.handlers.trust_budget_commands import journal_command

        mock_db_conn.fetch.return_value = []

        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 0):
            with patch(
                "bot.handlers.trust_budget_commands._get_pool",
                new_callable=AsyncMock,
                return_value=mock_pool,
            ):
                await journal_command(mock_update, mock_context)

                text = mock_update.message.reply_text.call_args[0][0]
                assert "Aucune action enregistree" in text


# ────────────────────────────────────────────────────────────
# /confiance (AC1)
# ────────────────────────────────────────────────────────────


class TestConfianceCommand:
    """Tests pour /confiance."""

    @pytest.mark.asyncio
    async def test_confiance_with_data(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC1: Affiche tableau accuracy avec donnees."""
        from bot.handlers.trust_budget_commands import confiance_command

        now = datetime.now(tz=timezone.utc)
        mock_db_conn.fetch.return_value = [
            {
                "module": "email",
                "action_type": "classify",
                "week_start": now.date(),
                "total_actions": 15,
                "corrected_actions": 1,
                "accuracy": 0.933,
                "current_trust_level": "auto",
                "trust_changed": False,
            },
            {
                "module": "email",
                "action_type": "classify",
                "week_start": (now - timedelta(days=7)).date(),
                "total_actions": 12,
                "corrected_actions": 0,
                "accuracy": 1.0,
                "current_trust_level": "auto",
                "trust_changed": False,
            },
        ]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands._load_trust_levels_config",
                return_value={"email": {"classify": "auto"}},
            ):
                with patch(
                    "bot.handlers.trust_budget_commands.send_message_with_split",
                    new_callable=AsyncMock,
                ) as mock_send:
                    await confiance_command(mock_update, mock_context)

                    mock_send.assert_called_once()
                    text = mock_send.call_args[0][1]
                    assert "email.classify" in text
                    assert "93.3%" in text
                    assert "auto" in text

    @pytest.mark.asyncio
    async def test_confiance_no_data(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC1: Message quand aucune metrique."""
        from bot.handlers.trust_budget_commands import confiance_command

        mock_db_conn.fetch.return_value = []

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await confiance_command(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()
            text = mock_update.message.reply_text.call_args[0][0]
            assert "Pas encore de donnees" in text

    @pytest.mark.asyncio
    async def test_confiance_verbose(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC1: Mode verbose affiche detail semaine par semaine."""
        from bot.handlers.trust_budget_commands import confiance_command

        mock_context.args = ["-v"]
        now = datetime.now(tz=timezone.utc)

        mock_db_conn.fetch.return_value = [
            {
                "module": "email",
                "action_type": "classify",
                "week_start": now.date(),
                "total_actions": 10,
                "corrected_actions": 1,
                "accuracy": 0.9,
                "current_trust_level": "auto",
                "trust_changed": False,
            },
        ]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands._load_trust_levels_config",
                return_value={"email": {"classify": "auto"}},
            ):
                with patch(
                    "bot.handlers.trust_budget_commands.send_message_with_split",
                    new_callable=AsyncMock,
                ) as mock_send:
                    await confiance_command(mock_update, mock_context)

                    text = mock_send.call_args[0][1]
                    assert "corr=" in text

    @pytest.mark.asyncio
    async def test_confiance_with_retrogradation(
        self, mock_update, mock_context, mock_pool, mock_db_conn
    ):
        """AC1: Mention visuelle retrogradation recente."""
        from bot.handlers.trust_budget_commands import confiance_command

        mock_db_conn.fetch.return_value = [
            {
                "module": "email",
                "action_type": "classify",
                "week_start": datetime.now(tz=timezone.utc).date(),
                "total_actions": 15,
                "corrected_actions": 3,
                "accuracy": 0.8,
                "current_trust_level": "propose",
                "trust_changed": True,
            },
        ]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands._load_trust_levels_config",
                return_value={"email": {"classify": "propose"}},
            ):
                with patch(
                    "bot.handlers.trust_budget_commands.send_message_with_split",
                    new_callable=AsyncMock,
                ) as mock_send:
                    await confiance_command(mock_update, mock_context)

                    text = mock_send.call_args[0][1]
                    assert "RETRO" in text


# ────────────────────────────────────────────────────────────
# /receipt (AC2)
# ────────────────────────────────────────────────────────────


class TestReceiptCommand:
    """Tests pour /receipt."""

    @pytest.mark.asyncio
    async def test_receipt_found(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC2: Affiche detail complet d'un receipt."""
        from bot.handlers.trust_budget_commands import receipt_command

        mock_context.args = ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"]

        mock_db_conn.fetchrow.return_value = {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "module": "email",
            "action_type": "classify",
            "trust_level": "auto",
            "status": "auto",
            "input_summary": "Email de test@example.com: Sujet test",
            "output_summary": "medical (0.95)",
            "confidence": 0.95,
            "reasoning": "Keywords detected: consultation",
            "payload": {"steps": []},
            "correction": None,
            "feedback_comment": None,
            "created_at": datetime(2026, 2, 10, 14, 30),
            "updated_at": datetime(2026, 2, 10, 14, 30),
            "validated_by": None,
            "duration_ms": 250,
        }

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await receipt_command(mock_update, mock_context)

                text = mock_send.call_args[0][1]
                assert "a1b2c3d4" in text
                assert "email.classify" in text
                assert "95.0%" in text

    @pytest.mark.asyncio
    async def test_receipt_not_found(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC2: Message erreur gracieux si introuvable."""
        from bot.handlers.trust_budget_commands import receipt_command

        mock_context.args = ["a1b2c3d4"]
        mock_db_conn.fetchrow.return_value = None
        mock_db_conn.fetch.return_value = []

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await receipt_command(mock_update, mock_context)

            text = mock_update.message.reply_text.call_args[0][0]
            assert "introuvable" in text

    @pytest.mark.asyncio
    async def test_receipt_by_prefix(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC2: Recherche par prefix UUID (>=8 chars)."""
        from bot.handlers.trust_budget_commands import receipt_command

        mock_context.args = ["a1b2c3d4"]
        mock_db_conn.fetchrow.return_value = None  # Pas de match exact
        mock_db_conn.fetch.return_value = [
            {
                "id": "a1b2c3d4-aaaa-bbbb-cccc-ddddeeeeeeee",
                "module": "email",
                "action_type": "classify",
                "trust_level": "auto",
                "status": "auto",
                "input_summary": "Test input summary",
                "output_summary": "OK result here",
                "confidence": 0.9,
                "reasoning": "test reasoning text here",
                "payload": None,
                "correction": None,
                "feedback_comment": None,
                "created_at": datetime(2026, 2, 10, 14, 0),
                "updated_at": datetime(2026, 2, 10, 14, 0),
                "validated_by": None,
                "duration_ms": None,
            },
        ]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await receipt_command(mock_update, mock_context)

                text = mock_send.call_args[0][1]
                assert "a1b2c3d4" in text

    @pytest.mark.asyncio
    async def test_receipt_invalid_uuid(self, mock_update, mock_context):
        """AC2: Message erreur avec format attendu si UUID invalide."""
        from bot.handlers.trust_budget_commands import receipt_command

        mock_context.args = ["xyz"]  # Trop court + non hex

        await receipt_command(mock_update, mock_context)

        text = mock_update.message.reply_text.call_args[0][0]
        assert "UUID invalide" in text
        assert "8 caracteres" in text

    @pytest.mark.asyncio
    async def test_receipt_verbose(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC2: Mode verbose affiche payload + steps."""
        from bot.handlers.trust_budget_commands import receipt_command

        mock_context.args = ["a1b2c3d4-e5f6-7890-abcd-ef1234567890", "-v"]

        mock_db_conn.fetchrow.return_value = {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "module": "email",
            "action_type": "classify",
            "trust_level": "auto",
            "status": "auto",
            "input_summary": "Test input summary",
            "output_summary": "OK result here",
            "confidence": 0.95,
            "reasoning": "test reasoning text here",
            "payload": {"steps": [{"name": "classify", "confidence": 0.95}]},
            "correction": None,
            "feedback_comment": "Good job",
            "created_at": datetime(2026, 2, 10, 14, 0),
            "updated_at": datetime(2026, 2, 10, 14, 5),
            "validated_by": 12345,
            "duration_ms": 350,
        }

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await receipt_command(mock_update, mock_context)

                text = mock_send.call_args[0][1]
                assert "350ms" in text
                assert "12345" in text
                assert "steps" in text


# ────────────────────────────────────────────────────────────
# /journal (AC3)
# ────────────────────────────────────────────────────────────


class TestJournalCommand:
    """Tests pour /journal."""

    @pytest.mark.asyncio
    async def test_journal_with_actions(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC3: Liste 20 actions chronologiquement."""
        from bot.handlers.trust_budget_commands import journal_command

        mock_db_conn.fetch.return_value = [
            {
                "id": "aaa",
                "module": "email",
                "action_type": "classify",
                "status": "auto",
                "confidence": 0.95,
                "input_summary": "Email de test",
                "created_at": datetime(2026, 2, 10, 14, 30, 0),
            },
            {
                "id": "bbb",
                "module": "archiviste",
                "action_type": "rename",
                "status": "pending",
                "confidence": 0.85,
                "input_summary": "Document facture",
                "created_at": datetime(2026, 2, 10, 14, 25, 0),
            },
        ]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await journal_command(mock_update, mock_context)

                text = mock_send.call_args[0][1]
                assert "email.classify" in text
                assert "archiviste.rename" in text
                assert "95.0%" in text

    @pytest.mark.asyncio
    async def test_journal_empty(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC3: Message quand aucune action."""
        from bot.handlers.trust_budget_commands import journal_command

        mock_db_conn.fetch.return_value = []

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await journal_command(mock_update, mock_context)

            text = mock_update.message.reply_text.call_args[0][0]
            assert "Aucune action enregistree" in text

    @pytest.mark.asyncio
    async def test_journal_verbose_shows_input(
        self, mock_update, mock_context, mock_pool, mock_db_conn
    ):
        """AC3+AC7: Mode verbose affiche input_summary par entree."""
        from bot.handlers.trust_budget_commands import journal_command

        mock_context.args = ["-v"]
        mock_db_conn.fetch.return_value = [
            {
                "id": "aaa",
                "module": "email",
                "action_type": "classify",
                "status": "auto",
                "confidence": 0.9,
                "input_summary": "Email de important@example.com",
                "created_at": datetime(2026, 2, 10, 14, 30, 0),
            },
        ]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await journal_command(mock_update, mock_context)

                text = mock_send.call_args[0][1]
                assert "Input:" in text
                assert "important@example.com" in text


# ────────────────────────────────────────────────────────────
# /status (AC4)
# ────────────────────────────────────────────────────────────


class TestStatusCommand:
    """Tests pour /status."""

    @pytest.mark.asyncio
    async def test_status_all_healthy(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC4: Dashboard complet quand tout est OK."""
        from bot.handlers.trust_budget_commands import status_command

        # Mock DB: actions today + pending (single connection)
        mock_db_conn.fetch.return_value = [
            {"status": "auto", "cnt": 5},
            {"status": "pending", "cnt": 2},
        ]
        mock_db_conn.fetchrow.return_value = {
            "pending_count": 2,
            "oldest_pending": datetime(2026, 2, 10, 10, 0),
        }

        # Mock Redis
        mock_redis = MagicMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.close = AsyncMock()

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.aioredis.from_url", return_value=mock_redis
            ):
                with patch(
                    "bot.handlers.trust_budget_commands.send_message_with_split",
                    new_callable=AsyncMock,
                ) as mock_send:
                    await status_command(mock_update, mock_context)

                    text = mock_send.call_args[0][1]
                    assert "PostgreSQL: OK" in text
                    assert "Redis: OK" in text
                    assert "Pending" in text

    @pytest.mark.asyncio
    async def test_status_db_down(self, mock_update, mock_context):
        """AC4: Mode degrade quand DB inaccessible."""
        from bot.handlers.trust_budget_commands import status_command

        # Mock Redis
        mock_redis = MagicMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.close = AsyncMock()

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            side_effect=ValueError("DB not configured"),
        ):
            with patch(
                "bot.handlers.trust_budget_commands.aioredis.from_url", return_value=mock_redis
            ):
                with patch(
                    "bot.handlers.trust_budget_commands.send_message_with_split",
                    new_callable=AsyncMock,
                ) as mock_send:
                    await status_command(mock_update, mock_context)

                    text = mock_send.call_args[0][1]
                    assert "PostgreSQL" in text
                    assert "indisponible" in text or "DB not configured" in text


# ────────────────────────────────────────────────────────────
# /budget (AC5)
# ────────────────────────────────────────────────────────────


class TestBudgetCommand:
    """Tests pour /budget."""

    @pytest.mark.asyncio
    async def test_budget_with_tokens(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC5: Cout calcule avec tokens."""
        from bot.handlers.trust_budget_commands import budget_command

        mock_db_conn.fetch.return_value = [
            {
                "module": "email",
                "action_count": 100,
                "tokens_in": 500_000,
                "tokens_out": 50_000,
            },
        ]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await budget_command(mock_update, mock_context)

                text = mock_send.call_args[0][1]
                assert "Budget API Claude" in text
                assert "500,000" in text or "500000" in text
                assert "EUR" in text

    @pytest.mark.asyncio
    async def test_budget_no_tracking(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC5: Message informatif quand pas de tracking tokens."""
        from bot.handlers.trust_budget_commands import budget_command

        mock_db_conn.fetch.return_value = []

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await budget_command(mock_update, mock_context)

            text = mock_update.message.reply_text.call_args[0][0]
            assert "Tracking tokens non encore actif" in text

    @pytest.mark.asyncio
    async def test_budget_over_threshold(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC5: Alerte quand >80% budget consomme."""
        from bot.handlers.trust_budget_commands import budget_command

        # 10M input + 1M output = $30 + $15 = $45 * 0.92 = 41.4 EUR > 80% de 45 EUR
        mock_db_conn.fetch.return_value = [
            {
                "module": "email",
                "action_count": 500,
                "tokens_in": 10_000_000,
                "tokens_out": 1_000_000,
            },
        ]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await budget_command(mock_update, mock_context)

                text = mock_send.call_args[0][1]
                assert "ALERTE" in text
                assert "80%" in text

    @pytest.mark.asyncio
    async def test_budget_verbose_shows_modules(
        self, mock_update, mock_context, mock_pool, mock_db_conn
    ):
        """AC5+AC7: Mode verbose affiche detail par module."""
        from bot.handlers.trust_budget_commands import budget_command

        mock_context.args = ["-v"]
        mock_db_conn.fetch.return_value = [
            {
                "module": "email",
                "action_count": 50,
                "tokens_in": 200_000,
                "tokens_out": 20_000,
            },
            {
                "module": "archiviste",
                "action_count": 30,
                "tokens_in": 100_000,
                "tokens_out": 10_000,
            },
        ]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await budget_command(mock_update, mock_context)

                text = mock_send.call_args[0][1]
                assert "Par module:" in text
                assert "email" in text
                assert "archiviste" in text


# ────────────────────────────────────────────────────────────
# /stats (AC6)
# ────────────────────────────────────────────────────────────


class TestStatsCommand:
    """Tests pour /stats."""

    @pytest.mark.asyncio
    async def test_stats_with_data(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC6: Metriques agregees correctes."""
        from bot.handlers.trust_budget_commands import stats_command

        # 3 fetchrow calls (24h, 7d, 30d) + 2 fetch (top_modules, status_breakdown)
        mock_db_conn.fetchrow.side_effect = [
            {"total": 10, "avg_confidence": 0.92},  # 24h
            {"total": 50, "success_cnt": 40, "error_cnt": 2, "avg_confidence": 0.91},  # 7d
            {"total": 200},  # 30d
        ]
        mock_db_conn.fetch.side_effect = [
            [{"module": "email", "cnt": 30}, {"module": "archiviste", "cnt": 15}],  # top modules
            [{"status": "auto", "cnt": 35}, {"status": "pending", "cnt": 10}],  # status
        ]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await stats_command(mock_update, mock_context)

                text = mock_send.call_args[0][1]
                assert "Actions 24h: 10" in text
                assert "Actions 7j: 50" in text
                assert "Actions 30j: 200" in text
                assert "email" in text

    @pytest.mark.asyncio
    async def test_stats_empty(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """AC6: Message adapte quand aucune donnee."""
        from bot.handlers.trust_budget_commands import stats_command

        mock_db_conn.fetchrow.side_effect = [
            {"total": 0, "avg_confidence": None},  # 24h
            {"total": 0, "success_cnt": 0, "error_cnt": 0, "avg_confidence": None},  # 7d
            {"total": 0},  # 30d
        ]
        mock_db_conn.fetch.side_effect = [[], []]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await stats_command(mock_update, mock_context)

            text = mock_update.message.reply_text.call_args[0][0]
            assert "Aucune action enregistree" in text


# ────────────────────────────────────────────────────────────
# Story 2.6 - Tests améliorations /journal et /receipt pour emails
# ────────────────────────────────────────────────────────────


class TestJournalEmailStory26:
    """Tests Story 2.6 AC4 - Améliorations /journal pour emails envoyés."""

    @pytest.mark.asyncio
    async def test_journal_email_filter(self, mock_update, mock_context, mock_pool, mock_db_conn):
        """Story 2.6 AC4: /journal email filtre uniquement actions email."""
        from bot.handlers.trust_budget_commands import journal_command

        mock_context.args = ["email"]
        mock_db_conn.fetch.return_value = [
            {
                "id": "aaa",
                "module": "email",
                "action_type": "draft_reply",
                "status": "executed",
                "confidence": 0.92,
                "input_summary": "Email de test",
                "output_summary": "[NAME_1]@[DOMAIN_1]",
                "created_at": datetime(2026, 2, 11, 14, 30, 0),
            },
        ]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await journal_command(mock_update, mock_context)

                # Vérifier que fetch a été appelé avec filtre module='email'
                fetch_call = mock_db_conn.fetch.call_args
                assert "WHERE module = $1" in fetch_call[0][0]
                assert fetch_call[0][1] == "email"

                # Vérifier message contient label filtre
                text = mock_send.call_args[0][1]
                assert "(filtre: email)" in text

    @pytest.mark.asyncio
    async def test_journal_email_special_format(
        self, mock_update, mock_context, mock_pool, mock_db_conn
    ):
        """Story 2.6 AC4: Format spécial pour emails envoyés avec recipient_anon."""
        from bot.handlers.trust_budget_commands import journal_command

        mock_db_conn.fetch.return_value = [
            {
                "id": "email-receipt-1",
                "module": "email",
                "action_type": "draft_reply",
                "status": "executed",
                "confidence": 0.95,
                "input_summary": "Email de john@example.com",
                "output_summary": "[NAME_42]@[DOMAIN_13]",  # Recipient anonymisé
                "created_at": datetime(2026, 2, 11, 15, 45, 0),
            },
            {
                "id": "other-receipt-1",
                "module": "archiviste",
                "action_type": "rename",
                "status": "auto",
                "confidence": 0.88,
                "input_summary": "Document test",
                "output_summary": "Renamed to facture.pdf",
                "created_at": datetime(2026, 2, 11, 15, 40, 0),
            },
        ]

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await journal_command(mock_update, mock_context)

                text = mock_send.call_args[0][1]

                # Vérifier format spécial pour email
                assert "Email envoyé → [NAME_42]@[DOMAIN_13]" in text

                # Vérifier format générique pour archiviste
                assert "archiviste.rename" in text

    @pytest.mark.asyncio
    async def test_receipt_email_details_section(
        self, mock_update, mock_context, mock_pool, mock_db_conn
    ):
        """Story 2.6 AC4: /receipt affiche section Email Details pour emails."""
        from bot.handlers.trust_budget_commands import receipt_command

        mock_context.args = ["aabbccdd-eeff-aabb-ccdd-eeffaabbccdd"]
        mock_db_conn.fetchrow.return_value = {
            "id": "aabbccdd-eeff-aabb-ccdd-eeffaabbccdd",
            "module": "email",
            "action_type": "draft_reply",
            "trust_level": "auto",
            "status": "executed",
            "confidence": 0.94,
            "input_summary": "Email de test",
            "output_summary": "[NAME_1]@[DOMAIN_1]",
            "reasoning": "Réponse générée par Claude",
            "created_at": datetime(2026, 2, 11, 14, 30, 0),
            "updated_at": datetime(2026, 2, 11, 14, 31, 0),
            "payload": {
                "account_id": "account_professional",
                "email_type": "professional",
                "message_id": "<sent-456@example.com>",
                "draft_body": "Bonjour,\n\nVoici ma réponse.\n\nCordialement,\nDr. Lopez",
            },
        }

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await receipt_command(mock_update, mock_context)

                text = mock_send.call_args[0][1]

                # Vérifier section Email Details
                assert "Email Details" in text
                assert "Compte IMAP: account_professional" in text
                assert "Type: professional" in text
                assert "Message ID:" in text
                assert "Brouillon (extrait):" in text
                assert "Bonjour" in text

    @pytest.mark.asyncio
    async def test_receipt_verbose_shows_payload_json(
        self, mock_update, mock_context, mock_pool, mock_db_conn
    ):
        """Story 2.6 AC4: /receipt -v affiche payload JSON complet."""
        from bot.handlers.trust_budget_commands import receipt_command

        mock_context.args = ["aabbccdd-eeff-aabb-ccdd-eeffaabbccdd", "-v"]
        mock_db_conn.fetchrow.return_value = {
            "id": "aabbccdd-eeff-aabb-ccdd-eeffaabbccdd",
            "module": "email",
            "action_type": "draft_reply",
            "trust_level": "propose",
            "status": "executed",
            "confidence": 0.91,
            "input_summary": "Input test",
            "output_summary": "Output test",
            "reasoning": "Reasoning test",
            "created_at": datetime(2026, 2, 11, 14, 0, 0),
            "updated_at": datetime(2026, 2, 11, 14, 5, 0),
            "validated_at": datetime(2026, 2, 11, 14, 3, 0),
            "executed_at": datetime(2026, 2, 11, 14, 4, 0),
            "duration_ms": 1250,
            "validated_by": 12345,
            "payload": {
                "draft_body": "Test body",
                "account_id": "account_medical",
                "email_type": "medical",
            },
        }

        with patch(
            "bot.handlers.trust_budget_commands._get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with patch(
                "bot.handlers.trust_budget_commands.send_message_with_split", new_callable=AsyncMock
            ) as mock_send:
                await receipt_command(mock_update, mock_context)

                text = mock_send.call_args[0][1]

                # Vérifier section Details (-v)
                assert "Details (-v)" in text
                assert "Duration: 1250ms" in text
                assert "Validated by: user 12345" in text
                assert "Validated at:" in text
                assert "Executed at:" in text

                # Vérifier payload JSON complet affiché
                assert "Payload (JSON):" in text
                assert '"draft_body":' in text or '"account_id":' in text
