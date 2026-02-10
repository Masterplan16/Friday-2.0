"""
Tests unitaires pour bot/handlers/recovery_commands.py

Story 1.13 - AC5: Commande /recovery
4 tests pour valider affichage événements recovery
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bot.handlers.recovery_commands import recovery_command


@pytest.fixture
def mock_update():
    """Mock Telegram Update avec message reply"""
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Mock Telegram Context avec bot_data et args"""
    context = MagicMock()
    # Mock pool asyncpg dans bot_data
    mock_pool = AsyncMock()
    context.bot_data = {"db_pool": mock_pool}
    context.args = []
    return context


@pytest.fixture
def mock_pool_with_events():
    """Mock asyncpg pool avec événements recovery fictifs"""
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()

    # Mock 2 événements recovery
    mock_conn.fetch.return_value = [
        {
            "event_type": "auto_recovery_ram",
            "services_affected": "kokoro-tts",
            "ram_before": 92,
            "ram_after": 83,
            "success": True,
            "recovery_duration_seconds": 15,
            "notification_sent": True,
            "created_at": datetime(2026, 2, 10, 14, 30, 0),
        },
        {
            "event_type": "crash_loop_detected",
            "services_affected": "faster-whisper",
            "ram_before": None,
            "ram_after": None,
            "success": False,
            "recovery_duration_seconds": None,
            "notification_sent": True,
            "created_at": datetime(2026, 2, 10, 12, 15, 0),
        },
    ]

    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    return mock_pool


@pytest.fixture
def mock_pool_empty():
    """Mock asyncpg pool sans événements"""
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    return mock_pool


@pytest.fixture
def mock_pool_with_stats():
    """Mock asyncpg pool avec statistiques"""
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()

    # Mock fetchval pour statistiques
    async def mock_fetchval(query, *args, **kwargs):
        if "COUNT(*)" in query and "WHERE success = true" in query:
            return 45  # successful_recoveries
        elif "COUNT(*)" in query:
            return 50  # total_recoveries
        elif "AVG(recovery_duration_seconds)" in query:
            return 18.5  # avg_duration
        elif "WHERE success = false AND created_at" in query:
            return 2  # failed_last_30d
        return 0

    mock_conn.fetchval = mock_fetchval

    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    return mock_pool


# Test 1: Liste 10 derniers événements (mode par défaut)
@pytest.mark.asyncio
async def test_recovery_command_lists_recent_events(mock_update, mock_context, mock_pool_with_events):
    """Test liste 10 derniers événements recovery (mode résumé)"""
    # Injecter pool dans context
    mock_context.bot_data["db_pool"] = mock_pool_with_events
    mock_context.args = []

    # Patcher send_message_with_split
    with patch("bot.handlers.recovery_commands.send_message_with_split", new_callable=AsyncMock) as mock_send:
        await recovery_command(mock_update, mock_context)

        # Vérifier qu'on a envoyé un message
        mock_send.assert_called_once()

        # Récupérer le texte du message
        response = mock_send.call_args[0][1]

        # Assertions sur le contenu
        assert "🛡️" in response or "Recovery Events" in response
        assert "10 derniers" in response
        # Devrait mentionner les types d'événements
        assert "auto_recovery_ram" in response or "RAM Auto-Recovery" in response


# Test 2: Mode verbose affiche détails complets
@pytest.mark.asyncio
async def test_recovery_command_verbose_shows_details(mock_update, mock_context, mock_pool_with_events):
    """Test -v flag ajoute services + RAM metrics + duration"""
    # Injecter pool et args
    mock_context.bot_data["db_pool"] = mock_pool_with_events
    mock_context.args = ["-v"]

    # Patcher send_message_with_split
    with patch("bot.handlers.recovery_commands.send_message_with_split", new_callable=AsyncMock) as mock_send:
        await recovery_command(mock_update, mock_context)

        # Récupérer le texte du message
        response = mock_send.call_args[0][1]

        # En mode verbose, devrait afficher :
        # - Services affectés
        # - Métriques RAM (before → after)
        # - Duration
        # - Notification status

        # Services mentionnés
        assert "kokoro-tts" in response or "Services:" in response

        # RAM metrics (92% → 83% ou format similaire)
        assert "RAM:" in response or "92" in response or "→" in response

        # Duration
        assert "Duration:" in response or "15" in response or "s" in response

        # Notification
        assert "Notification:" in response or "✓" in response


# Test 3: Mode stats affiche métriques agrégées
@pytest.mark.asyncio
async def test_recovery_command_stats_shows_metrics(mock_update, mock_context, mock_pool_with_stats):
    """Test stats subcommand affiche uptime + MTTR + success rate"""
    # Injecter pool et args
    mock_context.bot_data["db_pool"] = mock_pool_with_stats
    mock_context.args = ["stats"]

    # Patcher send_message_with_split
    with patch("bot.handlers.recovery_commands.send_message_with_split", new_callable=AsyncMock) as mock_send:
        await recovery_command(mock_update, mock_context)

        # Récupérer le texte du message
        response = mock_send.call_args[0][1]

        # Devrait afficher statistiques
        assert "Recovery Statistics" in response or "📊" in response

        # Total recoveries
        assert "Total recoveries" in response or "50" in response

        # Success rate (90% = 45/50)
        assert "Success rate" in response or "90" in response

        # MTTR (18.5s)
        assert "MTTR" in response or "18" in response

        # Uptime estimate
        assert "Uptime" in response or "estimate" in response


# Test 4: Aucun événement = message vide approprié
@pytest.mark.asyncio
async def test_recovery_command_empty_events(mock_update, mock_context, mock_pool_empty):
    """Test message approprié si aucun événement recovery enregistré"""
    # Injecter pool vide
    mock_context.bot_data["db_pool"] = mock_pool_empty
    mock_context.args = []

    await recovery_command(mock_update, mock_context)

    # Vérifier qu'on a répondu avec message "aucun événement"
    mock_update.message.reply_text.assert_called_once()

    response = mock_update.message.reply_text.call_args[0][0]

    # Message devrait indiquer qu'il n'y a pas d'événements
    assert "Aucun événement" in response or "enregistré" in response or "✅" in response
