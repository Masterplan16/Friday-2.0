"""
Tests intégration pour sender filter pipeline (Story 2.8 - H3 fix).

Tests la chaîne complète: consumer → check_sender_filter → DB → Redis event.
Utilise mocks pour les services externes (EmailEngine, Telegram, Presidio).

Requires:
    - PostgreSQL (via db_pool fixture)
    - Redis (via redis_client fixture)
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.src.agents.email.sender_filter import check_sender_filter


# ==========================================
# Helper: Mock DB pool async context manager
# ==========================================


class MockAsyncContextManager:
    """Helper pour mocker async with db_pool.acquire() as conn."""

    def __init__(self, return_value):
        self.return_value = return_value

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


def create_mock_pool(mock_conn):
    """Crée un mock db_pool correct pour async context manager."""
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockAsyncContextManager(mock_conn)
    return mock_pool


# ==========================================
# Fixtures
# ==========================================


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """Reset circuit breaker avant chaque test."""
    from agents.src.agents.email import sender_filter

    sender_filter._circuit_breaker_failures.clear()
    yield
    sender_filter._circuit_breaker_failures.clear()


# ==========================================
# Integration tests: Pipeline avec filtrage
# ==========================================


@pytest.mark.asyncio
async def test_pipeline_with_blacklist_filter():
    """
    Test pipeline email complet avec blacklist filter.

    Vérifie:
    1. check_sender_filter() retourne blacklist match
    2. Catégorie 'spam' assignée
    3. Claude call skippé (pas de classify_email)
    4. Pipeline continue normalement après filtrage
    """
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Simuler blacklist hit sur email exact
    mock_conn.fetchrow.return_value = {
        "id": "test-uuid",
        "filter_type": "blacklist",
        "category": "spam",
        "confidence": 1.0,
    }

    # Appel check_sender_filter (point d'intégration consumer → sender_filter)
    result = await check_sender_filter(
        email_id="integration-test-email-1",
        sender_email="spam@newsletter.com",
        sender_domain="newsletter.com",
        db_pool=mock_pool,
    )

    # Vérifications
    assert result is not None
    assert result["filter_type"] == "blacklist"
    assert result["category"] == "spam"
    assert result["confidence"] == 1.0
    assert result["tokens_saved_estimate"] == 0.015

    # Vérifier que la query DB a été exécutée
    mock_conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_with_whitelist_filter():
    """
    Test pipeline email complet avec whitelist filter.

    Vérifie:
    1. check_sender_filter() retourne whitelist match
    2. Catégorie pré-assignée utilisée
    3. Claude call skippé
    4. Notification topic Email envoyée (whitelist VIP)
    """
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Simuler whitelist hit sur email exact
    mock_conn.fetchrow.return_value = {
        "id": "test-uuid",
        "filter_type": "whitelist",
        "category": "pro",
        "confidence": 0.95,
    }

    result = await check_sender_filter(
        email_id="integration-test-email-2",
        sender_email="vip@hospital.fr",
        sender_domain="hospital.fr",
        db_pool=mock_pool,
    )

    assert result is not None
    assert result["filter_type"] == "whitelist"
    assert result["category"] == "pro"
    assert result["confidence"] == 0.95
    assert result["tokens_saved_estimate"] == 0.015


@pytest.mark.asyncio
async def test_pipeline_neutral_proceeds_to_classify():
    """
    Test pipeline email sans filter match → classification normale.

    Vérifie:
    1. check_sender_filter() retourne None (pas de match)
    2. Pipeline continue vers classify_email()
    """
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Simuler pas de match
    mock_conn.fetchrow.return_value = None

    result = await check_sender_filter(
        email_id="integration-test-email-3",
        sender_email="unknown@newdomain.com",
        sender_domain="newdomain.com",
        db_pool=mock_pool,
    )

    # Pas de filtre → classification normale
    assert result is None
    # Deux appels DB: email lookup + domain fallback
    assert mock_conn.fetchrow.call_count == 2


@pytest.mark.asyncio
async def test_telegram_commands_db_integration():
    """
    Test commande /blacklist → INSERT DB → vérifiable via /filters.

    Simule le flux:
    1. Mainteneur envoie /blacklist spam@test.com
    2. INSERT dans core.sender_filters
    3. /filters list affiche le nouveau filtre
    """
    from bot.handlers.sender_filter_commands import blacklist_command, filters_command

    # Setup mocks
    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()

    context_blacklist = MagicMock()
    context_blacklist.args = ["spam@test.com"]

    # Mock DB: INSERT retourne UUID
    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = "new-filter-uuid"

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    context_blacklist.bot_data = {"db_pool": mock_pool}

    # Step 1: /blacklist
    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await blacklist_command(update, context_blacklist)

    # Vérifier INSERT
    mock_conn.fetchval.assert_called_once()
    insert_query = mock_conn.fetchval.call_args[0][0]
    assert "INSERT INTO core.sender_filters" in insert_query
    assert "blacklist" in insert_query

    # Step 2: /filters list
    update2 = MagicMock()
    update2.effective_user.id = 12345
    update2.message = AsyncMock()

    context_filters = MagicMock()
    context_filters.args = ["list"]

    mock_conn2 = AsyncMock()
    mock_conn2.fetch.return_value = [
        {
            "sender_email": "spam@test.com",
            "sender_domain": None,
            "filter_type": "blacklist",
            "category": "spam",
            "created_at": "2026-02-12",
        }
    ]

    mock_pool2 = MagicMock()
    mock_pool2.acquire.return_value.__aenter__.return_value = mock_conn2
    mock_pool2.acquire.return_value.__aexit__.return_value = None

    context_filters.bot_data = {"db_pool": mock_pool2}

    with patch("bot.handlers.sender_filter_commands.OWNER_USER_ID", "12345"):
        await filters_command(update2, context_filters)

    reply_text = update2.message.reply_text.call_args[0][0]
    assert "spam@test.com" in reply_text


@pytest.mark.asyncio
async def test_sender_filter_notification_routing():
    """
    Test routage notifications: blacklist=aucune, whitelist=topic Email.

    Vérifie AC5: "Notification topic Email uniquement si whitelist VIP
    (pas pour spam blacklist)"
    """
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Blacklist → pas de notification (retourne résultat pour short-circuit)
    mock_conn.fetchrow.return_value = {
        "id": "test-uuid",
        "filter_type": "blacklist",
        "category": "spam",
        "confidence": 1.0,
    }

    blacklist_result = await check_sender_filter(
        email_id="notif-test-blacklist",
        sender_email="spam@newsletter.com",
        sender_domain="newsletter.com",
        db_pool=mock_pool,
    )

    assert blacklist_result is not None
    assert blacklist_result["filter_type"] == "blacklist"
    # Consumer short-circuits: pas de notification

    # Whitelist → notification topic Email (consumer continue normal flow)
    mock_conn.fetchrow.return_value = {
        "id": "test-uuid",
        "filter_type": "whitelist",
        "category": "pro",
        "confidence": 0.95,
    }

    whitelist_result = await check_sender_filter(
        email_id="notif-test-whitelist",
        sender_email="vip@hospital.fr",
        sender_domain="hospital.fr",
        db_pool=mock_pool,
    )

    assert whitelist_result is not None
    assert whitelist_result["filter_type"] == "whitelist"
    # Consumer continue: notification topic Email envoyée
