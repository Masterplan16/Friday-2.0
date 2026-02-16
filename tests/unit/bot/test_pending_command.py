"""Tests unitaires pour /pending command (Story 1.18)."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Chat, Message, Update, User
from telegram.ext import ContextTypes


@pytest.fixture
def mock_update():
    """Mock Update Telegram."""
    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 12345  # OWNER_USER_ID
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Mock ContextTypes."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []
    return context


@pytest.fixture
def mock_pool():
    """Mock asyncpg pool."""
    pool = MagicMock()
    conn = MagicMock()
    conn.fetch = AsyncMock()
    conn.fetchval = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock()
    pool.acquire.return_value = conn
    return pool


# ────────────────────────────────────────────────────────────
# AC1 : Commande /pending basique
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_command_shows_only_pending_actions(mock_update, mock_context, mock_pool):
    """AC1: Liste uniquement les actions status=pending."""
    from bot.handlers.trust_budget_commands import pending_command

    # Mock DB: 2 pending + 1 executed
    mock_pool.acquire.return_value.__aenter__.return_value.fetch = AsyncMock(
        return_value=[
            {
                "id": "abc12345-1234-1234-1234-123456789abc",
                "module": "email",
                "action_type": "classify",
                "created_at": datetime(2026, 2, 16, 14, 32, tzinfo=timezone.utc),
                "input_summary": "Email Dr Martin",
                "output_summary": "Catégorie: pro",
                "confidence": Decimal("0.89"),
            },
            {
                "id": "def67890-1234-1234-1234-123456789def",
                "module": "calendar",
                "action_type": "detect_event",
                "created_at": datetime(2026, 2, 16, 15, 10, tzinfo=timezone.utc),
                "input_summary": "Email réunion",
                "output_summary": "Événement: 2026-02-17 14:00",
                "confidence": Decimal("0.92"),
            },
        ]
    )

    with patch("bot.handlers.trust_budget_commands._get_pool", return_value=mock_pool):
        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            with patch("bot.handlers.trust_budget_commands.send_message_with_split") as mock_send:
                await pending_command(mock_update, mock_context)

    # Vérifier que seules les actions pending sont listées
    mock_send.assert_called_once()
    text = mock_send.call_args[0][1]
    assert "📋 Actions en attente de validation (2)" in text
    assert "⏳" in text
    assert "abc12345" in text
    assert "def67890" in text


@pytest.mark.asyncio
async def test_pending_command_chronological_desc(mock_update, mock_context, mock_pool):
    """AC1: Tri chronologique descendant (plus récentes en premier)."""
    from bot.handlers.trust_budget_commands import pending_command

    mock_pool.acquire.return_value.__aenter__.return_value.fetch = AsyncMock(
        return_value=[
            {
                "id": "newer123-1234-1234-1234-123456789abc",
                "module": "email",
                "action_type": "classify",
                "created_at": datetime(2026, 2, 16, 16, 0, tzinfo=timezone.utc),
                "input_summary": "Newer",
                "output_summary": "Output newer",
                "confidence": Decimal("0.85"),
            },
            {
                "id": "older123-1234-1234-1234-123456789abc",
                "module": "email",
                "action_type": "classify",
                "created_at": datetime(2026, 2, 16, 14, 0, tzinfo=timezone.utc),
                "input_summary": "Older",
                "output_summary": "Output older",
                "confidence": Decimal("0.80"),
            },
        ]
    )

    with patch("bot.handlers.trust_budget_commands._get_pool", return_value=mock_pool):
        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            with patch("bot.handlers.trust_budget_commands.send_message_with_split") as mock_send:
                await pending_command(mock_update, mock_context)

    text = mock_send.call_args[0][1]
    # La plus récente doit apparaître en premier
    newer_pos = text.find("newer123")
    older_pos = text.find("older123")
    assert newer_pos < older_pos, "Plus récente doit être avant plus ancienne"


@pytest.mark.asyncio
async def test_pending_command_format_output(mock_update, mock_context, mock_pool):
    """AC1: Format emoji + ID + module.action + timestamp + output_summary."""
    from bot.handlers.trust_budget_commands import pending_command

    mock_pool.acquire.return_value.__aenter__.return_value.fetch = AsyncMock(
        return_value=[
            {
                "id": "abc12345-1234-1234-1234-123456789abc",
                "module": "email",
                "action_type": "classify",
                "created_at": datetime(2026, 2, 16, 14, 32, tzinfo=timezone.utc),
                "input_summary": "Email test",
                "output_summary": "Catégorie: pro (0.89)",
                "confidence": Decimal("0.89"),
            }
        ]
    )

    with patch("bot.handlers.trust_budget_commands._get_pool", return_value=mock_pool):
        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            with patch("bot.handlers.trust_budget_commands.send_message_with_split") as mock_send:
                await pending_command(mock_update, mock_context)

    text = mock_send.call_args[0][1]
    # Vérifier tous les éléments du format
    assert "⏳" in text  # Emoji pending
    assert "abc12345" in text  # ID (8 premiers chars)
    assert "email.classify" in text  # module.action
    assert "Catégorie: pro" in text  # output_summary
    assert "/receipt abc12345" in text  # Lien receipt
    assert "💡 Utilisez /receipt <id>" in text  # Footer
    # M1 fix: pas de parse_mode Markdown (contenu utilisateur non echappe)
    assert (
        mock_send.call_args[1].get("parse_mode") is None
        or "parse_mode" not in mock_send.call_args[1]
    )


# ────────────────────────────────────────────────────────────
# AC2 : Filtrage par module
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_command_filter_by_module(mock_update, mock_context, mock_pool):
    """AC2: /pending email filtre uniquement module email."""
    from bot.handlers.trust_budget_commands import pending_command

    mock_context.args = ["email"]

    mock_pool.acquire.return_value.__aenter__.return_value.fetch = AsyncMock(
        return_value=[
            {
                "id": "email123-1234-1234-1234-123456789abc",
                "module": "email",
                "action_type": "classify",
                "created_at": datetime(2026, 2, 16, 14, 0, tzinfo=timezone.utc),
                "input_summary": "Email",
                "output_summary": "Output email",
                "confidence": Decimal("0.85"),
            }
        ]
    )

    with patch("bot.handlers.trust_budget_commands._get_pool", return_value=mock_pool):
        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            with patch("bot.handlers.trust_budget_commands.send_message_with_split") as mock_send:
                await pending_command(mock_update, mock_context)

    # Vérifier que la query a été appelée avec le filtre module
    fetch_call = mock_pool.acquire.return_value.__aenter__.return_value.fetch.call_args
    query = fetch_call[0][0]
    assert "module = $1" in query

    text = mock_send.call_args[0][1]
    assert "📋 Actions en attente - Module: email (1)" in text


# ────────────────────────────────────────────────────────────
# AC3 : Mode verbose
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_command_verbose_shows_input(mock_update, mock_context, mock_pool):
    """AC3: /pending -v affiche input_summary."""
    from bot.handlers.trust_budget_commands import pending_command

    mock_context.args = ["-v"]

    mock_pool.acquire.return_value.__aenter__.return_value.fetch = AsyncMock(
        return_value=[
            {
                "id": "abc12345-1234-1234-1234-123456789abc",
                "module": "email",
                "action_type": "classify",
                "created_at": datetime(2026, 2, 16, 14, 32, tzinfo=timezone.utc),
                "input_summary": "Email complet avec détails",
                "output_summary": "Catégorie: pro",
                "confidence": Decimal("0.89"),
            }
        ]
    )

    with patch("bot.handlers.trust_budget_commands._get_pool", return_value=mock_pool):
        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            with patch("bot.handlers.trust_budget_commands.send_message_with_split") as mock_send:
                await pending_command(mock_update, mock_context)

    text = mock_send.call_args[0][1]
    assert "📥 Input:" in text
    assert "Email complet avec détails" in text


# ────────────────────────────────────────────────────────────
# AC4 : Aucune action pending
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_command_no_pending_actions(mock_update, mock_context, mock_pool):
    """AC4: Message si aucune action pending."""
    from bot.handlers.trust_budget_commands import pending_command

    mock_pool.acquire.return_value.__aenter__.return_value.fetch = AsyncMock(return_value=[])

    with patch("bot.handlers.trust_budget_commands._get_pool", return_value=mock_pool):
        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            await pending_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    text = mock_update.message.reply_text.call_args[0][0]
    assert "✅ Aucune action en attente de validation" in text
    assert "Tout est à jour" in text


# ────────────────────────────────────────────────────────────
# AC5 : Pagination si >20 actions
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_command_pagination_limit_20(mock_update, mock_context, mock_pool):
    """AC5: Limite à 20 actions + warning si total > 20."""
    from bot.handlers.trust_budget_commands import pending_command

    # Simuler 20 actions retournées + total de 25
    mock_rows = [
        {
            "id": f"action{i:02d}-1234-1234-1234-123456789abc",
            "module": "email",
            "action_type": "classify",
            "created_at": datetime(2026, 2, 16, 14, i, tzinfo=timezone.utc),
            "input_summary": f"Input {i}",
            "output_summary": f"Output {i}",
            "confidence": Decimal("0.85"),
        }
        for i in range(20)
    ]

    conn_mock = mock_pool.acquire.return_value.__aenter__.return_value
    conn_mock.fetch = AsyncMock(return_value=mock_rows)
    conn_mock.fetchval = AsyncMock(return_value=25)  # Total count

    with patch("bot.handlers.trust_budget_commands._get_pool", return_value=mock_pool):
        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            with patch("bot.handlers.trust_budget_commands.send_message_with_split") as mock_send:
                await pending_command(mock_update, mock_context)

    text = mock_send.call_args[0][1]
    assert "⚠️ Affichage limite aux 20 plus recentes (25 total)" in text


# ────────────────────────────────────────────────────────────
# AC6 : Autorisation Mainteneur uniquement
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_command_unauthorized_user(mock_update, mock_context, mock_pool):
    """AC6: Erreur si utilisateur non autorisé."""
    from bot.handlers.trust_budget_commands import pending_command

    mock_update.effective_user.id = 99999  # Pas OWNER_USER_ID

    with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
        await pending_command(mock_update, mock_context)

    # Vérifier que _ERR_UNAUTHORIZED est envoyé
    mock_update.message.reply_text.assert_called_once()
    text = mock_update.message.reply_text.call_args[0][0]
    assert "Non autorise" in text or "Non autorisé" in text


# ────────────────────────────────────────────────────────────
# Tests edge cases
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_command_db_error(mock_update, mock_context, mock_pool):
    """Gestion erreur DB."""
    from bot.handlers.trust_budget_commands import pending_command

    mock_pool.acquire.return_value.__aenter__.return_value.fetch = AsyncMock(
        side_effect=Exception("DB connection failed")
    )

    with patch("bot.handlers.trust_budget_commands._get_pool", return_value=mock_pool):
        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            await pending_command(mock_update, mock_context)

    # Vérifier que _ERR_DB est envoyé
    mock_update.message.reply_text.assert_called_once()
    text = mock_update.message.reply_text.call_args[0][0]
    assert "Erreur DB" in text


@pytest.mark.asyncio
async def test_pending_command_combined_module_verbose(mock_update, mock_context, mock_pool):
    """Test combinaison filtrage module + verbose."""
    from bot.handlers.trust_budget_commands import pending_command

    mock_context.args = ["email", "-v"]

    mock_pool.acquire.return_value.__aenter__.return_value.fetch = AsyncMock(
        return_value=[
            {
                "id": "abc12345-1234-1234-1234-123456789abc",
                "module": "email",
                "action_type": "classify",
                "created_at": datetime(2026, 2, 16, 14, 32, tzinfo=timezone.utc),
                "input_summary": "Input détaillé",
                "output_summary": "Output détaillé",
                "confidence": Decimal("0.89"),
            }
        ]
    )

    with patch("bot.handlers.trust_budget_commands._get_pool", return_value=mock_pool):
        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            with patch("bot.handlers.trust_budget_commands.send_message_with_split") as mock_send:
                await pending_command(mock_update, mock_context)

    text = mock_send.call_args[0][1]
    # Vérifier filtrage module
    assert "Module: email" in text
    # Vérifier mode verbose
    assert "📥 Input:" in text
    assert "Input détaillé" in text


# ────────────────────────────────────────────────────────────
# Fix M2 : Test pagination + filtre module combinés (H1 fix)
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_command_pagination_with_module_filter(mock_update, mock_context, mock_pool):
    """H1 fix: Le total count respecte le filtre module dans la pagination."""
    from bot.handlers.trust_budget_commands import pending_command

    mock_context.args = ["email"]

    # Simuler 20 actions email retournées + total email = 30
    mock_rows = [
        {
            "id": f"action{i:02d}-1234-1234-1234-123456789abc",
            "module": "email",
            "action_type": "classify",
            "created_at": datetime(2026, 2, 16, 14, i, tzinfo=timezone.utc),
            "input_summary": f"Input {i}",
            "output_summary": f"Output {i}",
            "confidence": Decimal("0.85"),
        }
        for i in range(20)
    ]

    conn_mock = mock_pool.acquire.return_value.__aenter__.return_value
    conn_mock.fetch = AsyncMock(return_value=mock_rows)
    conn_mock.fetchval = AsyncMock(return_value=30)  # 30 email pending (pas total global)

    with patch("bot.handlers.trust_budget_commands._get_pool", return_value=mock_pool):
        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            with patch("bot.handlers.trust_budget_commands.send_message_with_split") as mock_send:
                await pending_command(mock_update, mock_context)

    # Vérifier que le count query inclut le filtre module
    fetchval_call = conn_mock.fetchval.call_args
    count_query = fetchval_call[0][0]
    assert "module = $1" in count_query, "Count query doit filtrer par module"

    text = mock_send.call_args[0][1]
    assert "30 total" in text
    assert "Module: email" in text


# ────────────────────────────────────────────────────────────
# Fix M3 : Test --verbose ne pollue pas le filtre module (H2 fix)
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_command_long_verbose_flag_not_parsed_as_module(
    mock_update, mock_context, mock_pool
):
    """H2 fix: --verbose ne doit pas etre interprete comme nom de module."""
    from bot.handlers.trust_budget_commands import pending_command

    mock_context.args = ["--verbose", "email"]

    mock_pool.acquire.return_value.__aenter__.return_value.fetch = AsyncMock(
        return_value=[
            {
                "id": "abc12345-1234-1234-1234-123456789abc",
                "module": "email",
                "action_type": "classify",
                "created_at": datetime(2026, 2, 16, 14, 32, tzinfo=timezone.utc),
                "input_summary": "Input verbose",
                "output_summary": "Output verbose",
                "confidence": Decimal("0.89"),
            }
        ]
    )

    with patch("bot.handlers.trust_budget_commands._get_pool", return_value=mock_pool):
        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            with patch("bot.handlers.trust_budget_commands.send_message_with_split") as mock_send:
                await pending_command(mock_update, mock_context)

    # Vérifier que le module filtre est "email" (pas "--verbose")
    fetch_call = conn_mock = mock_pool.acquire.return_value.__aenter__.return_value.fetch.call_args
    query = fetch_call[0][0]
    assert "module = $1" in query, "Doit filtrer par module email"

    text = mock_send.call_args[0][1]
    assert "Module: email" in text
    # Verbose doit etre actif aussi
    assert "📥 Input:" in text


# ────────────────────────────────────────────────────────────
# Fix L1 : Test confidence=None
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_command_confidence_none(mock_update, mock_context, mock_pool):
    """L1 fix: confidence=None affiche N/A."""
    from bot.handlers.trust_budget_commands import pending_command

    mock_pool.acquire.return_value.__aenter__.return_value.fetch = AsyncMock(
        return_value=[
            {
                "id": "nullconf-1234-1234-1234-123456789abc",
                "module": "email",
                "action_type": "classify",
                "created_at": datetime(2026, 2, 16, 14, 0, tzinfo=timezone.utc),
                "input_summary": "Input test",
                "output_summary": "Output test",
                "confidence": None,
            }
        ]
    )

    with patch("bot.handlers.trust_budget_commands._get_pool", return_value=mock_pool):
        with patch("bot.handlers.trust_budget_commands._OWNER_USER_ID", 12345):
            with patch("bot.handlers.trust_budget_commands.send_message_with_split") as mock_send:
                await pending_command(mock_update, mock_context)

    text = mock_send.call_args[0][1]
    assert "N/A" in text
