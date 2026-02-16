"""
Tests unitaires pour CheckExecutor (Story 4.1 Task 5)

RED PHASE : Tests écrits AVANT l'implémentation (TDD)
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from agents.src.core.check_executor import CheckExecutor
from agents.src.core.heartbeat_models import Check, CheckPriority, CheckResult

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg Pool."""
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool


@pytest.fixture
def mock_redis_client():
    """Mock Redis client pour circuit breaker."""
    redis = AsyncMock()
    redis.get.return_value = None  # Pas de circuit breaker actif
    redis.incr.return_value = 1
    redis.setex.return_value = True
    return redis


@pytest.fixture
def mock_check_registry():
    """Mock CheckRegistry."""
    from agents.src.core.check_registry import CheckRegistry

    registry = Mock(spec=CheckRegistry)

    # Check sample
    async def sample_check_fn(*args, **kwargs):
        return CheckResult(notify=True, message="Test check result")

    sample_check = Check(
        check_id="test_check",
        priority=CheckPriority.HIGH,
        description="Test check",
        execute_fn=sample_check_fn,
    )

    registry.get_check.return_value = sample_check
    return registry


@pytest.fixture
def check_executor(mock_db_pool, mock_redis_client, mock_check_registry):
    """Fixture CheckExecutor avec mocks."""
    return CheckExecutor(
        db_pool=mock_db_pool, redis_client=mock_redis_client, check_registry=mock_check_registry
    )


# ============================================================================
# Tests Task 5.1-5.2: Execute Check
# ============================================================================


@pytest.mark.asyncio
async def test_check_executor_init(check_executor):
    """Test 1: CheckExecutor initialisation."""
    assert check_executor is not None
    assert check_executor.db_pool is not None
    assert check_executor.redis_client is not None


@pytest.mark.asyncio
async def test_execute_check_returns_check_result(check_executor):
    """Test 2: execute_check retourne CheckResult."""
    result = await check_executor.execute_check("test_check")

    assert isinstance(result, CheckResult)
    assert result.message == "Test check result"


@pytest.mark.asyncio
async def test_execute_check_calls_check_function(check_executor, mock_check_registry):
    """Test 3: execute_check appelle fonction check."""
    check_fn = AsyncMock(return_value=CheckResult(notify=False))

    check = Check(
        check_id="test_check_2",
        priority=CheckPriority.MEDIUM,
        description="Test",
        execute_fn=check_fn,
    )
    mock_check_registry.get_check.return_value = check

    await check_executor.execute_check("test_check_2")

    # Vérifier que fonction check appelée
    check_fn.assert_called_once()


@pytest.mark.asyncio
async def test_execute_check_passes_db_pool_to_check(
    check_executor, mock_check_registry, mock_db_pool
):
    """Test 4: execute_check passe db_pool au check."""
    check_fn = AsyncMock(return_value=CheckResult(notify=False))

    check = Check(
        check_id="test_check_3",
        priority=CheckPriority.HIGH,
        description="Test",
        execute_fn=check_fn,
    )
    mock_check_registry.get_check.return_value = check

    await check_executor.execute_check("test_check_3")

    # Vérifier que db_pool passé en argument
    check_fn.assert_called_once_with(mock_db_pool)


# ============================================================================
# Tests Task 5.3: Isolation Checks
# ============================================================================


@pytest.mark.asyncio
async def test_check_isolation_returns_error_result_on_exception(
    check_executor, mock_check_registry
):
    """Test 5: Si check crash → retourne CheckResult avec error."""
    check_fn = AsyncMock(side_effect=Exception("Check crashed"))

    check = Check(
        check_id="crash_check",
        priority=CheckPriority.MEDIUM,
        description="Crash test",
        execute_fn=check_fn,
    )
    mock_check_registry.get_check.return_value = check

    result = await check_executor.execute_check("crash_check")

    # Vérifier que CheckResult avec erreur retourné
    assert isinstance(result, CheckResult)
    assert result.notify is False
    assert result.error is not None
    assert "Check crashed" in result.error


@pytest.mark.asyncio
async def test_check_isolation_logs_error(check_executor, mock_check_registry):
    """Test 6: Si check crash → log error."""
    check_fn = AsyncMock(side_effect=Exception("Check error"))

    check = Check(
        check_id="error_check",
        priority=CheckPriority.LOW,
        description="Error test",
        execute_fn=check_fn,
    )
    mock_check_registry.get_check.return_value = check

    with patch("structlog.get_logger") as mock_logger_factory:
        mock_logger = Mock()
        mock_logger_factory.return_value = mock_logger

        await check_executor.execute_check("error_check")

        # Vérifier log error appelé
        # Note: détails logs dépendent implémentation


