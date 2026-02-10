#!/usr/bin/env python3
"""
Tests unitaires pour l'adaptateur LLM (Claude Sonnet 4.5)

RÈGLES:
- JAMAIS d'appels LLM réels (toujours mocker)
- Tester anonymisation obligatoire
- Tester fail-explicit si Presidio down
- Tester factory pattern

Date: 2026-02-10
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from anthropic.types import Message, Usage, TextBlock, ContentBlock

from agents.src.adapters.llm import (
    ClaudeAdapter,
    get_llm_adapter,
    LLMResponse,
    LLMError,
)
from agents.src.tools.anonymize import AnonymizationError, AnonymizationResult


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_anthropic_client():
    """Mock du client Anthropic"""
    mock = AsyncMock()
    return mock


@pytest.fixture
def mock_anonymization():
    """Mock de l'anonymisation Presidio"""
    mock_result = AnonymizationResult(
        anonymized_text="Bonjour [PERSON_1], rendez-vous à [LOCATION_1]",
        entities_found=[
            {"entity_type": "PERSON", "start": 8, "end": 18, "score": 0.95},
            {"entity_type": "LOCATION", "start": 38, "end": 58, "score": 0.92},
        ],
        confidence_min=0.92,
        mapping={
            "[PERSON_1]": "Dr Dupont",
            "[LOCATION_1]": "Clinique Saint-Jean",
        },
    )
    return mock_result


@pytest.fixture
def sample_claude_response():
    """Réponse Claude mock"""
    return Message(
        id="msg_123",
        type="message",
        role="assistant",
        content=[TextBlock(type="text", text="Voici ma réponse avec [PERSON_1]")],
        model="claude-sonnet-4-5-20250929",
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(input_tokens=100, output_tokens=50),
    )


# ============================================================================
# TESTS INITIALIZATION
# ============================================================================


def test_claude_adapter_init_success():
    """Test initialisation avec API key valide"""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = ClaudeAdapter()
        assert adapter.api_key == "sk-test-123"
        assert adapter.model == "claude-sonnet-4-5-20250929"
        assert adapter.anonymize_by_default is True


def test_claude_adapter_init_missing_key():
    """Test erreur si API key manquante"""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY manquante"):
            ClaudeAdapter()


def test_claude_adapter_init_custom_model():
    """Test initialisation avec modèle custom"""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = ClaudeAdapter(model="claude-opus-4-6")
        assert adapter.model == "claude-opus-4-6"


# ============================================================================
# TESTS COMPLETE_WITH_ANONYMIZATION (méthode principale)
# ============================================================================


@pytest.mark.asyncio
async def test_complete_with_anonymization_success(
    mock_anthropic_client, mock_anonymization, sample_claude_response
):
    """Test appel LLM avec anonymisation OK"""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = ClaudeAdapter()
        adapter.client = mock_anthropic_client
        mock_anthropic_client.messages.create.return_value = sample_claude_response

    # Mock anonymize_text et deanonymize_text
    with patch("agents.src.adapters.llm.anonymize_text") as mock_anon:
        with patch("agents.src.adapters.llm.deanonymize_text") as mock_deanon:
            mock_anon.return_value = mock_anonymization
            mock_deanon.return_value = "Voici ma réponse avec Dr Dupont"

            response = await adapter.complete_with_anonymization(
                prompt="Analyse cet email",
                context="Email de Dr Dupont à Clinique Saint-Jean",
            )

            # Vérifications
            assert isinstance(response, LLMResponse)
            assert response.content == "Voici ma réponse avec Dr Dupont"
            assert response.model == "claude-sonnet-4-5-20250929"
            assert response.anonymization_applied is True
            assert response.usage["input_tokens"] == 100
            assert response.usage["output_tokens"] == 50

            # Vérifier que l'anonymisation a été appelée
            mock_anon.assert_called_once_with(
                "Email de Dr Dupont à Clinique Saint-Jean"
            )

            # Vérifier que Claude a reçu le texte anonymisé
            call_args = mock_anthropic_client.messages.create.call_args
            user_message = call_args.kwargs["messages"][0]["content"]
            assert "[PERSON_1]" in user_message
            assert "[LOCATION_1]" in user_message
            assert "Dr Dupont" not in user_message  # PII anonymisée


