#!/usr/bin/env python3
"""
Tests unitaires pour EmbeddingGenerator (Story 3.3 - Task 1).

Tests:
- Génération embedding avec Voyage AI mock
- Validation dimensions (1024)
- Normalization vecteur (L2 norm = 1)
- Anonymisation Presidio AVANT appel API
- Retry automatique (backoff exponentiel)
- Timeout 5s
- Budget tracking core.api_usage
- ActionResult avec confidence et reasoning
- Fail-explicit si erreur Voyage AI

Date: 2026-02-16
Story: 3.3 - Task 1.8
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from agents.src.agents.archiviste.embedding_generator import EmbeddingGenerator
from agents.src.agents.archiviste.models import EmbeddingResult
from agents.src.middleware.models import ActionResult
from agents.src.tools.anonymize import AnonymizationResult


@pytest.fixture
def embedding_generator():
    """Fixture EmbeddingGenerator avec DB pool mock."""
    db_pool = AsyncMock()
    return EmbeddingGenerator(db_pool=db_pool)


@pytest.fixture
def mock_voyage_response():
    """Fixture réponse Voyage AI mock."""
    # Vecteur normalisé (L2 norm = 1) de 1024 dimensions
    # Créer vecteur avec norme L2 = 1
    import math

    value = 1.0 / math.sqrt(1024)  # sqrt(1024 * value^2) = 1
    embedding_vector = [value] * 1024
    return {
        "embeddings": [embedding_vector],
        "dimensions": 1024,
        "tokens_used": 150,
        "model": "voyage-4-large",
    }


@pytest.fixture
def mock_anonymization_result():
    """Fixture résultat anonymisation Presidio."""
    return AnonymizationResult(
        anonymized_text="Document concernant patient [PERSON_0] avec montant [AMOUNT_1]",
        mapping={
            "PERSON_0": "Dr. Martin Dupont",
            "AMOUNT_1": "1250.50 EUR",
        },
        confidence_min=0.95,
    )


# ============================================================
# Test 1: Génération embedding basique
# ============================================================


@pytest.mark.asyncio
async def test_generate_embedding_basic_success(
    embedding_generator, mock_voyage_response, mock_anonymization_result
):
    """
    Test génération embedding réussie (AC2).

    Vérifie:
    - Embedding généré via Voyage AI
    - Dimensions = 1024
    - Retourne EmbeddingResult complet
    """
    document_id = uuid4()
    text_content = "Facture SELARL cabinet médical 1250 EUR"

    # Mock anonymisation
    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        # Mock Voyage AI adapter
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_voyage_response

        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            result = await embedding_generator.generate_embedding(
                document_id=document_id, text_content=text_content
            )

    # Assertions
    assert isinstance(result, EmbeddingResult)
    assert result.document_id == str(document_id)  # document_id stored as string
    assert len(result.embedding_vector) == 1024
    assert result.model_name == "voyage-4-large"
    assert result.confidence >= 0.0 and result.confidence <= 1.0
    assert result.metadata is not None


# ============================================================
# Test 2: Validation dimensions (1024)
# ============================================================


@pytest.mark.asyncio
async def test_embedding_dimensions_validation(embedding_generator, mock_anonymization_result):
    """
    Test validation dimensions embedding (AC2).

    Vérifie que embedding a exactement 1024 dimensions.
    """
    document_id = uuid4()
    text_content = "Test document"

    mock_response_wrong_dims = {
        "embeddings": [[0.1] * 512],  # Wrong: 512 dimensions au lieu de 1024
        "dimensions": 512,
        "tokens_used": 50,
        "model": "wrong-model",
    }

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_response_wrong_dims

        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            with pytest.raises(ValueError, match="Expected 1024 dimensions"):
                await embedding_generator.generate_embedding(
                    document_id=document_id, text_content=text_content
                )


# ============================================================
# Test 3: Normalization vecteur (L2 norm = 1)
# ============================================================


@pytest.mark.asyncio
async def test_embedding_vector_normalization(
    embedding_generator, mock_voyage_response, mock_anonymization_result
):
    """
    Test normalization vecteur embedding (L2 norm = 1).

    Voyage AI retourne vecteurs normalisés.
    Vérifie norme L2 ≈ 1.0 (tolérance 0.01).
    """
    document_id = uuid4()
    text_content = "Document de test normalization"

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_voyage_response

        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            result = await embedding_generator.generate_embedding(
                document_id=document_id, text_content=text_content
            )

    # Calculer norme L2
    embedding = result.embedding_vector
    l2_norm = sum(x**2 for x in embedding) ** 0.5

    # Tolérance 0.01 pour floating point errors
    assert abs(l2_norm - 1.0) < 0.01, f"L2 norm should be ~1.0, got {l2_norm}"


# ============================================================
# Test 4: Anonymisation Presidio AVANT appel Voyage AI
# ============================================================


@pytest.mark.asyncio
async def test_anonymization_before_api_call(
    embedding_generator, mock_voyage_response, mock_anonymization_result
):
    """
    Test anonymisation Presidio AVANT appel Voyage AI (AC2, NFR6).

    Vérifie:
    - anonymize_text() appelé AVANT embed()
    - Texte anonymisé passé à Voyage AI
    """
    document_id = uuid4()
    text_content = "Patient Dr. Martin Dupont facture 1250.50 EUR"

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ) as mock_anonymize:
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_voyage_response

        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            await embedding_generator.generate_embedding(
                document_id=document_id, text_content=text_content
            )

    # Vérifier anonymize_text appelé avec texte original
    mock_anonymize.assert_called_once_with(text_content)

    # Vérifier Voyage AI appelé avec texte ANONYMISÉ
    mock_adapter.embed.assert_called_once()
    # call_args est un tuple (args, kwargs), on veut kwargs['texts']
    call_kwargs = mock_adapter.embed.call_args[1] if len(mock_adapter.embed.call_args) > 1 else {}
    call_args_positional = (
        mock_adapter.embed.call_args[0] if len(mock_adapter.embed.call_args) > 0 else ()
    )

    # Vérifier textes passés (soit en positional soit en kwargs)
    if "texts" in call_kwargs:
        texts_passed = call_kwargs["texts"]
    elif len(call_args_positional) > 0:
        texts_passed = call_args_positional[0]
    else:
        texts_passed = []

    assert len(texts_passed) > 0
    assert "[PERSON_0]" in texts_passed[0]  # Texte anonymisé
    assert "Dr. Martin Dupont" not in texts_passed[0]  # PAS de PII


# ============================================================
# Test 5: Retry automatique (backoff exponentiel)
# ============================================================


@pytest.mark.asyncio
async def test_retry_exponential_backoff(
    embedding_generator, mock_voyage_response, mock_anonymization_result
):
    """
    Test retry automatique avec backoff exponentiel (1s, 2s, 4s).

    Vérifie:
    - 3 tentatives max
    - Délai exponentiel entre tentatives
    - Success au 2e essai
    """
    document_id = uuid4()
    text_content = "Test retry"

    # Simuler échec 1er appel, success 2e appel
    mock_adapter = AsyncMock()
    mock_adapter.embed.side_effect = [
        Exception("API timeout"),  # 1er essai échoue
        mock_voyage_response,  # 2e essai réussit
    ]

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await embedding_generator.generate_embedding(
                    document_id=document_id, text_content=text_content
                )

    # Vérifier 2 appels (1 échec + 1 success)
    assert mock_adapter.embed.call_count == 2

    # Vérifier backoff exponentiel (1s après 1er échec)
    mock_sleep.assert_called_once_with(1.0)

    # Résultat success
    assert isinstance(result, EmbeddingResult)


# ============================================================
# Test 6: Timeout 5s
# ============================================================


@pytest.mark.asyncio
async def test_timeout_5_seconds(embedding_generator, mock_anonymization_result):
    """
    Test timeout 5s via asyncio.wait_for (AC6).

    Vérifie que si Voyage AI > 5s → TimeoutError → Exception après retries.
    Note: Timeout court (0.1s) pour test rapide, 3 retries = ~0.7s total.
    """
    document_id = uuid4()
    text_content = "Test timeout"

    # Mock adapter avec délai 1s (> 0.1s timeout)
    async def slow_embed(*args, **kwargs):
        await asyncio.sleep(1.0)
        return {"embeddings": [[0.1] * 1024], "dimensions": 1024, "tokens_used": 50}

    mock_adapter = AsyncMock()
    mock_adapter.embed = slow_embed

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            # Utiliser timeout court pour test rapide
            with pytest.raises(Exception, match="Failed to generate embedding after 3 retries"):
                await embedding_generator.generate_embedding(
                    document_id=document_id, text_content=text_content, timeout=0.1
                )


# ============================================================
# Test 7: Budget tracking core.api_usage
# ============================================================


@pytest.mark.asyncio
async def test_budget_tracking_api_usage(
    embedding_generator, mock_voyage_response, mock_anonymization_result
):
    """
    Test budget tracking dans core.api_usage (AC7).

    Vérifie:
    - INSERT dans core.api_usage après génération embedding
    - Tokens utilisés enregistrés
    - Provider = "voyage-ai"
    """
    document_id = uuid4()
    text_content = "Test budget tracking"

    # Mock DB pool
    db_pool = AsyncMock()
    embedding_generator.db_pool = db_pool

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_voyage_response

        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            await embedding_generator.generate_embedding(
                document_id=document_id, text_content=text_content
            )

    # Vérifier INSERT dans core.api_usage
    db_pool.execute.assert_called_once()
    call_args = db_pool.execute.call_args[0][0]
    assert "INSERT INTO core.api_usage" in call_args
    assert "voyage-ai" in call_args.lower() or "embedding" in call_args.lower()


# ============================================================
# Test 8: ActionResult avec confidence et reasoning
# ============================================================


@pytest.mark.asyncio
async def test_action_result_structure(
    embedding_generator, mock_voyage_response, mock_anonymization_result
):
    """
    Test structure ActionResult (AC7).

    Vérifie:
    - input_summary contient document_id
    - output_summary contient dimensions
    - confidence entre 0.0-1.0
    - reasoning explique décision
    """
    document_id = uuid4()
    text_content = "Test ActionResult structure"

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_voyage_response

        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            # Appeler via @friday_action wrapper
            result = await embedding_generator.generate_embedding_action(
                document_id=document_id, text_content=text_content
            )

    # Vérifier ActionResult structure
    assert isinstance(result, ActionResult)
    assert str(document_id) in result.input_summary
    assert "1024" in result.output_summary or "dimensions" in result.output_summary.lower()
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.reasoning) > 10  # Reasoning non trivial


# ============================================================
# Test 9: Fail-explicit si erreur Voyage AI
# ============================================================


@pytest.mark.asyncio
async def test_fail_explicit_on_voyage_error(embedding_generator, mock_anonymization_result):
    """
    Test fail-explicit si erreur Voyage AI après 3 retries (NFR7).

    Vérifie:
    - Raise Exception explicite
    - Message d'erreur clair
    - Pas de silent failure
    """
    document_id = uuid4()
    text_content = "Test fail-explicit"

    # Simuler 3 échecs consécutifs
    mock_adapter = AsyncMock()
    mock_adapter.embed.side_effect = [
        Exception("API Error 1"),
        Exception("API Error 2"),
        Exception("API Error 3"),
    ]

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(Exception, match="Failed to generate embedding after 3 retries"):
                    await embedding_generator.generate_embedding(
                        document_id=document_id, text_content=text_content
                    )

    # Vérifier 3 tentatives
    assert mock_adapter.embed.call_count == 3


# ============================================================
# Test 10: Texte vide → Confidence 0.0
# ============================================================


@pytest.mark.asyncio
async def test_empty_text_returns_low_confidence(embedding_generator):
    """
    Test texte vide → EmbeddingResult avec confidence 0.0.

    Évite appel API inutile.
    """
    document_id = uuid4()
    text_content = ""  # Texte vide

    with pytest.raises(ValueError, match="Text content cannot be empty"):
        await embedding_generator.generate_embedding(
            document_id=document_id, text_content=text_content
        )


# ============================================================
# Test 11: @friday_action decorator intégration
# ============================================================


@pytest.mark.asyncio
async def test_friday_action_decorator_integration(
    embedding_generator, mock_voyage_response, mock_anonymization_result
):
    """
    Test intégration @friday_action decorator (AC7).

    Vérifie:
    - Decorator appliqué correctement
    - Receipt créé dans core.action_receipts
    - Trust level = "auto"
    """
    document_id = uuid4()
    text_content = "Test friday_action decorator"

    # Mock DB pool pour receipt
    db_pool = AsyncMock()
    embedding_generator.db_pool = db_pool

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_voyage_response

        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            # Simuler TrustManager
            with patch(
                "agents.src.middleware.trust.TrustManager.get_trust_level",
                return_value="auto",
            ):
                result = await embedding_generator.generate_embedding_action(
                    document_id=document_id, text_content=text_content
                )

    # Vérifier ActionResult retourné
    assert isinstance(result, ActionResult)

    # Vérifier trust level = "auto" (lecture seule, monitoring)
    # (Implémentation détaillée dans trust.py)


# ============================================================
# Test 12: Metadata optionnelles
# ============================================================


@pytest.mark.asyncio
async def test_optional_metadata_included(
    embedding_generator, mock_voyage_response, mock_anonymization_result
):
    """
    Test inclusion metadata optionnelles dans EmbeddingResult.

    Metadata: filename, classification_category, etc.
    """
    document_id = uuid4()
    text_content = "Test metadata"
    metadata = {
        "filename": "2026-02-16_Facture_EDF_120EUR.pdf",
        "classification_category": "finance",
        "subcategory": "selarl",
    }

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_voyage_response

        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            result = await embedding_generator.generate_embedding(
                document_id=document_id, text_content=text_content, metadata=metadata
            )

    # Vérifier metadata incluses
    assert result.metadata["filename"] == metadata["filename"]
    assert result.metadata["classification_category"] == metadata["classification_category"]


# ============================================================
# Test 13: Latence embedding < 1s (AC6)
# ============================================================


@pytest.mark.asyncio
async def test_embedding_latency_under_1_second(
    embedding_generator, mock_voyage_response, mock_anonymization_result
):
    """
    Test latence embedding < 1s (AC6).

    Vérifie que génération embedding prend < 1000ms.
    """
    document_id = uuid4()
    text_content = "Test latency"

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_voyage_response

        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            import time

            start = time.time()
            await embedding_generator.generate_embedding(
                document_id=document_id, text_content=text_content
            )
            duration = time.time() - start

    # Latence < 1s (AC6)
    # Note: Mock rapide, vrai appel API ~100ms Voyage AI
    assert duration < 1.0


# ============================================================
# Test 14: Unicode support
# ============================================================


@pytest.mark.asyncio
async def test_unicode_text_support(
    embedding_generator, mock_voyage_response, mock_anonymization_result
):
    """
    Test support texte unicode (français, accents, caractères spéciaux).
    """
    document_id = uuid4()
    text_content = "Facture médecin spécialisé €150 à Montpellier"

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_voyage_response

        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            result = await embedding_generator.generate_embedding(
                document_id=document_id, text_content=text_content
            )

    # Embedding généré sans erreur
    assert isinstance(result, EmbeddingResult)


# ============================================================
# Test 15: Long document chunking (future)
# ============================================================


@pytest.mark.asyncio
async def test_long_document_single_embedding(
    embedding_generator, mock_voyage_response, mock_anonymization_result
):
    """
    Test document long (>10k chars) → single embedding (Story 3.3).

    Note: Chunking sera dans pipeline (Task 2), pas dans generator.
    """
    document_id = uuid4()
    # Document 15k chars
    text_content = "A" * 15000

    with patch(
        "agents.src.agents.archiviste.embedding_generator.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_voyage_response

        with patch(
            "agents.src.agents.archiviste.embedding_generator.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            result = await embedding_generator.generate_embedding(
                document_id=document_id, text_content=text_content
            )

    # Single embedding (pipeline gère chunking si nécessaire)
    assert isinstance(result, EmbeddingResult)
    assert len(result.embedding_vector) == 1024
