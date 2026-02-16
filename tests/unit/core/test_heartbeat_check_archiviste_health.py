"""
Tests Unitaires - Heartbeat Check Archiviste Health

Epic 3: Archiviste & Recherche Documentaire

Tests :
- Check détecte Surya OCR down
- Check détecte Watchdog observer inactif
- Check détecte pipeline inactif >24h
- Check skip si tout OK
- CheckResult status='warning' si anomalie
- CheckResult status='ok' si healthy
- Formatage message notification
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.core.heartbeat_checks.archiviste_health import (
    _check_pipeline_activity,
    _check_surya_ocr,
    _check_watchdog_observer,
    _format_health_notification,
    check_archiviste_health,
)
from agents.src.core.heartbeat_models import CheckResult

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg.Pool."""
    pool = AsyncMock()
    conn = AsyncMock()
    # Fix: acquire() doit retourner un coroutine qui est aussi un async context manager
    acquire_mock = AsyncMock()
    acquire_mock.__aenter__ = AsyncMock(return_value=conn)
    acquire_mock.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acquire_mock)
    pool.close = AsyncMock()
    return pool


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def context_normal():
    """Contexte Heartbeat normal (14h)."""
    return {
        "time": datetime(2026, 2, 17, 14, 30),
        "hour": 14,
        "is_weekend": False,
        "quiet_hours": False,
    }


# ============================================================================
# Tests Surya OCR Health Check
# ============================================================================


@pytest.mark.asyncio
async def test_check_surya_ocr_healthy():
    """Test Surya OCR healthy (HTTP 200)."""
    with patch(
        "agents.src.core.heartbeat_checks.archiviste_health.httpx.AsyncClient"
    ) as mock_client:
        # Mock HTTP 200 response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        result = await _check_surya_ocr()

        assert result is None  # No issue


@pytest.mark.asyncio
async def test_check_surya_ocr_unhealthy_503():
    """Test Surya OCR unhealthy (HTTP 503)."""
    with patch(
        "agents.src.core.heartbeat_checks.archiviste_health.httpx.AsyncClient"
    ) as mock_client:
        # Mock HTTP 503 response
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        result = await _check_surya_ocr()

        assert result is not None
        assert "HTTP 503" in result


@pytest.mark.asyncio
async def test_check_surya_ocr_timeout():
    """Test Surya OCR timeout (>5s)."""
    with patch(
        "agents.src.core.heartbeat_checks.archiviste_health.httpx.AsyncClient"
    ) as mock_client:
        # Mock timeout exception
        import httpx

        mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.TimeoutException(
            "Timeout"
        )

        result = await _check_surya_ocr()

        assert result is not None
        assert "timeout" in result.lower()


@pytest.mark.asyncio
async def test_check_surya_ocr_connection_error():
    """Test Surya OCR connection error."""
    with patch(
        "agents.src.core.heartbeat_checks.archiviste_health.httpx.AsyncClient"
    ) as mock_client:
        # Mock connection error
        mock_client.return_value.__aenter__.return_value.get.side_effect = Exception(
            "Connection refused"
        )

        result = await _check_surya_ocr()

        assert result is not None
        assert "inaccessible" in result.lower()


# ============================================================================
# Tests Watchdog Observer Check
# ============================================================================


@pytest.mark.asyncio
async def test_check_watchdog_observer_active(mock_redis):
    """Test Watchdog observer actif (heartbeat Redis présent)."""
    # Mock Redis heartbeat key exists
    mock_redis.get.return_value = b"2026-02-17T14:30:00"

    result = await _check_watchdog_observer(mock_redis)

    assert result is None  # No issue
    mock_redis.get.assert_called_once_with("watchdog:heartbeat")


@pytest.mark.asyncio
async def test_check_watchdog_observer_inactive(mock_redis):
    """Test Watchdog observer inactif (pas de heartbeat Redis)."""
    # Mock Redis heartbeat key missing
    mock_redis.get.return_value = None

    result = await _check_watchdog_observer(mock_redis)

    assert result is not None
    assert "inactif" in result.lower()