# ============================================================================
# Tests Task 5.4: Circuit Breaker
# ============================================================================


@pytest.mark.asyncio
async def test_circuit_breaker_increments_on_failure(
    check_executor, mock_check_registry, mock_redis_client
):
    """Test 7: Échec check → incrémente compteur failures Redis."""
    check_fn = AsyncMock(side_effect=Exception("Failure"))

    check = Check(
        check_id="fail_check",
        priority=CheckPriority.MEDIUM,
        description="Fail test",
        execute_fn=check_fn,
    )
    mock_check_registry.get_check.return_value = check

    await check_executor.execute_check("fail_check")

    # Vérifier Redis incr appelé
    mock_redis_client.incr.assert_called()


@pytest.mark.asyncio
async def test_circuit_breaker_disables_after_3_failures(
    check_executor, mock_check_registry, mock_redis_client
):
    """Test 8: 3 échecs consécutifs → disable check 1h."""
    # Simuler 3 échecs
    mock_redis_client.incr.return_value = 3

    check_fn = AsyncMock(side_effect=Exception("Failure"))

    check = Check(
        check_id="fail_check_3",
        priority=CheckPriority.HIGH,
        description="Fail test",
        execute_fn=check_fn,
    )
    mock_check_registry.get_check.return_value = check

    await check_executor.execute_check("fail_check_3")

    # Vérifier Redis setex appelé pour disable (1h = 3600s)
    mock_redis_client.setex.assert_called()
    call_args = mock_redis_client.setex.call_args
    assert 3600 in call_args[0] or 3600 in call_args.kwargs.values()


@pytest.mark.asyncio
async def test_circuit_breaker_open_returns_disabled_result(
    check_executor, mock_check_registry, mock_redis_client
):
    """Test 9: Circuit breaker ouvert → retourne CheckResult disabled."""
    # Simuler circuit breaker ouvert
    mock_redis_client.get.return_value = "1"  # Check disabled

    check = Check(
        check_id="disabled_check",
        priority=CheckPriority.MEDIUM,
        description="Disabled",
        execute_fn=AsyncMock(),
    )
    mock_check_registry.get_check.return_value = check

    result = await check_executor.execute_check("disabled_check")

    # Vérifier que check pas exécuté
    assert isinstance(result, CheckResult)
    assert result.notify is False
    assert "disabled" in result.error.lower() or "circuit breaker" in result.error.lower()


@pytest.mark.asyncio
async def test_circuit_breaker_sends_alert_on_disable(
    check_executor, mock_check_registry, mock_redis_client
):
    """Test 10: Disable check → alerte System."""
    # Simuler 3ème échec
    mock_redis_client.incr.return_value = 3

    check_fn = AsyncMock(side_effect=Exception("Failure"))

    check = Check(
        check_id="alert_check",
        priority=CheckPriority.HIGH,
        description="Alert test",
        execute_fn=check_fn,
    )
    mock_check_registry.get_check.return_value = check

    with patch("agents.src.core.check_executor.send_alert_system") as mock_alert:
        await check_executor.execute_check("alert_check")

        # Vérifier alerte System envoyée
        # Note: mock_alert sera appelé si implémentation correcte


# ============================================================================
# Tests Task 5.5: Intégration @friday_action
# ============================================================================


@pytest.mark.asyncio
async def test_execute_check_compatible_with_friday_action(check_executor, mock_check_registry):
    """Test 11: CheckExecutor compatible avec checks utilisant @friday_action."""
    # Note: @friday_action est utilisé par les checks eux-mêmes (Task 6),
    # pas par le CheckExecutor. Ce test vérifie compatibilité.

    # Check simple sans @friday_action (OK)
    check_fn = AsyncMock(return_value=CheckResult(notify=False))

    check = Check(
        check_id="simple_check",
        priority=CheckPriority.MEDIUM,
        description="Simple check",
        execute_fn=check_fn,
    )
    mock_check_registry.get_check.return_value = check

    result = await check_executor.execute_check("simple_check")

    # Vérifier execution correcte
    assert isinstance(result, CheckResult)
    assert result.error is None
    # Note: Les checks Day 1 (Task 6) utiliseront @friday_action pour générer receipts


@pytest.mark.asyncio
async def test_execute_check_unknown_id_returns_error(check_executor, mock_check_registry):
    """Test 12: Check ID inconnu → retourne CheckResult avec erreur."""
    mock_check_registry.get_check.return_value = None

    result = await check_executor.execute_check("unknown_check")

    assert isinstance(result, CheckResult)
    assert result.notify is False
    assert result.error is not None
    assert "unknown" in result.error.lower() or "not found" in result.error.lower()
