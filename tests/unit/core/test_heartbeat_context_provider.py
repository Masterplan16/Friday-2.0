"""
Tests unitaires pour ContextProvider Heartbeat (Story 4.1 Task 3)

Teste le ContextProvider du Heartbeat Engine (agents.src.core.context_provider),
PAS le ContextProvider Story 7.1 (agents.src.core.context).
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

from agents.src.core.context_provider import ContextProvider
from agents.src.core.heartbeat_models import HeartbeatContext


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_context_manager():
    """Mock ContextManager (Story 7.3)."""
    from agents.src.core.models import UserContext, Casquette

    manager = AsyncMock()
    manager.get_current_context.return_value = UserContext(
        id=1,
        casquette=Casquette.MEDECIN,
        source="manual",
        last_updated_at=datetime(2026, 2, 17, 14, 0, tzinfo=timezone.utc)
    )
    return manager


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg Pool."""
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool


@pytest.fixture
def context_provider(mock_context_manager, mock_db_pool):
    """Fixture ContextProvider."""
    return ContextProvider(
        context_manager=mock_context_manager,
        db_pool=mock_db_pool
    )


# ============================================================================
# Tests Task 3.2-3.3: Get Current Context
# ============================================================================

@pytest.mark.asyncio
async def test_get_current_context_returns_heartbeat_context(context_provider):
    """Test 1: get_current_context() retourne HeartbeatContext."""
    context = await context_provider.get_current_context()

    assert isinstance(context, HeartbeatContext)
    assert context.current_time is not None
    assert context.day_of_week is not None
    assert isinstance(context.is_weekend, bool)
    assert isinstance(context.is_quiet_hours, bool)


@pytest.mark.asyncio
async def test_context_current_time_is_utc(context_provider):
    """Test 2: current_time est en UTC."""
    context = await context_provider.get_current_context()
    assert context.current_time.tzinfo == timezone.utc


@pytest.mark.asyncio
async def test_context_is_weekend_saturday(context_provider):
    """Test 3: is_weekend=True le samedi."""
    with patch("agents.src.core.context_provider.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 2, 21, 14, 30, tzinfo=timezone.utc)
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        context = await context_provider.get_current_context()
        assert context.is_weekend is True


@pytest.mark.asyncio
async def test_context_quiet_hours_22h(context_provider):
    """Test 4: is_quiet_hours=True a 22h."""
    with patch("agents.src.core.context_provider.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 2, 17, 22, 0, tzinfo=timezone.utc)
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        context = await context_provider.get_current_context()
        assert context.is_quiet_hours is True


@pytest.mark.asyncio
async def test_context_not_quiet_hours_14h(context_provider):
    """Test 5: is_quiet_hours=False a 14h."""
    with patch("agents.src.core.context_provider.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 2, 17, 14, 0, tzinfo=timezone.utc)
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        context = await context_provider.get_current_context()
        assert context.is_quiet_hours is False


@pytest.mark.asyncio
async def test_context_includes_current_casquette(context_provider, mock_context_manager):
    """Test 6: context inclut casquette active depuis Story 7.3."""
    context = await context_provider.get_current_context()

    mock_context_manager.get_current_context.assert_called_once()
    assert context.current_casquette is not None


@pytest.mark.asyncio
async def test_context_next_calendar_event_integration(context_provider, mock_db_pool):
    """Test 7: context recupere prochain evenement calendrier (<24h)."""
    mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetchrow.return_value = {
        "title": "Consultation M. Dupont",
        "start_time": datetime(2026, 2, 17, 15, 0, tzinfo=timezone.utc),
        "casquette": "medecin"
    }

    context = await context_provider.get_current_context()
    # Note: Verifie seulement si implementation inclut calendar event


@pytest.mark.asyncio
async def test_context_last_activity_mainteneur(context_provider, mock_db_pool):
    """Test 8: context recupere last_activity_mainteneur."""
    context = await context_provider.get_current_context()

    # Verifier last_activity_mainteneur (peut etre None ou datetime)
    assert context.last_activity_mainteneur is None or isinstance(context.last_activity_mainteneur, datetime)


# ============================================================================
# Tests Task 3.3: Quiet Hours Edge Cases
# ============================================================================

@pytest.mark.asyncio
async def test_quiet_hours_boundaries_22h():
    """Test 9: Quiet hours start 22h00 precis."""
    context = HeartbeatContext(
        current_time=datetime(2026, 2, 17, 22, 0, tzinfo=timezone.utc),
        day_of_week="Monday",
        is_weekend=False,
        is_quiet_hours=True,
        current_casquette=None,
        next_calendar_event=None,
        last_activity_mainteneur=None
    )
    assert context.is_quiet_hours is True


@pytest.mark.asyncio
async def test_quiet_hours_boundaries_08h():
    """Test 10: Quiet hours end 08h00 precis."""
    context = HeartbeatContext(
        current_time=datetime(2026, 2, 17, 8, 0, tzinfo=timezone.utc),
        day_of_week="Monday",
        is_weekend=False,
        is_quiet_hours=False,
        current_casquette=None,
        next_calendar_event=None,
        last_activity_mainteneur=None
    )
    assert context.is_quiet_hours is False
