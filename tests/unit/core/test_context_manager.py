"""
Tests Unitaires - Context Manager

Story 7.3: Multi-casquettes & Conflits Calendrier (AC1)

Tests:
- Détection contexte événement en cours
- Détection contexte heuristique heure
- Priorité manuel > événement
- Fallback dernier événement
- Défaut NULL si aucune règle
- Cache Redis évite double query
- Transition contexte logged
- Singleton user_context UPDATE pas INSERT
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agents.src.core.context_manager import ContextManager, get_context_manager
from agents.src.core.models import Casquette, ContextSource, OngoingEvent, UserContext

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg.Pool."""
    pool = MagicMock()
    conn = AsyncMock()
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = acquire_cm
    return pool, conn


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis_client = AsyncMock()
    # Simule cache miss par défaut (évite json.loads sur AsyncMock)
    redis_client.get.return_value = None
    return redis_client


@pytest.fixture
def context_manager(mock_db_pool, mock_redis):
    """Instance ContextManager avec mocks."""
    pool, _ = mock_db_pool
    return ContextManager(db_pool=pool, redis_client=mock_redis, cache_ttl=300)


# ============================================================================
# Tests Détection Contexte
# ============================================================================


@pytest.mark.asyncio
async def test_context_auto_detect_from_ongoing_event(context_manager, mock_db_pool):
    """Test AC1: Détection contexte depuis événement en cours."""
    _, conn = mock_db_pool

    # Mock: Événement en cours (14h00-15h00, médecin)
    now = datetime.now()
    start_time = now.replace(hour=14, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=0, second=0, microsecond=0)

    event_id = uuid4()
    conn.fetchrow = AsyncMock(
        side_effect=[
            # 1er appel: user_context (updated_by='system')
            {"id": 1, "current_casquette": None, "last_updated_at": now, "updated_by": "system"},
            # 2ème appel: ongoing event
            {
                "id": event_id,
                "casquette": "medecin",
                "title": "Consultation Dr Dupont",
                "start_datetime": start_time,
                "end_datetime": end_time,
            },
        ]
    )

    # Mock cache Redis miss
    context_manager.redis_client.get.return_value = None

    # Get context
    context = await context_manager.get_current_context()

    # Assertions
    assert context.casquette == Casquette.MEDECIN
    assert context.source == ContextSource.EVENT
    assert context.updated_by == "system"


@pytest.mark.asyncio
async def test_context_auto_detect_from_time_heuristic(context_manager, mock_db_pool):
    """Test AC1: Détection contexte heuristique heure (14h00-16h00 → enseignant)."""
    _, conn = mock_db_pool

    # Mock: user_context (auto-detect)
    now = datetime.now().replace(hour=15, minute=0)  # 15h00 = enseignant
    conn.fetchrow = AsyncMock(
        side_effect=[
            # 1er appel: user_context
            {"id": 1, "current_casquette": None, "last_updated_at": now, "updated_by": "system"},
            # 2ème appel: ongoing event (None)
            None,
            # 3ème appel: last event (None)
            None,
        ]
    )

    # Mock cache Redis miss
    context_manager.redis_client.get.return_value = None

    # Get context (avec patch datetime.now pour fixer heure)
    with patch("agents.src.core.context_manager.datetime") as mock_datetime:
        mock_datetime.now.return_value = now

        context = await context_manager.get_current_context()

    # Assertions
    assert context.casquette == Casquette.ENSEIGNANT
    assert context.source == ContextSource.TIME


@pytest.mark.asyncio
async def test_context_manual_overrides_auto_detect(context_manager, mock_db_pool):
    """Test AC1: Priorité manuel > auto-detect."""
    _, conn = mock_db_pool

    # Mock: user_context (updated_by='manual' → pas d'auto-detect)
    now = datetime.now()
    conn.fetchrow = AsyncMock(
        return_value={
            "id": 1,
            "current_casquette": "chercheur",
            "last_updated_at": now,
            "updated_by": "manual",
        }
    )

    # Mock cache Redis miss
    context_manager.redis_client.get.return_value = None

    # Get context
    context = await context_manager.get_current_context()

    # Assertions
    assert context.casquette == Casquette.CHERCHEUR
    assert context.source == ContextSource.MANUAL
    assert context.updated_by == "manual"

    # Vérifier qu'aucun appel auto-detect (pas de 2ème fetchrow)
    assert conn.fetchrow.call_count == 1