@pytest.mark.asyncio
async def test_complete_with_anonymization_no_context(
    mock_anthropic_client, sample_claude_response
):
    """Test appel LLM sans contexte (pas d'anonymisation nécessaire)"""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = ClaudeAdapter()
        adapter.client = mock_anthropic_client
        mock_anthropic_client.messages.create.return_value = sample_claude_response

    with patch("agents.src.adapters.llm.anonymize_text") as mock_anon:
        response = await adapter.complete_with_anonymization(
            prompt="Quelle est la météo aujourd'hui?"
        )

        # Pas de contexte → pas d'anonymisation
        mock_anon.assert_not_called()
        assert response.anonymization_applied is False


@pytest.mark.asyncio
async def test_complete_with_anonymization_presidio_down(mock_anthropic_client):
    """Test fail-explicit si Presidio unavailable"""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = ClaudeAdapter()
        adapter.client = mock_anthropic_client

    # Simuler Presidio down
    with patch("agents.src.adapters.llm.anonymize_text") as mock_anon:
        mock_anon.side_effect = AnonymizationError("Presidio service unavailable")

        # Doit lever une erreur, pas de fallback silencieux
        with pytest.raises(AnonymizationError, match="Presidio service unavailable"):
            await adapter.complete_with_anonymization(
                prompt="Analyse", context="Email avec PII"
            )

        # Claude ne doit PAS avoir été appelé
        mock_anthropic_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_complete_with_anonymization_force_skip(
    mock_anthropic_client, sample_claude_response
):
    """Test skip anonymisation (DEBUG ONLY - doit logger warning)"""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = ClaudeAdapter()
        adapter.client = mock_anthropic_client
        mock_anthropic_client.messages.create.return_value = sample_claude_response

    with patch("agents.src.adapters.llm.anonymize_text") as mock_anon:
        response = await adapter.complete_with_anonymization(
            prompt="Test",
            context="Texte avec PII",
            force_anonymize=False,  # DANGEREUX
        )

        # Anonymisation pas appelée
        mock_anon.assert_not_called()
        assert response.anonymization_applied is False


@pytest.mark.asyncio
async def test_complete_with_anonymization_llm_error(mock_anthropic_client):
    """Test gestion erreur API Claude"""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = ClaudeAdapter()
        adapter.client = mock_anthropic_client

    # Simuler erreur Claude
    mock_anthropic_client.messages.create.side_effect = Exception("Rate limit exceeded")

    with patch("agents.src.adapters.llm.anonymize_text") as mock_anon:
        mock_anon.return_value = AnonymizationResult(
            anonymized_text="Texte safe",
            entities_found=[],
            confidence_min=1.0,
            mapping={},
        )

        with pytest.raises(LLMError, match="Claude API call failed"):
            await adapter.complete_with_anonymization(prompt="Test", context="Texte")


# ============================================================================
# TESTS COMPLETE_RAW (sans anonymisation)
# ============================================================================


@pytest.mark.asyncio
async def test_complete_raw_success(mock_anthropic_client, sample_claude_response):
    """Test appel LLM sans anonymisation (texte safe)"""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = ClaudeAdapter()
        adapter.client = mock_anthropic_client
        mock_anthropic_client.messages.create.return_value = sample_claude_response

    response = await adapter.complete_raw(prompt="Quel jour sommes-nous?")

    assert isinstance(response, LLMResponse)
    assert response.anonymization_applied is False
    assert response.model == "claude-sonnet-4-5-20250929"


