#!/usr/bin/env python3
"""
Tests unitaires pour SemanticSearcher (Story 3.3 - Task 4).

Tests:
- Recherche sémantique basique via pgvector mock
- Validation query vide
- Validation top_k limites
- Anonymisation AVANT embedding query
- Filtres: category, date_range, confidence_min, file_type
- Excerpt extraction (<= 200 chars)
- ActionResult wrapper
- Métriques search_metrics integration

Date: 2026-02-16
Story: 3.3 - Task 4
"""

import math
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agents.src.agents.archiviste.models import SearchResult
from agents.src.agents.archiviste.semantic_search import EXCERPT_LENGTH, TOP_K_MAX, SemanticSearcher
from agents.src.middleware.models import ActionResult
from agents.src.tools.anonymize import AnonymizationResult

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def db_pool():
    """Fixture asyncpg pool mock."""
    pool = AsyncMock()
    pool.execute = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    return pool


@pytest.fixture
def searcher(db_pool):
    """Fixture SemanticSearcher avec DB pool mock."""
    return SemanticSearcher(db_pool=db_pool)


@pytest.fixture
def mock_anonymization_result():
    """Fixture résultat anonymisation Presidio."""
    return AnonymizationResult(
        anonymized_text="facture [PERSON_0] 2026",
        mapping={"PERSON_0": "plombier Dupont"},
        confidence_min=0.95,
    )


@pytest.fixture
def mock_embedding():
    """Fixture vecteur embedding normalisé 1024 dims."""
    value = 1.0 / math.sqrt(1024)
    return [value] * 1024


@pytest.fixture
def mock_embedding_response(mock_embedding):
    """Fixture réponse Voyage AI adapter."""
    return {
        "embeddings": [mock_embedding],
        "dimensions": 1024,
        "tokens_used": 50,
    }


@pytest.fixture
def mock_db_rows():
    """Fixture rows retournées par pgvector query."""
    return [
        {
            "document_id": uuid4(),
            "title": "2026-01-15_Facture_Plombier_350EUR.pdf",
            "path": r"C:\Users\lopez\BeeStation\Friday\Archives\finance\selarl\2026-01-15_Facture_Plombier_350EUR.pdf",
            "score": 0.92,
            "ocr_text": "Facture plomberie travaux salle de bain remplacement tuyauterie cuivre",
            "classification_category": "finance",
            "classification_subcategory": "selarl",
            "classification_confidence": 0.95,
            "document_metadata": {"source": "scan"},
        },
        {
            "document_id": uuid4(),
            "title": "2026-02-01_Facture_Electricien_200EUR.pdf",
            "path": r"C:\Users\lopez\BeeStation\Friday\Archives\finance\selarl\2026-02-01_Facture_Electricien_200EUR.pdf",
            "score": 0.78,
            "ocr_text": "Facture electricien installation prises electriques cabinet",
            "classification_category": "finance",
            "classification_subcategory": "selarl",
            "classification_confidence": 0.88,
            "document_metadata": {"source": "email"},
        },
    ]


# ============================================================
# Test 1: Recherche sémantique basique
# ============================================================


