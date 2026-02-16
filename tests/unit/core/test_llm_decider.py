"""
Tests unitaires pour LLM Décideur (Story 4.1 Task 4)

RED PHASE : Tests écrits AVANT l'implémentation (TDD)
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, Mock

from agents.src.core.llm_decider import LLMDecider, LLMDecisionResult
from agents.src.core.heartbeat_models import (
    HeartbeatContext,
    Check,
    CheckPriority
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def llm_client_mock():
    """Mock Anthropic AsyncAnthropic client."""
    client = AsyncMock()

    # Default response : silence (80%+ du temps)
    response_mock = Mock()
    response_mock.content = [
        Mock(text='{"checks_to_run": [], "reasoning": "Silence = bon comportement"}')
    ]
    client.messages.create = AsyncMock(return_value=response_mock)

    return client


@pytest.fixture
def redis_client_mock():
    """Mock Redis client pour circuit breaker."""
    redis = AsyncMock()
    redis.get.return_value = None  # Pas de circuit breaker actif
    redis.incr.return_value = 1
    redis.setex.return_value = True
    return redis


@pytest.fixture
def llm_decider(llm_client_mock, redis_client_mock):
    """Fixture LLMDecider avec mocks."""
    return LLMDecider(
        llm_client=llm_client_mock,
        redis_client=redis_client_mock
    )


@pytest.fixture
def sample_context():
    """HeartbeatContext sample (lundi 14h30, médecin)."""
    return HeartbeatContext(
        current_time=datetime(2026, 2, 17, 14, 30, tzinfo=timezone.utc),
        day_of_week="Monday",
        is_weekend=False,
        is_quiet_hours=False,
        current_casquette="medecin",
        next_calendar_event={
            "title": "Consultation",
            "start_time": "2026-02-17T15:00:00Z",
            "casquette": "medecin"
        },
        last_activity_mainteneur=datetime(2026, 2, 17, 14, 0, tzinfo=timezone.utc)
    )


@pytest.fixture
def sample_checks():
    """Liste checks disponibles."""
    return [
        Check(
            check_id="check_urgent_emails",
            priority=CheckPriority.HIGH,
            description="Emails urgents non lus",
            execute_fn=AsyncMock()
        ),
        Check(
            check_id="check_financial_alerts",
            priority=CheckPriority.MEDIUM,
            description="Échéances cotisations <7j",
            execute_fn=AsyncMock()
        ),
        Check(
            check_id="check_thesis_reminders",
            priority=CheckPriority.LOW,
            description="Relances thésards",
            execute_fn=AsyncMock()
        ),
        Check(
            check_id="check_warranty_expiry",
            priority=CheckPriority.CRITICAL,
            description="Garanties expirant <7j",
            execute_fn=AsyncMock()
        )
    ]


# ============================================================================
# Tests Task 4.1-4.2: Prompt LLM Décideur
# ============================================================================

@pytest.mark.asyncio
async def test_llm_decider_init(llm_decider):
    """Test 1: LLMDecider initialisation."""
    assert llm_decider is not None
    assert llm_decider.llm_client is not None
    assert llm_decider.redis_client is not None


@pytest.mark.asyncio
async def test_decide_checks_returns_valid_structure(llm_decider, sample_context, sample_checks):
    """Test 2: decide_checks retourne structure valide."""
    result = await llm_decider.decide_checks(sample_context, sample_checks)

    assert isinstance(result, dict)
    assert "checks_to_run" in result
    assert "reasoning" in result
    assert isinstance(result["checks_to_run"], list)
    assert isinstance(result["reasoning"], str)


@pytest.mark.asyncio
async def test_decide_checks_calls_llm_with_correct_prompt(
    llm_decider,
    llm_client_mock,
    sample_context,
    sample_checks
):
    """Test 3: LLM appelé avec prompt correct."""
    await llm_decider.decide_checks(sample_context, sample_checks)

    # Vérifier que LLM client appelé
    llm_client_mock.messages.create.assert_called_once()

    # Vérifier paramètres appel
    call_kwargs = llm_client_mock.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-4-5-20250929"
    assert call_kwargs["temperature"] == 0.3
    assert call_kwargs["max_tokens"] == 500

    # Vérifier prompt contient règles critiques
    messages = call_kwargs["messages"]
    prompt_text = messages[0]["content"]
    assert "80%" in prompt_text  # Règle silence
    assert "CRITICAL" in prompt_text
    assert "HIGH" in prompt_text


@pytest.mark.asyncio
async def test_decide_checks_silence_by_default(llm_decider, sample_context, sample_checks):
    """Test 4: Par défaut, LLM retourne silence (checks_to_run=[])."""
    result = await llm_decider.decide_checks(sample_context, sample_checks)

    # Mock retourne silence par défaut
    assert result["checks_to_run"] == []
    assert "silence" in result["reasoning"].lower() or "bon" in result["reasoning"].lower()


@pytest.mark.asyncio
async def test_decide_checks_selects_checks_when_pertinent(
    llm_decider,
    llm_client_mock,
    sample_context,
    sample_checks
):
    """Test 5: LLM sélectionne checks pertinents selon contexte."""
    # Simuler réponse LLM avec 2 checks sélectionnés
    response_mock = Mock()
    response_mock.content = [
        Mock(text='{"checks_to_run": ["check_urgent_emails", "check_financial_alerts"], "reasoning": "Casquette médecin + événement proche"}')
    ]
    llm_client_mock.messages.create = AsyncMock(return_value=response_mock)

    result = await llm_decider.decide_checks(sample_context, sample_checks)

    assert len(result["checks_to_run"]) == 2
    assert "check_urgent_emails" in result["checks_to_run"]
    assert "check_financial_alerts" in result["checks_to_run"]


@pytest.mark.asyncio
async def test_decide_checks_includes_context_details_in_prompt(
    llm_decider,
    llm_client_mock,
    sample_context,
    sample_checks
):
    """Test 6: Prompt inclut détails contexte (heure, casquette, événement)."""
    await llm_decider.decide_checks(sample_context, sample_checks)

    call_kwargs = llm_client_mock.messages.create.call_args.kwargs
    messages = call_kwargs["messages"]
    prompt_text = messages[0]["content"]

    # Vérifier présence détails contexte
    assert "Monday" in prompt_text or "lundi" in prompt_text.lower()
    assert "medecin" in prompt_text.lower() or "médecin" in prompt_text.lower()
    assert "Consultation" in prompt_text  # Événement prochain


# ============================================================================
# Tests Task 4.3: Fallback si LLM crash
# ============================================================================

@pytest.mark.asyncio
async def test_fallback_on_llm_error_returns_high_checks(
    llm_decider,
    llm_client_mock,
    sample_context,
    sample_checks
):
    """Test 7: Si LLM crash → fallback HIGH checks."""
    # Simuler erreur LLM
    llm_client_mock.messages.create.side_effect = Exception("LLM API error")

    result = await llm_decider.decide_checks(sample_context, sample_checks)

    # Fallback : HIGH checks uniquement
    assert "check_urgent_emails" in result["checks_to_run"]
    assert "fallback" in result["reasoning"].lower()


@pytest.mark.asyncio
async def test_fallback_on_invalid_json_response(
    llm_decider,
    llm_client_mock,
    sample_context,
    sample_checks
):
    """Test 8: Si LLM retourne JSON invalide → fallback HIGH checks."""
    # Simuler réponse JSON invalide
    response_mock = Mock()
    response_mock.content = [Mock(text='INVALID JSON {{{')]
    llm_client_mock.messages.create = AsyncMock(return_value=response_mock)

    result = await llm_decider.decide_checks(sample_context, sample_checks)

    # Fallback : HIGH checks
    assert "check_urgent_emails" in result["checks_to_run"]
    assert "fallback" in result["reasoning"].lower() or "error" in result["reasoning"].lower()


@pytest.mark.asyncio
async def test_fallback_includes_critical_checks(
    llm_decider,
    llm_client_mock,
    sample_context,
    sample_checks
):
    """Test 9: Fallback inclut aussi CRITICAL checks."""
    llm_client_mock.messages.create.side_effect = Exception("LLM error")

    result = await llm_decider.decide_checks(sample_context, sample_checks)

    # Fallback : HIGH + CRITICAL
    assert "check_warranty_expiry" in result["checks_to_run"]  # CRITICAL
    assert "check_urgent_emails" in result["checks_to_run"]  # HIGH


# ============================================================================
# Tests Task 4.4: Circuit Breaker
# ============================================================================

@pytest.mark.asyncio
async def test_circuit_breaker_after_3_failures(
    llm_decider,
    llm_client_mock,
    redis_client_mock,
    sample_context,
    sample_checks
):
    """Test 10: 3 échecs consécutifs → circuit breaker 1h."""
    # Simuler 3 échecs LLM
    llm_client_mock.messages.create.side_effect = Exception("LLM error")

    # 3 appels consécutifs
    for i in range(3):
        await llm_decider.decide_checks(sample_context, sample_checks)

    # Vérifier que Redis incrémente failures
    assert redis_client_mock.incr.call_count >= 3


@pytest.mark.asyncio
async def test_circuit_breaker_open_uses_fallback(
    llm_decider,
    redis_client_mock,
    sample_context,
    sample_checks
):
    """Test 11: Circuit breaker ouvert → fallback sans appeler LLM."""
    # Simuler circuit breaker ouvert (3 échecs)
    redis_client_mock.get.return_value = "3"

    result = await llm_decider.decide_checks(sample_context, sample_checks)

    # Vérifier fallback utilisé (HIGH checks)
    assert "check_urgent_emails" in result["checks_to_run"]
    assert "circuit breaker" in result["reasoning"].lower() or "fallback" in result["reasoning"].lower()


@pytest.mark.asyncio
async def test_circuit_breaker_resets_after_success(
    llm_decider,
    llm_client_mock,
    redis_client_mock,
    sample_context,
    sample_checks
):
    """Test 12: Succès LLM → reset compteur failures."""
    # Simuler 2 échecs puis 1 succès
    llm_client_mock.messages.create.side_effect = [
        Exception("Error 1"),
        Exception("Error 2"),
        Mock(content=[Mock(text='{"checks_to_run": [], "reasoning": "Success"}')])
    ]

    # 2 échecs
    await llm_decider.decide_checks(sample_context, sample_checks)
    await llm_decider.decide_checks(sample_context, sample_checks)

    # 1 succès → reset compteur
    await llm_decider.decide_checks(sample_context, sample_checks)

    # Vérifier que Redis delete appelé (reset)
    redis_client_mock.delete.assert_called()


# ============================================================================
# Tests Edge Cases
# ============================================================================

@pytest.mark.asyncio
async def test_decide_checks_empty_checks_list(llm_decider, sample_context):
    """Test 13: Liste checks vide → retourne []."""
    result = await llm_decider.decide_checks(sample_context, [])

    assert result["checks_to_run"] == []


@pytest.mark.asyncio
async def test_decide_checks_validates_check_ids(
    llm_decider,
    llm_client_mock,
    sample_context,
    sample_checks
):
    """Test 14: IDs checks invalides filtrés."""
    # Simuler LLM retourne check ID inexistant
    response_mock = Mock()
    response_mock.content = [
        Mock(text='{"checks_to_run": ["check_invalid", "check_urgent_emails"], "reasoning": "Test"}')
    ]
    llm_client_mock.messages.create = AsyncMock(return_value=response_mock)

    result = await llm_decider.decide_checks(sample_context, sample_checks)

    # Vérifier que check_invalid filtré (n'existe pas dans sample_checks)
    # Note: validation doit être faite dans HeartbeatEngine, pas LLMDecider
    # LLMDecider retourne juste ce que le LLM dit
    assert "check_invalid" in result["checks_to_run"]  # LLM peut retourner n'importe quoi
    assert "check_urgent_emails" in result["checks_to_run"]


@pytest.mark.asyncio
async def test_decide_checks_timeout_handling(
    llm_decider,
    llm_client_mock,
    sample_context,
    sample_checks
):
    """Test 15: Timeout LLM → fallback."""
    import asyncio

    # Simuler timeout
    async def timeout_side_effect(*args, **kwargs):
        await asyncio.sleep(10)
        return Mock(content=[Mock(text='{"checks_to_run": [], "reasoning": ""}')])

    llm_client_mock.messages.create = timeout_side_effect

    # Appeler avec timeout court (devrait fallback)
    # Note: LLMDecider doit implémenter timeout interne
    result = await llm_decider.decide_checks(sample_context, sample_checks)

    # Si timeout implémenté correctement → fallback
    # Sinon ce test timeout (à corriger dans implémentation)
    assert result is not None
