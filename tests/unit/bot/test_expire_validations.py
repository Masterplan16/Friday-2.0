"""
Tests unitaires pour services/metrics/expire_validations.py (Story 1.10, Task 4).

Teste l'expiration des validations en attente (timeout configurable).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.metrics.expire_validations import (
    expire_pending_validations,
    load_timeout_config,
    notify_expiration_telegram,
)


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg Pool."""
    pool = MagicMock()
    conn = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    conn.fetch = AsyncMock(return_value=[])
    return pool


@pytest.mark.asyncio
async def test_expire_validations_after_timeout(mock_db_pool):
    """
    Test AC6: Receipts expires apres timeout.
    """
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetch.return_value = [
        {
            "id": "abc123",
            "module": "email",
            "action_type": "classify",
            "created_at": "2026-02-09T10:00:00",
        },
    ]

    count = await expire_pending_validations(mock_db_pool, timeout_hours=24)
    assert count == 1

    # Verifier UPDATE SQL
    conn.fetch.assert_called_once()
    sql = conn.fetch.call_args[0][0]
    assert "status = 'expired'" in sql
    assert "status = 'pending'" in sql
    assert conn.fetch.call_args[0][1] == 24


@pytest.mark.asyncio
async def test_expire_validations_no_timeout(mock_db_pool):
    """
    Test AC6: Si timeout=null, rien n'expire (BUG-1.10.13 fix).
    """
    count = await expire_pending_validations(mock_db_pool, timeout_hours=None)
    assert count == 0

    # Aucun appel SQL
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_expire_validations_zero_timeout(mock_db_pool):
    """
    Test: timeout=0 -> rien n'expire (valeur invalide).
    """
    count = await expire_pending_validations(mock_db_pool, timeout_hours=0)
    assert count == 0


@pytest.mark.asyncio
async def test_expire_validations_no_pending(mock_db_pool):
    """
    Test: Aucun receipt pending -> 0 expirations.
    """
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetch.return_value = []

    count = await expire_pending_validations(mock_db_pool, timeout_hours=24)
    assert count == 0


def test_load_timeout_config_default():
    """Test: Config reelle avec validation_timeout_hours=null -> None."""
    result = load_timeout_config("config/telegram.yaml")
    assert result is None


def test_load_timeout_config_missing_file():
    """Test: Fichier config manquant -> None."""
    result = load_timeout_config("nonexistent/path.yaml")
    assert result is None


@pytest.mark.asyncio
async def test_notify_expiration_telegram_zero_count():
    """Test H5: Si 0 expirations, pas de notification."""
    # Ne devrait pas lever d'exception
    await notify_expiration_telegram(0, 24)


@pytest.mark.asyncio
async def test_notify_expiration_telegram_no_config():
    """Test H5: Si Telegram non configure, log warning sans crash."""
    with patch.dict("os.environ", {}, clear=True):
        await notify_expiration_telegram(3, 24)
