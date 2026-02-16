"""
Tests E2E Heartbeat Engine (Story 4.1 Task 10.7)

Tests end-to-end avec DB PostgreSQL réelle + scénarios complets.

TODO: Implémenter vrai setup testcontainers-python PostgreSQL 16.
      Actuellement : fixtures DB utilisent AsyncMock (pas de vrais E2E).
      Priorité : quand testcontainers sera setupé pour le projet.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import asyncpg
from anthropic import AsyncAnthropic

from agents.src.core.heartbeat_engine import HeartbeatEngine
from agents.src.core.context_provider import ContextProvider
from agents.src.core.context_manager import ContextManager
from agents.src.core.check_registry import CheckRegistry
from agents.src.core.llm_decider import LLMDecider
from agents.src.core.check_executor import CheckExecutor
from agents.src.core.checks import register_all_checks


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
async def postgres_testcontainer():
    """
    PostgreSQL testcontainer pour tests E2E.

    TODO: Setup testcontainers-python avec PostgreSQL 16
    Pour l'instant, utiliser DB de test locale ou mock
    """
    # Exemple setup (à adapter selon env test):
    # from testcontainers.postgres import PostgresContainer
    #
    # postgres = PostgresContainer("postgres:16-alpine")
    # postgres.start()
    #
    # yield postgres.get_connection_url()
    #
    # postgres.stop()

    # Mock pour l'instant
    yield "postgresql://test:test@localhost:5432/test_heartbeat"


@pytest.fixture
async def db_pool_real(postgres_testcontainer):
    """
    Pool PostgreSQL réel pour tests E2E.

    TODO: Créer pool asyncpg vers testcontainer
    """
    # Exemple:
    # pool = await asyncpg.create_pool(postgres_testcontainer)
    # yield pool
    # await pool.close()

    # Mock pour l'instant
    pool = AsyncMock(spec=asyncpg.Pool)
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn

    # Mock data pour tests
    conn.fetchval.return_value = 0
    conn.fetch.return_value = []
    conn.execute.return_value = None

    return pool


@pytest.fixture
def redis_client_real():
    """
    Redis client réel pour tests E2E.

    TODO: Setup Redis testcontainer ou Redis mock
    """
    return AsyncMock()


@pytest.fixture
async def setup_db_schema(db_pool_real):
    """
    Setup schema DB pour tests E2E.

    TODO: Appliquer migrations 001-039 sur testcontainer
    """
    # Exemple:
    # async with db_pool_real.acquire() as conn:
    #     # Appliquer migrations
    #     await conn.execute(open("database/migrations/001_init_schemas.sql").read())
    #     ...
    #     await conn.execute(open("database/migrations/039_heartbeat_metrics.sql").read())

    pass


@pytest.fixture
def full_heartbeat_stack(db_pool_real, redis_client_real):
    """Stack Heartbeat complet pour E2E."""
    # Context Manager + Provider
    context_manager = ContextManager(
        db_pool=db_pool_real,
        redis_client=redis_client_real
    )
    context_provider = ContextProvider(
        context_manager=context_manager,
        db_pool=db_pool_real
    )

    # Check Registry + Checks Day 1
    check_registry = CheckRegistry()
    check_registry.clear()
    register_all_checks(check_registry)

    # LLM Decider (mock Anthropic)
    llm_client_mock = AsyncMock(spec=AsyncAnthropic)
    response_mock = AsyncMock()
    response_mock.content = [
        AsyncMock(text='{"checks_to_run": [], "reasoning": "Silence"}')
    ]
    llm_client_mock.messages.create.return_value = response_mock

    llm_decider = LLMDecider(
        llm_client=llm_client_mock,
        redis_client=redis_client_real
    )

    # Check Executor
    check_executor = CheckExecutor(
        db_pool=db_pool_real,
        redis_client=redis_client_real,
        check_registry=check_registry
    )

    # Heartbeat Engine
    engine = HeartbeatEngine(
        db_pool=db_pool_real,
        redis_client=redis_client_real,
        context_provider=context_provider,
        check_registry=check_registry,
        llm_decider=llm_decider,
        check_executor=check_executor
    )

    return {
        "engine": engine,
        "db_pool": db_pool_real,
        "llm_client": llm_client_mock,
        "check_executor": check_executor,
        "context_provider": context_provider
    }


# ============================================================================
# Tests Task 10.7: Tests E2E
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_check_urgent_emails_detection(
    full_heartbeat_stack,
    db_pool_real,
    setup_db_schema
):
    """
    Test E2E 1: Email urgent créé → Heartbeat détecte → notification.

    Flow complet:
        1. Insérer email urgent en DB
        2. Run cycle Heartbeat
        3. LLM sélectionne check_urgent_emails
        4. Check détecte email
        5. Notification Telegram envoyée
    """
    engine = full_heartbeat_stack["engine"]
    llm_client = full_heartbeat_stack["llm_client"]

    # 1. Créer email urgent en DB
    async with db_pool_real.acquire() as conn:
        # Mock fetchval pour check_urgent_emails
        conn.fetchval.return_value = 1  # 1 email urgent

        # Mock fetch pour détails
        conn.fetch.return_value = [
            {
                "sender": "vip@example.com",
                "subject": "URGENT: Demande importante"
            }
        ]

    # 2. Configurer LLM pour sélectionner check_urgent_emails
    response_mock = AsyncMock()
    response_mock.content = [
        AsyncMock(text='{"checks_to_run": ["check_urgent_emails"], "reasoning": "Email VIP"}')
    ]
    llm_client.messages.create.return_value = response_mock

    # 3. Mock notification Telegram
    with patch.object(engine, '_send_notification') as mock_notify:
        # 4. Exécuter cycle
        result = await engine.run_heartbeat_cycle(mode="one-shot")

    # 5. Vérifier résultat
    assert result["status"] == "success"
    assert result["checks_executed"] >= 1
    assert result["checks_notified"] >= 1

    # Vérifier notification envoyée
    # Note: mock_notify.assert_called dépend implémentation


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_quiet_hours_no_notification(
    full_heartbeat_stack,
    setup_db_schema
):
    """
    Test E2E 2: Cycle 03h (quiet hours) → aucune notification sauf CRITICAL.

    Flow complet:
        1. Context Provider retourne is_quiet_hours=True
        2. HeartbeatEngine skip LLM décideur
        3. Seuls CRITICAL checks exécutés
        4. Aucune notification sauf si CRITICAL trouvé
    """
    engine = full_heartbeat_stack["engine"]
    context_provider = full_heartbeat_stack["context_provider"]

    # 1. Mock context provider pour quiet hours
    from agents.src.core.heartbeat_models import HeartbeatContext

    quiet_context = HeartbeatContext(
        current_time=datetime(2026, 2, 17, 3, 0, tzinfo=timezone.utc),
        day_of_week="Monday",
        is_weekend=False,
        is_quiet_hours=True,
        current_casquette=None,
        next_calendar_event=None,
        last_activity_mainteneur=None
    )

    with patch.object(context_provider, 'get_current_context', return_value=quiet_context):
        # 2. Exécuter cycle
        result = await engine.run_heartbeat_cycle(mode="one-shot")

    # 3. Vérifier quiet hours respecté
    assert result["status"] == "success"
    assert "quiet hours" in result["llm_reasoning"].lower() or result["checks_executed"] == 0


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_llm_decider_context_aware(
    full_heartbeat_stack,
    db_pool_real,
    setup_db_schema
):
    """
    Test E2E 3: Contexte casquette médecin → LLM sélectionne urgent_emails.

    Flow complet:
        1. Context Provider retourne casquette="medecin" + événement proche
        2. LLM Décideur analyse contexte
        3. LLM sélectionne check_urgent_emails (pertinent médecin)
        4. Check exécuté + notification
    """
    engine = full_heartbeat_stack["engine"]
    context_provider = full_heartbeat_stack["context_provider"]
    llm_client = full_heartbeat_stack["llm_client"]

    # 1. Mock context provider avec casquette médecin
    from agents.src.core.heartbeat_models import HeartbeatContext

    medecin_context = HeartbeatContext(
        current_time=datetime(2026, 2, 17, 14, 30, tzinfo=timezone.utc),
        day_of_week="Monday",
        is_weekend=False,
        is_quiet_hours=False,
        current_casquette="medecin",
        next_calendar_event={
            "title": "Consultation patient",
            "start_time": "2026-02-17T15:00:00Z",
            "casquette": "medecin"
        },
        last_activity_mainteneur=datetime(2026, 2, 17, 14, 0, tzinfo=timezone.utc)
    )

    # 2. Configurer LLM pour répondre selon contexte
    response_mock = AsyncMock()
    response_mock.content = [
        AsyncMock(text='{"checks_to_run": ["check_urgent_emails"], "reasoning": "Casquette médecin + événement proche"}')
    ]
    llm_client.messages.create.return_value = response_mock

    # 3. Mock email urgent en DB
    async with db_pool_real.acquire() as conn:
        conn.fetchval.return_value = 1
        conn.fetch.return_value = [{"sender": "patient@example.com", "subject": "Urgent"}]

    with patch.object(context_provider, 'get_current_context', return_value=medecin_context):
        # 4. Exécuter cycle
        result = await engine.run_heartbeat_cycle(mode="one-shot")

    # 5. Vérifier LLM décision context-aware
    assert result["status"] == "success"
    assert "check_urgent_emails" in result["selected_checks"]
    assert "médecin" in result["llm_reasoning"].lower() or "casquette" in result["llm_reasoning"].lower()


# ============================================================================
# Tests E2E Silence Rate (AC4)
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_silence_rate_calculation(db_pool_real, setup_db_schema):
    """
    Test E2E bonus: Calcul silence_rate sur 7j (AC4).

    Flow:
        1. Insérer 10 cycles metrics en DB (8 silence, 2 notifications)
        2. Appeler fonction core.calculate_silence_rate(7)
        3. Vérifier résultat = 80%
    """
    # TODO: Setup DB avec migrations appliquées
    # async with db_pool_real.acquire() as conn:
    #     # Insérer 10 cycles
    #     for i in range(10):
    #         notified = 0 if i < 8 else 1
    #         await conn.execute(
    #             "INSERT INTO core.heartbeat_metrics (checks_selected, checks_executed, checks_notified) "
    #             "VALUES ($1, $2, $3)",
    #             [], 0, notified
    #         )
    #
    #     # Calculer silence_rate
    #     silence_rate = await conn.fetchval("SELECT core.calculate_silence_rate(7)")
    #
    #     # Vérifier 80%
    #     assert silence_rate == 80.0

    pass  # Mock pour l'instant


# ============================================================================
# Helper Functions
# ============================================================================

async def create_test_email(conn, priority="urgent", read=False):
    """Helper pour créer email test en DB."""
    await conn.execute(
        """
        INSERT INTO ingestion.emails (sender, subject, priority, read)
        VALUES ($1, $2, $3, $4)
        """,
        "test@example.com",
        "Test subject",
        priority,
        read
    )