@pytest.mark.asyncio
async def test_check_watchdog_observer_redis_error(mock_redis):
    """Test Watchdog observer check error (Redis exception)."""
    # Mock Redis exception
    mock_redis.get.side_effect = Exception("Redis connection lost")

    result = await _check_watchdog_observer(mock_redis)

    assert result is not None
    assert "failed" in result.lower()


# ============================================================================
# Tests Pipeline Activity Check
# ============================================================================


@pytest.mark.asyncio
async def test_check_pipeline_activity_recent(mock_db_pool):
    """Test pipeline actif (dernière action <24h)."""
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value

    # Mock dernière action il y a 2h
    recent_action = {"created_at": datetime.now() - timedelta(hours=2)}
    conn.fetchrow.return_value = recent_action

    result = await _check_pipeline_activity(mock_db_pool)

    assert result is None  # No issue


@pytest.mark.asyncio
async def test_check_pipeline_activity_inactive_24h(mock_db_pool):
    """Test pipeline inactif (dernière action >24h)."""
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value

    # Mock dernière action il y a 36h
    old_action = {"created_at": datetime.now() - timedelta(hours=36)}
    conn.fetchrow.return_value = old_action

    result = await _check_pipeline_activity(mock_db_pool)

    assert result is not None
    assert "inactif" in result.lower()
    assert "36h" in result


@pytest.mark.asyncio
async def test_check_pipeline_activity_no_history(mock_db_pool):
    """Test pipeline sans historique (système neuf, OK)."""
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value

    # Mock aucune action dans l'historique
    conn.fetchrow.return_value = None

    result = await _check_pipeline_activity(mock_db_pool)

    assert result is None  # No issue (système neuf)


@pytest.mark.asyncio
async def test_check_pipeline_activity_db_error(mock_db_pool):
    """Test pipeline check error (DB exception)."""
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value

    # Mock DB exception
    conn.fetchrow.side_effect = Exception("DB connection lost")

    result = await _check_pipeline_activity(mock_db_pool)

    assert result is not None
    assert "failed" in result.lower()


# ============================================================================
# Tests Check Archiviste Health (Integration)
# ============================================================================


@pytest.mark.asyncio
async def test_check_archiviste_health_all_ok(context_normal, mock_db_pool, mock_redis):
    """Test archiviste healthy (tout OK)."""
    # Mock all checks OK
    with patch("agents.src.core.heartbeat_checks.archiviste_health._check_surya_ocr") as mock_surya:
        with patch(
            "agents.src.core.heartbeat_checks.archiviste_health._check_watchdog_observer"
        ) as mock_watchdog:
            with patch(
                "agents.src.core.heartbeat_checks.archiviste_health._check_pipeline_activity"
            ) as mock_pipeline:
                mock_surya.return_value = None
                mock_watchdog.return_value = None
                mock_pipeline.return_value = None

                result = await check_archiviste_health(
                    context=context_normal, db_pool=mock_db_pool, redis_client=mock_redis
                )

                assert isinstance(result, CheckResult)
                assert result.notify is False
                assert result.message == ""


@pytest.mark.asyncio
async def test_check_archiviste_health_single_issue(context_normal, mock_db_pool, mock_redis):
    """Test archiviste unhealthy (1 problème détecté)."""
    # Mock Surya OCR down
    with patch("agents.src.core.heartbeat_checks.archiviste_health._check_surya_ocr") as mock_surya:
        with patch(
            "agents.src.core.heartbeat_checks.archiviste_health._check_watchdog_observer"
        ) as mock_watchdog:
            with patch(
                "agents.src.core.heartbeat_checks.archiviste_health._check_pipeline_activity"
            ) as mock_pipeline:
                mock_surya.return_value = "Surya OCR unhealthy (HTTP 503)"
                mock_watchdog.return_value = None
                mock_pipeline.return_value = None

                result = await check_archiviste_health(
                    context=context_normal, db_pool=mock_db_pool, redis_client=mock_redis
                )

                assert isinstance(result, CheckResult)
                assert result.notify is True
                assert "problème" in result.message.lower()
                assert "Surya OCR" in result.message
                assert result.payload["severity"] == "medium"


