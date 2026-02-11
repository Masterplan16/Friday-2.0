"""
Tests unitaires pour agents/email/classifier.py

Tests de base - tests complets dans tests/integration/
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.src.agents.email.classifier import (
    EmailClassifierError,
    _call_claude_with_retry,
    _fetch_correction_rules,
    _update_email_category,
    classify_email,
)
from agents.src.models.email_classification import EmailClassification


# ==========================================
# Tests classify_email (fonction principale)
# ==========================================


@pytest.mark.integration  # Nécessite TrustManager initialisé
@pytest.mark.asyncio
@patch("agents.src.agents.email.classifier._fetch_correction_rules")
@patch("agents.src.agents.email.classifier._call_claude_with_retry")
@patch("agents.src.agents.email.classifier._update_email_category")
@patch("agents.src.agents.email.classifier._check_cold_start_progression")
async def test_classify_email_success(
    mock_cold_start,
    mock_update,
    mock_claude,
    mock_rules,
):
    """Test classification réussie avec tous les mocks."""
    # Setup mocks
    mock_rules.return_value = []
    mock_claude.return_value = EmailClassification(
        category="medical",
        confidence=0.92,
        reasoning="Email from SELARL cabinet",
        keywords=["SELARL", "patients"],
    )
    mock_update.return_value = None
    mock_cold_start.return_value = None

    # Mock db_pool (pas utilisé dans ce test avec mocks)
    mock_pool = AsyncMock()

    # Test
    result = await classify_email(
        email_id="test-email-123",
        email_text="Email from cabinet medical SELARL",
        db_pool=mock_pool,
    )

    # Assertions
    assert result.confidence == 0.92
    assert "medical" in result.output_summary
    assert result.payload["category"] == "medical"
    assert result.payload["model"] == "claude-sonnet-4-5-20250929"
    assert "latency_ms" in result.payload


@pytest.mark.integration  # Nécessite TrustManager initialisé
@pytest.mark.asyncio
@patch("agents.src.agents.email.classifier._fetch_correction_rules")
@patch("agents.src.agents.email.classifier._call_claude_with_retry")
async def test_classify_email_error_fallback(mock_claude, mock_rules):
    """Test fallback en cas d'erreur de classification."""
    # Setup mocks pour simuler erreur
    mock_rules.return_value = []
    mock_claude.side_effect = Exception("Claude API error")

    mock_pool = AsyncMock()

    # Test
    result = await classify_email(
        email_id="test-email-error",
        email_text="Test email",
        db_pool=mock_pool,
    )

    # Assertions - doit retourner fallback
    assert result.confidence == 0.0
    assert "ERREUR" in result.output_summary
    assert result.payload["category"] == "unknown"
    assert "error" in result.payload


# ==========================================
# Tests _fetch_correction_rules
# ==========================================


@pytest.mark.asyncio
async def test_fetch_correction_rules_empty():
    """Test fetch rules quand aucune règle active."""
    # Mock pool et conn
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []

    mock_pool = MagicMock()
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire = MagicMock(return_value=acquire_ctx)

    # Test
    rules = await _fetch_correction_rules(mock_pool)

    # Assertions
    assert rules == []
    mock_conn.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_correction_rules_degraded_mode():
    """Test mode dégradé si fetch rules échoue."""
    # Mock pool pour simuler erreur
    mock_pool = MagicMock()
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(side_effect=Exception("DB error"))
    mock_pool.acquire = MagicMock(return_value=acquire_ctx)

    # Test - ne doit PAS raise, retourner []
    rules = await _fetch_correction_rules(mock_pool)

    # Assertions
    assert rules == []  # Mode dégradé


# ==========================================
# Tests _call_claude_with_retry
# ==========================================


@pytest.mark.asyncio
@patch("agents.src.agents.email.classifier.get_llm_adapter")
async def test_call_claude_success_first_try(mock_get_adapter):
    """Test appel Claude réussi du premier coup."""
    # Mock LLM adapter (C1 fix: mock complete_with_anonymization)
    mock_adapter = AsyncMock()
    mock_response = AsyncMock()
    mock_response.content = json.dumps({
        "category": "finance",
        "confidence": 0.88,
        "reasoning": "Banking email with account details",
        "keywords": ["bank", "account"],
        "suggested_priority": "normal",
    })
    mock_adapter.complete_with_anonymization.return_value = mock_response
    mock_get_adapter.return_value = mock_adapter

    # Test
    classification = await _call_claude_with_retry(
        system_prompt="System prompt",
        user_prompt="User prompt",
        email_id="test-email",
    )

    # Assertions
    assert classification.category == "finance"
    assert classification.confidence == 0.88
    mock_adapter.complete_with_anonymization.assert_called_once()


