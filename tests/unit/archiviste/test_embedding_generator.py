#!/usr/bin/env python3
"""
Friday 2.0 - Tests Unitaires Archiviste Embedding Generator

Tests pour chunking documents + génération embeddings multi-chunks.

Date: 2026-02-11
Story: 6.2 - Task 3
"""

from unittest.mock import AsyncMock, patch

import pytest
from agents.src.agents.archiviste.embedding_generator import (
    chunk_text,
    generate_document_embeddings,
)


def test_chunk_text_small_document():
    """Test que petit document (<chunk_size) retourne 1 seul chunk"""
    text = "A" * 1000  # 1000 chars < 2000
    chunks = chunk_text(text, chunk_size=2000, overlap=200)

    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_large_document():
    """Test que grand document split en chunks avec overlap"""
    text = "A" * 5000  # 5000 chars
    chunks = chunk_text(text, chunk_size=2000, overlap=200)

    # Doit créer plusieurs chunks
    assert len(chunks) > 1

    # Premier chunk = 2000 chars
    assert len(chunks[0]) == 2000

    # Chaque chunk ≤ chunk_size
    for chunk in chunks:
        assert len(chunk) <= 2000


@pytest.mark.asyncio
async def test_generate_document_embeddings_small():
    """Test génération embedding pour petit document (1 chunk)"""
    mock_vectorstore = AsyncMock()

    # Mock embed
    mock_response = AsyncMock()
    mock_response.embeddings = [[0.1] * 1024]
    mock_vectorstore.embed = AsyncMock(return_value=mock_response)
    mock_vectorstore.store = AsyncMock()

    # Mock anonymization
    with patch("agents.src.agents.archiviste.embedding_generator.anonymize_text") as mock_anon:
        mock_anon_result = AsyncMock()
        mock_anon_result.anonymized_text = "Test document content"
        mock_anon_result.entities = []
        mock_anon.return_value = mock_anon_result

        text = "Test document content (small)"
        count = await generate_document_embeddings(
            document_node_id="doc_123",
            text=text,
            vectorstore=mock_vectorstore,
        )

        # 1 embedding généré
        assert count == 1

        # Anonymisation appelée
        mock_anon.assert_awaited_once()

        # Embedding généré + stocké
        mock_vectorstore.embed.assert_awaited_once()
        mock_vectorstore.store.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_document_embeddings_chunked():
    """Test génération embeddings pour document nécessitant chunking"""
    mock_vectorstore = AsyncMock()

    # Mock embed
    mock_response = AsyncMock()
    mock_response.embeddings = [[0.1] * 1024]
    mock_vectorstore.embed = AsyncMock(return_value=mock_response)
    mock_vectorstore.store = AsyncMock()

    # Mock anonymization
    with patch("agents.src.agents.archiviste.embedding_generator.anonymize_text") as mock_anon:
        mock_anon_result = AsyncMock()
        mock_anon_result.anonymized_text = "Anonymized chunk"
        mock_anon_result.entities = []
        mock_anon.return_value = mock_anon_result

        # Document long >10k chars → chunking
        text = "A" * 15000  # 15k chars

        count = await generate_document_embeddings(
            document_node_id="doc_456",
            text=text,
            vectorstore=mock_vectorstore,
        )

        # Plusieurs embeddings générés
        assert count > 1

        # Anonymisation appelée pour chaque chunk
        assert mock_anon.await_count == count

        # Embeddings générés + stockés
        assert mock_vectorstore.embed.await_count == count
        assert mock_vectorstore.store.await_count == count