@pytest.mark.asyncio
async def test_check_archiviste_health_multiple_issues(context_normal, mock_db_pool, mock_redis):
    """Test archiviste unhealthy (2+ problèmes détectés, high severity)."""
    # Mock 2 issues
    with patch("agents.src.core.heartbeat_checks.archiviste_health._check_surya_ocr") as mock_surya:
        with patch(
            "agents.src.core.heartbeat_checks.archiviste_health._check_watchdog_observer"
        ) as mock_watchdog:
            with patch(
                "agents.src.core.heartbeat_checks.archiviste_health._check_pipeline_activity"
            ) as mock_pipeline:
                mock_surya.return_value = "Surya OCR timeout"
                mock_watchdog.return_value = "Watchdog observer inactif"
                mock_pipeline.return_value = None

                result = await check_archiviste_health(
                    context=context_normal, db_pool=mock_db_pool, redis_client=mock_redis
                )

                assert isinstance(result, CheckResult)
                assert result.notify is True
                assert "problèmes" in result.message.lower()
                assert "Surya OCR" in result.message
                assert "Watchdog" in result.message
                assert result.payload["severity"] == "high"


@pytest.mark.asyncio
async def test_check_archiviste_health_creates_pool_if_missing(context_normal):
    """Test check crée DB pool si non fourni."""
    import os

    with patch(
        "agents.src.core.heartbeat_checks.archiviste_health.asyncpg.create_pool"
    ) as mock_create:
        with patch(
            "agents.src.core.heartbeat_checks.archiviste_health._check_surya_ocr"
        ) as mock_surya:
            with patch(
                "agents.src.core.heartbeat_checks.archiviste_health._check_watchdog_observer"
            ) as mock_watchdog:
                with patch(
                    "agents.src.core.heartbeat_checks.archiviste_health._check_pipeline_activity"
                ) as mock_pipeline:
                    # Mock DATABASE_URL env var via patch.dict
                    with patch.dict(
                        os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost/db"}
                    ):
                        # Mock pool creation (create_pool est awaitable)
                        mock_pool = AsyncMock()
                        mock_pool.close = AsyncMock()

                        # create_pool() doit retourner un coroutine
                        async def async_create_pool(*args, **kwargs):
                            return mock_pool

                        mock_create.side_effect = async_create_pool

                        # Mock checks OK
                        mock_surya.return_value = None
                        mock_watchdog.return_value = None
                        mock_pipeline.return_value = None

                        result = await check_archiviste_health(context=context_normal)

                        # Vérifier pool créé et fermé
                        mock_create.assert_called_once()
                        mock_pool.close.assert_called_once()


# ============================================================================
# Tests Formatage Notification
# ============================================================================


def test_format_health_notification_single_issue(context_normal):
    """Test formatage notification 1 problème."""
    issues = ["Surya OCR unhealthy (HTTP 503)"]

    message = _format_health_notification(issues, context_normal)

    assert "1 problème détecté" in message
    assert "Surya OCR unhealthy" in message
    assert "/status" in message


def test_format_health_notification_multiple_issues(context_normal):
    """Test formatage notification 2+ problèmes."""
    issues = [
        "Surya OCR timeout",
        "Watchdog observer inactif",
        "Pipeline inactif (36h)",
    ]

    message = _format_health_notification(issues, context_normal)

    assert "3 problèmes détectés" in message
    assert "Surya OCR" in message
    assert "Watchdog" in message
    assert "Pipeline" in message
    assert "/status" in message