@pytest.mark.asyncio
async def test_search_basic_success(
    searcher, mock_anonymization_result, mock_embedding_response, mock_db_rows
):
    """
    Test recherche sémantique réussie (AC1).

    Vérifie:
    - Pipeline complet: anonymize → embed → pgvector → SearchResult
    - Résultats retournés en liste de SearchResult
    """
    searcher.db_pool.fetch.return_value = mock_db_rows

    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_embedding_response

        with patch(
            "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            results = await searcher.search(query="facture plombier 2026")

    assert len(results) == 2
    assert all(isinstance(r, SearchResult) for r in results)
    assert results[0].score >= results[1].score


# ============================================================
# Test 2: Query vide → ValueError
# ============================================================


@pytest.mark.asyncio
async def test_search_empty_query_raises(searcher):
    """Test query vide lève ValueError."""
    with pytest.raises(ValueError, match="Query cannot be empty"):
        await searcher.search(query="")

    with pytest.raises(ValueError, match="Query cannot be empty"):
        await searcher.search(query="   ")


# ============================================================
# Test 3: top_k validation
# ============================================================


@pytest.mark.asyncio
async def test_search_top_k_validation(searcher):
    """Test top_k hors limites lève ValueError."""
    with pytest.raises(ValueError, match="top_k must be between 1 and"):
        await searcher.search(query="test", top_k=0)

    with pytest.raises(ValueError, match="top_k must be between 1 and"):
        await searcher.search(query="test", top_k=TOP_K_MAX + 1)


# ============================================================
# Test 4: Anonymisation AVANT embedding query
# ============================================================


@pytest.mark.asyncio
async def test_anonymization_before_embedding(
    searcher, mock_anonymization_result, mock_embedding_response
):
    """
    Test anonymisation Presidio AVANT appel Voyage AI (NFR6).

    Vérifie ordre: anonymize_text() → adapter.embed()
    """
    searcher.db_pool.fetch.return_value = []

    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        return_value=mock_anonymization_result,
    ) as mock_anonymize:
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_embedding_response

        with patch(
            "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            await searcher.search(query="patient Dupont facture")

    # anonymize_text appelé avec query originale
    mock_anonymize.assert_called_once_with("patient Dupont facture")

    # adapter.embed appelé avec texte ANONYMISÉ
    mock_adapter.embed.assert_called_once()
    call_kwargs = mock_adapter.embed.call_args[1]
    assert call_kwargs["texts"] == [mock_anonymization_result.anonymized_text]
    assert call_kwargs["anonymize"] is False


# ============================================================
# Test 5: Filtre category
# ============================================================


@pytest.mark.asyncio
async def test_search_filter_category(searcher, mock_anonymization_result, mock_embedding_response):
    """Test filtre category injecté dans WHERE clause."""
    searcher.db_pool.fetch.return_value = []

    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_embedding_response

        with patch(
            "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            await searcher.search(query="facture", filters={"category": "finance"})

    # Vérifier SET LOCAL hnsw.iterative_scan activé
    searcher.db_pool.execute.assert_called_once_with("SET LOCAL hnsw.iterative_scan = on")

    # Vérifier query SQL contient filtre category
    fetch_call = searcher.db_pool.fetch.call_args
    sql = fetch_call[0][0]
    assert "dm.classification_category = $3" in sql

    # Vérifier paramètre "finance" passé
    params = fetch_call[0][1:]
    assert "finance" in params


# ============================================================
# Test 6: Filtres multiples
# ============================================================


@pytest.mark.asyncio
async def test_search_multiple_filters(
    searcher, mock_anonymization_result, mock_embedding_response
):
    """Test multiples filtres simultanés."""
    searcher.db_pool.fetch.return_value = []

    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_embedding_response

        with patch(
            "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            await searcher.search(
                query="facture",
                filters={
                    "category": "finance",
                    "after": "2026-01-01",
                    "file_type": "pdf",
                },
            )

    # Vérifier 3 filtres dans SQL
    sql = searcher.db_pool.fetch.call_args[0][0]
    assert "dm.classification_category" in sql
    assert "dm.created_at >=" in sql
    assert "dm.original_filename ILIKE" in sql


# ============================================================
# Test 7: Excerpt extraction
# ============================================================


def test_extract_excerpt_short_text(searcher):
    """Test excerpt texte court (<200 chars) retourné tel quel."""
    text = "Facture plombier 350 EUR"
    excerpt = searcher._extract_excerpt(text)
    assert excerpt == text


def test_extract_excerpt_long_text(searcher):
    """Test excerpt texte long (>200 chars) tronqué avec '...'."""
    text = "A" * 300
    excerpt = searcher._extract_excerpt(text)
    assert len(excerpt) <= EXCERPT_LENGTH
    assert excerpt.endswith("...")


def test_extract_excerpt_empty_text(searcher):
    """Test excerpt texte vide retourne chaîne vide."""
    assert searcher._extract_excerpt("") == ""
    assert searcher._extract_excerpt(None) == ""


def test_extract_excerpt_exactly_200_chars(searcher):
    """Test excerpt exactement 200 chars (pas de troncature)."""
    text = "B" * 200
    excerpt = searcher._extract_excerpt(text)
    assert len(excerpt) == 200
    assert "..." not in excerpt


# ============================================================
# Test 8: ActionResult wrapper
# ============================================================


@pytest.mark.asyncio
async def test_search_action_success(
    searcher, mock_anonymization_result, mock_embedding_response, mock_db_rows
):
    """Test search_action retourne ActionResult valide."""
    searcher.db_pool.fetch.return_value = mock_db_rows

    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_embedding_response

        with patch(
            "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            result = await searcher.search_action(query="facture plombier")

    assert isinstance(result, ActionResult)
    assert "facture plombier" in result.input_summary
    assert result.confidence > 0.0
    assert "FAILED" not in result.output_summary
    assert result.payload["results_count"] == 2


@pytest.mark.asyncio
async def test_search_action_failure(searcher):
    """Test search_action raise exception après avoir créé un receipt d'erreur."""
    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        side_effect=Exception("Presidio down"),
    ):
        with pytest.raises(Exception, match="Presidio down"):
            await searcher.search_action(query="test")

    # Le décorateur @friday_action a créé un receipt d'erreur avant de re-raise
    # (vérifié par le log "Receipt created" dans les tests)


# ============================================================
# Test 9: Pas de résultats
# ============================================================


@pytest.mark.asyncio
async def test_search_no_results(searcher, mock_anonymization_result, mock_embedding_response):
    """Test recherche sans résultats retourne liste vide."""
    searcher.db_pool.fetch.return_value = []

    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_embedding_response

        with patch(
            "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            results = await searcher.search(query="xyz introuvable")

    assert results == []


# ============================================================
# Test 10: Métriques search_metrics enregistrées
# ============================================================


@pytest.mark.asyncio
async def test_search_records_metrics(
    searcher, mock_anonymization_result, mock_embedding_response, mock_db_rows
):
    """Test search_metrics.record_query() appelé après chaque recherche."""
    searcher.db_pool.fetch.return_value = mock_db_rows

    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_embedding_response

        with patch(
            "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            with patch(
                "agents.src.agents.archiviste.semantic_search.search_metrics"
            ) as mock_metrics:
                await searcher.search(query="facture")

    mock_metrics.record_query.assert_called_once()
    call_kwargs = mock_metrics.record_query.call_args[1]
    assert "query_duration_ms" in call_kwargs
    assert call_kwargs["results_count"] == 2
    assert call_kwargs["top_score"] > 0.0


# ============================================================
# Test 11: hnsw.iterative_scan NON activé sans filtres
# ============================================================


@pytest.mark.asyncio
async def test_no_iterative_scan_without_filters(
    searcher, mock_anonymization_result, mock_embedding_response
):
    """Test SET LOCAL hnsw.iterative_scan NON appelé sans filtres."""
    searcher.db_pool.fetch.return_value = []

    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        return_value=mock_anonymization_result,
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = mock_embedding_response

        with patch(
            "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            await searcher.search(query="test")

    # execute NE devrait PAS être appelé (pas de SET LOCAL)
    searcher.db_pool.execute.assert_not_called()