@pytest.mark.asyncio
async def test_context_fallback_last_event(context_manager, mock_db_pool):
    """Test AC1: Fallback dernier événement passé."""
    _, conn = mock_db_pool

    now = datetime.now()
    conn.fetchrow = AsyncMock(
        side_effect=[
            # 1er appel: user_context (auto-detect)
            {"id": 1, "current_casquette": None, "last_updated_at": now, "updated_by": "system"},
            # 2ème appel: ongoing event (None)
            None,
            # 3ème appel: last event (médecin)
            {"casquette": "medecin"},
        ]
    )

    # Mock cache Redis miss
    context_manager.redis_client.get.return_value = None

    # Get context (heure sans mapping → skip TIME rule)
    with patch("agents.src.core.context_manager.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime.now().replace(hour=20, minute=0)

        context = await context_manager.get_current_context()

    # Assertions
    assert context.casquette == Casquette.MEDECIN
    assert context.source == ContextSource.LAST_EVENT


@pytest.mark.asyncio
async def test_context_default_null_if_no_rules(context_manager, mock_db_pool):
    """Test AC1: Défaut NULL si aucune règle applicable."""
    _, conn = mock_db_pool

    now = datetime.now()
    conn.fetchrow = AsyncMock(
        side_effect=[
            # 1er appel: user_context (auto-detect)
            {"id": 1, "current_casquette": None, "last_updated_at": now, "updated_by": "system"},
            # 2ème appel: ongoing event (None)
            None,
            # 3ème appel: last event (None)
            None,
        ]
    )

    # Mock cache Redis miss
    context_manager.redis_client.get.return_value = None

    # Get context (heure sans mapping)
    with patch("agents.src.core.context_manager.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime.now().replace(hour=20, minute=0)

        context = await context_manager.get_current_context()

    # Assertions
    assert context.casquette is None
    assert context.source == ContextSource.DEFAULT


# ============================================================================
# Tests Cache Redis
# ============================================================================


@pytest.mark.asyncio
async def test_context_cache_redis_avoids_double_query(context_manager, mock_db_pool):
    """Test: Cache Redis évite double query PostgreSQL."""
    _, conn = mock_db_pool

    # Mock: Cache hit
    import json

    cached_data = json.dumps(
        {
            "casquette": "medecin",
            "source": "event",
            "updated_at": datetime.now().isoformat(),
            "updated_by": "system",
        }
    )
    context_manager.redis_client.get.return_value = cached_data

    # Get context
    context = await context_manager.get_current_context()

    # Assertions
    assert context.casquette == Casquette.MEDECIN
    assert context.source == ContextSource.EVENT

    # Vérifier qu'aucun query PostgreSQL (cache hit)
    assert conn.fetchrow.call_count == 0

    # Vérifier appel Redis GET
    context_manager.redis_client.get.assert_called_once_with("user:context")


@pytest.mark.asyncio
async def test_context_set_invalidates_cache(context_manager, mock_db_pool):
    """Test: set_context() invalide cache Redis."""
    _, conn = mock_db_pool

    # Mock: UPDATE user_context
    conn.execute = AsyncMock()

    # Mock: Après invalidation cache, get_current_context() fait query DB
    now = datetime.now()
    conn.fetchrow = AsyncMock(
        return_value={
            "id": 1,
            "current_casquette": "enseignant",
            "last_updated_at": now,
            "updated_by": "manual",
        }
    )

    # Mock cache Redis miss après invalidation
    context_manager.redis_client.get.return_value = None

    # Set context
    context = await context_manager.set_context(Casquette.ENSEIGNANT, source="manual")

    # Assertions
    assert context.casquette == Casquette.ENSEIGNANT
    assert context.source == ContextSource.MANUAL

    # Vérifier invalidation cache (DELETE key)
    context_manager.redis_client.delete.assert_called_with("user:context")

    # Vérifier UPDATE PostgreSQL
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args[0]
    assert "UPDATE core.user_context" in call_args[0]


# ============================================================================
# Tests Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_context_transition_logged(context_manager, mock_db_pool):
    """Test: Transition contexte logged (structlog)."""
    import structlog.testing

    _, conn = mock_db_pool

    # Mock: UPDATE context
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "id": 1,
            "current_casquette": "chercheur",
            "last_updated_at": datetime.now(),
            "updated_by": "manual",
        }
    )

    # Mock cache Redis miss
    context_manager.redis_client.get.return_value = None

    # Set context
    with structlog.testing.capture_logs() as cap_logs:
        await context_manager.set_context(Casquette.CHERCHEUR, source="manual")

    # Vérifier log "context_updated"
    assert any(log.get("event") == "context_updated" for log in cap_logs)


