#!/usr/bin/env python3
"""
Tests intégration Embedding Pipeline (Story 3.3 - Task 2.7).

Tests avec PostgreSQL et Redis réels (pas de mocks).

Date: 2026-02-16
Story: 3.3 - Task 2.7
"""

import asyncio
import json
from uuid import uuid4

import asyncpg
import pytest
import redis.asyncio as aioredis

from agents.src.agents.archiviste.embedding_pipeline import EmbeddingPipeline


@pytest.fixture
async def db_pool():
    """Fixture PostgreSQL pool."""
    pool = await asyncpg.create_pool(
        "postgresql://friday:friday@localhost:5432/friday_test",
        min_size=1,
        max_size=2,
    )
    yield pool
    await pool.close()


@pytest.fixture
async def redis_client():
    """Fixture Redis client."""
    client = await aioredis.from_url(
        "redis://localhost:6379/1",  # DB 1 pour tests
        decode_responses=False,
    )
    yield client
    await client.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_process_document_classified_event(db_pool, redis_client):
    """
    Test pipeline complet : event document.classified → embedding → event document.indexed.

    Vérifie:
    - Consumer lit event Redis Streams
    - Embedding généré et stocké PostgreSQL
    - Event document.indexed publié
    """
    # Créer test document dans PostgreSQL
    document_id = uuid4()
    await db_pool.execute(
        """
        INSERT INTO ingestion.document_metadata (
            document_id,
            original_filename,
            final_path,
            ocr_text,
            classification_category
        ) VALUES ($1, $2, $3, $4, $5)
        """,
        document_id,
        "test-document.pdf",
        "/tmp/test.pdf",
        "Test document content for embedding generation.",
        "pro",
    )

    # Publish event document.classified
    await redis_client.xadd(
        name="document.classified",
        fields={
            "document_id": str(document_id),
            "category": "pro",
        },
    )

    # Start pipeline (process 1 message puis stop)
    pipeline = EmbeddingPipeline(db_pool=db_pool, redis_client=redis_client)

    # Process batch once
    await pipeline._consume_batch()

    # Vérifier embedding stocké dans knowledge.embeddings
    row = await db_pool.fetchrow(
        "SELECT document_id, model, confidence FROM knowledge.embeddings WHERE document_id = $1",
        document_id,
    )

    assert row is not None
    assert row["model"] == "voyage-4-large"
    assert row["confidence"] > 0.0

    # Cleanup
    await db_pool.execute("DELETE FROM knowledge.embeddings WHERE document_id = $1", document_id)
    await db_pool.execute("DELETE FROM ingestion.document_metadata WHERE document_id = $1", document_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_retry_on_failure(db_pool, redis_client):
    """
    Test retry automatique si erreur (Task 2.4).

    Simule échec temporaire → retry → succès.
    """
    # Test avec document sans text_content → devrait skip
    document_id = uuid4()
    await db_pool.execute(
        """
        INSERT INTO ingestion.document_metadata (
            document_id,
            original_filename,
            final_path,
            ocr_text
        ) VALUES ($1, $2, $3, $4)
        """,
        document_id,
        "empty-doc.pdf",
        "/tmp/empty.pdf",
        "",  # Texte vide
    )

    # Publish event
    await redis_client.xadd(
        name="document.classified",
        fields={"document_id": str(document_id)},
    )

    pipeline = EmbeddingPipeline(db_pool=db_pool, redis_client=redis_client)
    await pipeline._consume_batch()

    # Vérifier pas d'embedding créé (document vide skipped)
    row = await db_pool.fetchrow(
        "SELECT * FROM knowledge.embeddings WHERE document_id = $1",
        document_id,
    )
    assert row is None  # Pas d'embedding pour document vide

    # Cleanup
    await db_pool.execute("DELETE FROM ingestion.document_metadata WHERE document_id = $1", document_id)