@pytest.mark.asyncio
@patch("agents.src.agents.email.classifier.get_llm_adapter")
@patch("agents.src.agents.email.classifier._async_sleep")
async def test_call_claude_retry_on_json_error(mock_sleep, mock_get_adapter):
    """Test retry en cas d'erreur parsing JSON."""
    # Mock LLM adapter (C1 fix: mock complete_with_anonymization)
    mock_adapter = AsyncMock()
    # Premier appel : JSON invalide
    # Deuxième appel : JSON valide
    mock_response_1 = AsyncMock()
    mock_response_1.content = "Invalid JSON response"
    mock_response_2 = AsyncMock()
    mock_response_2.content = json.dumps({
        "category": "medical",
        "confidence": 0.90,
        "reasoning": "Valid response on retry",
        "keywords": ["test"],
    })
    mock_adapter.complete_with_anonymization.side_effect = [mock_response_1, mock_response_2]
    mock_get_adapter.return_value = mock_adapter
    mock_sleep.return_value = None

    # Test
    classification = await _call_claude_with_retry(
        system_prompt="System",
        user_prompt="User",
        email_id="test",
    )

    # Assertions
    assert classification.category == "medical"
    assert mock_adapter.complete_with_anonymization.call_count == 2
    mock_sleep.assert_called_once_with(1)  # Backoff 1s


@pytest.mark.asyncio
@patch("agents.src.agents.email.classifier.get_llm_adapter")
@patch("agents.src.agents.email.classifier._async_sleep")
async def test_call_claude_fail_after_max_retries(mock_sleep, mock_get_adapter):
    """Test échec après max retries."""
    # Mock LLM adapter qui fail toujours (C1 fix: mock complete_with_anonymization)
    mock_adapter = AsyncMock()
    mock_adapter.complete_with_anonymization.side_effect = Exception("API error")
    mock_get_adapter.return_value = mock_adapter
    mock_sleep.return_value = None

    # Test - doit raise EmailClassifierError
    with pytest.raises(EmailClassifierError) as exc_info:
        await _call_claude_with_retry(
            system_prompt="System",
            user_prompt="User",
            email_id="test",
            max_retries=3,
        )

    # Message peut être en français ou anglais
    error_msg = str(exc_info.value).lower()
    assert ("3 tentatives" in error_msg or "max retries" in error_msg)
    assert mock_adapter.complete_with_anonymization.call_count == 3  # C1 fix


# ==========================================
# Tests _update_email_category
# ==========================================


@pytest.mark.asyncio
async def test_update_email_category_success():
    """Test mise à jour catégorie email réussie."""
    # Mock conn
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = "UPDATE 1"  # 1 ligne modifiée

    # Mock pool
    mock_pool = MagicMock()
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire = MagicMock(return_value=acquire_ctx)

    # Test - ne doit pas raise
    await _update_email_category(
        db_pool=mock_pool,
        email_id="test-email-123",
        category="medical",
        confidence=0.92,
    )

    # Assertions
    mock_conn.execute.assert_called_once()
    call_args = mock_conn.execute.call_args[0]
    assert "UPDATE ingestion.emails" in call_args[0]
    assert call_args[1] == "medical"
    assert call_args[2] == 0.92


@pytest.mark.asyncio
async def test_update_email_category_not_found():
    """Test erreur si email introuvable."""
    # Mock conn - aucune ligne modifiée
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = "UPDATE 0"

    # Mock pool
    mock_pool = MagicMock()
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire = MagicMock(return_value=acquire_ctx)

    # Test - doit raise EmailClassifierError
    with pytest.raises(EmailClassifierError) as exc_info:
        await _update_email_category(
            db_pool=mock_pool,
            email_id="nonexistent-email",
            category="medical",
            confidence=0.92,
        )

    assert "introuvable" in str(exc_info.value)