@pytest.mark.asyncio
async def test_context_singleton_user_context_update_not_insert(context_manager, mock_db_pool):
    """Test: user_context singleton → UPDATE pas INSERT."""
    _, conn = mock_db_pool

    # Mock: UPDATE (pas INSERT)
    conn.execute = AsyncMock()
    # fetchrow appelé par get_current_context() après set_context()
    # Retourner un row manuel valide pour éviter d'autres requêtes DB
    conn.fetchrow = AsyncMock(
        return_value={
            "id": 1,
            "current_casquette": "medecin",
            "last_updated_at": datetime.now(),
            "updated_by": "manual",
        }
    )

    # Set context
    await context_manager.set_context(Casquette.MEDECIN, source="manual")

    # Vérifier query est UPDATE (pas INSERT)
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args[0]
    query = call_args[0]

    assert "UPDATE core.user_context" in query
    assert "INSERT" not in query
    assert "WHERE id = 1" in query


@pytest.mark.asyncio
async def test_get_context_manager_factory():
    """Test: Factory function get_context_manager()."""
    mock_pool = AsyncMock()
    mock_redis = AsyncMock()

    manager = await get_context_manager(db_pool=mock_pool, redis_client=mock_redis)

    assert isinstance(manager, ContextManager)
    assert manager.db_pool == mock_pool
    assert manager.redis_client == mock_redis
    assert manager.cache_ttl == 300


# ============================================================================
# Tests Time Heuristic Rules
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hour,expected_casquette",
    [
        (9, Casquette.MEDECIN),  # 09:00 → médecin (08:00-12:00)
        (11, Casquette.MEDECIN),  # 11:00 → médecin
        (14, Casquette.ENSEIGNANT),  # 14:00 → enseignant (14:00-16:00)
        (15, Casquette.ENSEIGNANT),  # 15:00 → enseignant
        (17, Casquette.CHERCHEUR),  # 17:00 → chercheur (16:00-18:00)
        (20, None),  # 20:00 → None (hors plages)
    ],
)
async def test_time_heuristic_mapping(context_manager, mock_db_pool, hour, expected_casquette):
    """Test: Mapping heure → casquette (AC1 Règle 3)."""
    _, conn = mock_db_pool

    # Mock: user_context (auto-detect)
    test_time = datetime.now().replace(hour=hour, minute=0)
    conn.fetchrow = AsyncMock(
        side_effect=[
            # 1er appel: user_context
            {
                "id": 1,
                "current_casquette": None,
                "last_updated_at": test_time,
                "updated_by": "system",
            },
            # 2ème appel: ongoing event (None)
            None,
            # 3ème appel: last event (None si expected_casquette None)
            None,
        ]
    )

    # Mock cache Redis miss
    context_manager.redis_client.get.return_value = None

    # Get context
    with patch("agents.src.core.context_manager.datetime") as mock_datetime:
        mock_datetime.now.return_value = test_time

        context = await context_manager.get_current_context()

    # Assertions
    if expected_casquette:
        assert context.casquette == expected_casquette
        assert context.source == ContextSource.TIME
    else:
        # Hors plages → fallback DEFAULT
        assert context.casquette is None
        assert context.source == ContextSource.DEFAULT