@pytest.mark.asyncio
async def test_complete_raw_llm_error(mock_anthropic_client):
    """Test erreur API sur complete_raw"""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = ClaudeAdapter()
        adapter.client = mock_anthropic_client
        mock_anthropic_client.messages.create.side_effect = Exception("Network error")

    with pytest.raises(LLMError, match="Claude API call failed"):
        await adapter.complete_raw(prompt="Test")


# ============================================================================
# TESTS FACTORY PATTERN
# ============================================================================


def test_get_llm_adapter_default():
    """Test factory avec provider par défaut (anthropic)"""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = get_llm_adapter()
        assert isinstance(adapter, ClaudeAdapter)
        assert adapter.anonymize_by_default is True


def test_get_llm_adapter_anthropic_explicit():
    """Test factory avec provider anthropic explicite"""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = get_llm_adapter(provider="anthropic")
        assert isinstance(adapter, ClaudeAdapter)


def test_get_llm_adapter_unsupported_provider():
    """Test erreur si provider non supporté"""
    with pytest.raises(NotImplementedError, match="pas encore supporté"):
        get_llm_adapter(provider="openai")


def test_get_llm_adapter_disable_anonymization():
    """Test factory avec anonymisation désactivée (DEBUG)"""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = get_llm_adapter(anonymize_by_default=False)
        assert adapter.anonymize_by_default is False


# ============================================================================
# TESTS RESPONSE MODEL
# ============================================================================


def test_llm_response_model():
    """Test modèle Pydantic LLMResponse"""
    response = LLMResponse(
        content="Test response",
        model="claude-sonnet-4-5-20250929",
        usage={"input_tokens": 10, "output_tokens": 5},
        anonymization_applied=True,
    )

    assert response.content == "Test response"
    assert response.model == "claude-sonnet-4-5-20250929"
    assert response.usage["input_tokens"] == 10
    assert response.anonymization_applied is True


def test_llm_response_defaults():
    """Test valeurs par défaut LLMResponse"""
    response = LLMResponse(content="Test", model="claude-test")

    assert response.usage == {}
    assert response.anonymization_applied is False


# ============================================================================
# TESTS INTEGRATION (mocks mais flow complet)
# ============================================================================


@pytest.mark.asyncio
async def test_full_flow_with_pii_protection(
    mock_anthropic_client, mock_anonymization, sample_claude_response
):
    """
    Test flow complet : contexte PII → anonymisation → LLM → deanonymisation
    """
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        adapter = ClaudeAdapter()
        adapter.client = mock_anthropic_client
        mock_anthropic_client.messages.create.return_value = sample_claude_response

    with patch("agents.src.adapters.llm.anonymize_text") as mock_anon:
        with patch("agents.src.adapters.llm.deanonymize_text") as mock_deanon:
            # Setup mocks
            mock_anon.return_value = mock_anonymization
            mock_deanon.return_value = "Réponse finale avec Dr Dupont"

            # Contexte avec PII
            context_with_pii = """
            Email de Dr Dupont (dr.dupont@clinique-saint-jean.fr)
            RDV patient le 15/02/2026 à 14h30
            Tél: 01.23.45.67.89
            """

            response = await adapter.complete_with_anonymization(
                prompt="Résume cet email médical",
                context=context_with_pii,
                system="Tu es un assistant médical RGPD-compliant",
            )

            # Vérifications critiques RGPD
            assert mock_anon.called  # Anonymisation appelée
            assert mock_deanon.called  # Deanonymisation appelée
            assert response.anonymization_applied is True

            # Vérifier que les PII n'ont PAS été envoyées à Claude
            claude_call = mock_anthropic_client.messages.create.call_args
            user_message = claude_call.kwargs["messages"][0]["content"]
            assert "Dr Dupont" not in user_message
            assert "dr.dupont@clinique-saint-jean.fr" not in user_message
            assert "01.23.45.67.89" not in user_message

            # Mais la réponse finale doit être deanonymisée
            assert "Dr Dupont" in response.content
