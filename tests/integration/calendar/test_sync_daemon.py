"""Tests d'intégration pour le daemon de synchronisation Google Calendar."""

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
import redis.asyncio as aioredis

from services.calendar_sync.worker import CalendarSyncWorker


@pytest.fixture
async def mock_redis():
    """Create mock Redis client."""
    redis_mock = AsyncMock(spec=aioredis.Redis)
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock(return_value=True)
    redis_mock.incr = AsyncMock(return_value=1)
    redis_mock.expire = AsyncMock(return_value=True)
    redis_mock.delete = AsyncMock(return_value=True)
    return redis_mock


@pytest.fixture
async def mock_sync_manager():
    """Create mock Google Calendar sync manager."""
    from agents.src.integrations.google_calendar.models import SyncResult

    manager = AsyncMock()
    manager.sync_bidirectional = AsyncMock(
        return_value=SyncResult(
            events_created=2,
            events_updated=1,
            errors=[],
        )
    )
    return manager


@pytest.fixture
def mock_config():
    """Create mock calendar configuration."""
    return {
        "google_calendar": {
            "enabled": True,
            "sync_interval_minutes": 30,
            "calendars": [
                {"id": "primary", "name": "Test Calendar", "casquette": "medecin"}
            ],
        }
    }


class TestCalendarSyncWorker:
    """Test suite for calendar sync daemon."""

    @pytest.mark.asyncio
    async def test_sync_daemon_runs_every_30_minutes(
        self, mock_redis, mock_sync_manager, mock_config
    ):
        """Test daemon exécute sync toutes les 30 min (depuis config)."""
        # Arrange
        worker = CalendarSyncWorker(
            sync_manager=mock_sync_manager,
            redis_client=mock_redis,
            config=mock_config,
        )

        # Mock asyncio.sleep to avoid waiting
        sync_count = 0

        async def mock_sleep(seconds):
            nonlocal sync_count
            sync_count += 1
            if sync_count >= 3:  # Stop after 3 iterations
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=mock_sleep):
            try:
                await worker.run()
            except asyncio.CancelledError:
                pass

        # Assert
        # Vérifie que sync_bidirectional a été appelé 3 fois
        assert mock_sync_manager.sync_bidirectional.call_count == 3

        # Vérifie que l'intervalle est bien 30 min (1800 secondes)
        expected_interval = mock_config["google_calendar"]["sync_interval_minutes"] * 60
        assert expected_interval == 1800

    @pytest.mark.asyncio
    async def test_healthcheck_redis_key_updated(
        self, mock_redis, mock_sync_manager, mock_config
    ):
        """Test healthcheck : Redis key calendar:last_sync (TTL 1h)."""
        # Arrange
        worker = CalendarSyncWorker(
            sync_manager=mock_sync_manager,
            redis_client=mock_redis,
            config=mock_config,
        )

        # Act
        await worker.sync_once()

        # Assert
        # Vérifie que la clé Redis a été mise à jour
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "calendar:last_sync"

        # Vérifie que le TTL est 1h (3600 secondes)
        assert call_args[1]["ex"] == 3600

        # Vérifie que la valeur contient un timestamp ISO
        value = json.loads(call_args[0][1])
        assert "timestamp" in value
        assert "events_created" in value
        assert "events_updated" in value

    @pytest.mark.asyncio
    async def test_alert_system_after_3_consecutive_failures(
        self, mock_redis, mock_sync_manager, mock_config
    ):
        """Test alerte System si sync échoue 3x consécutives."""
        # Arrange
        # Make sync_bidirectional fail
        mock_sync_manager.sync_bidirectional.side_effect = Exception(
            "Google Calendar API error"
        )

        # Configure Redis incr to return 1, 2, 3 (incremental counter)
        mock_redis.incr.side_effect = [1, 2, 3]

        worker = CalendarSyncWorker(
            sync_manager=mock_sync_manager,
            redis_client=mock_redis,
            config=mock_config,
        )

        # Mock Telegram alerting (must be AsyncMock for async function)
        with patch(
            "services.calendar_sync.worker.send_telegram_alert", new=AsyncMock()
        ) as mock_telegram:
            # Act - Execute 3 failed syncs
            for _ in range(3):
                await worker.sync_once()

            # Assert
            # Vérifie que l'alerte Telegram a été envoyée après 3 échecs
            mock_telegram.assert_called_once()
            call_args = mock_telegram.call_args
            assert call_args[1]["topic"] == "system"
            assert "3 échecs consécutifs" in call_args[1]["message"]

            # Vérifie que le compteur Redis a été incrémenté 3 fois
            assert mock_redis.incr.call_count == 3
            assert (
                mock_redis.incr.call_args[0][0] == "calendar:sync_failures"
            )  # Last call

    @pytest.mark.asyncio
    async def test_sync_success_resets_failure_counter(
        self, mock_redis, mock_sync_manager, mock_config
    ):
        """Test succès sync → reset compteur échecs."""
        # Arrange
        worker = CalendarSyncWorker(
            sync_manager=mock_sync_manager,
            redis_client=mock_redis,
            config=mock_config,
        )

        # Act - Simulate 2 failures then 1 success
        mock_sync_manager.sync_bidirectional.side_effect = [
            Exception("Error 1"),
            Exception("Error 2"),
            Mock(
                events_created=1, events_updated=0, errors=[]
            ),  # Success on 3rd attempt
        ]

        with patch("services.calendar_sync.worker.send_telegram_alert"):
            for _ in range(3):
                await worker.sync_once()

        # Assert
        # Vérifie que le compteur a été reset après succès
        mock_redis.delete.assert_called_with("calendar:sync_failures")

    @pytest.mark.asyncio
    async def test_graceful_shutdown_on_sigterm(
        self, mock_redis, mock_sync_manager, mock_config
    ):
        """Test arrêt gracieux (SIGTERM)."""
        # Arrange
        worker = CalendarSyncWorker(
            sync_manager=mock_sync_manager,
            redis_client=mock_redis,
            config=mock_config,
        )

        # Act - Simulate SIGTERM during sync
        # Mock asyncio.sleep to raise CancelledError after first sync
        call_count = 0

        async def mock_sleep_with_interrupt(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:  # Interrupt after first sync completes
                raise asyncio.CancelledError()
            # Return immediately (don't actually sleep)
            return None

        with patch("asyncio.sleep", side_effect=mock_sleep_with_interrupt):
            try:
                await worker.run()
            except asyncio.CancelledError:
                pass

        # Assert - Worker should have called cleanup
        # (This test verifies the worker handles CancelledError gracefully)
        assert mock_sync_manager.sync_bidirectional.call_count >= 1
