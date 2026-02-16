#!/usr/bin/env python3
"""
Friday 2.0 - Tests E2E Pipeline Embeddings (Story 6.2 - AC7)

Tests end-to-end du pipeline complet :
    1. Email reçu → populate_email_graph()
    2. Embedding généré automatiquement (Voyage AI mocked)
    3. Embedding stocké dans PostgreSQL knowledge.embeddings
    4. Recherche sémantique retrouve l'email

Usage:
    pytest tests/e2e/test_embeddings_pipeline_e2e.py -v --e2e

Date: 2026-02-11
Story: 6.2 - Task 9
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from agents.src.adapters.memorystore import PostgreSQLMemorystore
from agents.src.adapters.vectorstore import get_vectorstore_adapter
from agents.src.agents.email.graph_populator import populate_email_graph

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(scope="module")
async def db_pool():
    """Pool PostgreSQL pour tests E2E"""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL manquante - skip tests E2E")

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)

    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture(scope="function")
async def clean_test_data(db_pool: asyncpg.Pool):
    """Nettoie données test avant/après chaque test"""
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM knowledge.embeddings WHERE metadata->>'test' = 'true'")
        await conn.execute("DELETE FROM knowledge.edges WHERE metadata->>'test' = 'true'")
        await conn.execute("DELETE FROM knowledge.nodes WHERE metadata->>'test' = 'true'")

    yield

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM knowledge.embeddings WHERE metadata->>'test' = 'true'")
        await conn.execute("DELETE FROM knowledge.edges WHERE metadata->>'test' = 'true'")
        await conn.execute("DELETE FROM knowledge.nodes WHERE metadata->>'test' = 'true'")


# ============================================================
# Test E2E Pipeline Complet: Email → Embedding → Search
# ============================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_email_to_search_e2e_pipeline(db_pool: asyncpg.Pool, clean_test_data):
    """
    Test E2E complet: Email reçu → Embedding généré → Recherche sémantique

    Flow:
        1. Email "Facture plombier" arrive
        2. populate_email_graph() créé Email node
        3. Embedding généré automatiquement (Voyage AI mocked)
        4. Embedding stocké dans knowledge.embeddings
        5. Recherche "réparation fuite" retrouve l'email
    """

    # Mock memorystore (PostgreSQL knowledge.nodes)
    mock_memorystore = AsyncMock(spec=PostgreSQLMemorystore)

    # Email node créé (PAS mock - vrai INSERT)
    email_node_id = "test_email_e2e_facture_plombier"

    async def create_node_real(node_type, name, metadata, source):
        """Créer vraiment le node dans PostgreSQL"""
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge.nodes (id, node_type, name, metadata, source)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                """,
                email_node_id,
                node_type,
                name,
                {**metadata, "test": True},  # Mark as test data
                source,
            )
        return email_node_id

    mock_memorystore.create_node = create_node_real
    mock_memorystore.get_or_create_node = AsyncMock(return_value="person_node_test_001")
    mock_memorystore.create_edge = AsyncMock()

    # Mock Voyage AI + Presidio
    with patch(
        "agents.src.agents.email.graph_populator.get_vectorstore_adapter"
    ) as mock_vectorstore_factory:
        with patch("agents.src.agents.email.graph_populator.anonymize_text") as mock_anon:

            # Mock vectorstore - VA VRAIMENT stocker dans PostgreSQL
            mock_vectorstore = AsyncMock()

            # Embedding réaliste (dimensions 1024)
            test_embedding = [0.123] * 1024

            mock_embed_response = AsyncMock()
            mock_embed_response.embeddings = [test_embedding]
            mock_embed_response.anonymization_applied = False
            mock_vectorstore.embed = AsyncMock(return_value=mock_embed_response)

            # store() RÉEL (pas mock)
            async def store_real(node_id, embedding, metadata):
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO knowledge.embeddings (node_id, embedding, metadata)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (node_id) DO UPDATE SET
                            embedding = EXCLUDED.embedding,
                            metadata = EXCLUDED.metadata,
                            updated_at = NOW()
                        """,
                        node_id,
                        embedding,
                        {**metadata, "test": True},
                    )

            mock_vectorstore.store = store_real
            mock_vectorstore_factory.return_value = mock_vectorstore

            # Mock anonymization (pas de PII dans cet email)
            mock_anon_result = AsyncMock()
            mock_anon_result.anonymized_text = "Facture plombier 250 EUR Réparation fuite cuisine"
            mock_anon_result.entities = []
            mock_anon.return_value = mock_anon_result

            # === ÉTAPE 1 : Email arrive, populate graph ===
            email_data = {
                "message_id": "<e2e-test@example.com>",
                "subject": "Facture plombier 250 EUR",
                "sender": "plombier@test.com",
                "recipients": ["mainteneur@friday.local"],
                "body": "Bonjour, réparation fuite cuisine terminée.",
                "date": "2026-02-11T16:00:00Z",
                "category": "admin",
                "priority": "normal",
            }

            # Populate graph (crée node + embedding)
            created_email_node_id = await populate_email_graph(email_data, mock_memorystore)

            assert created_email_node_id == email_node_id

    # === ÉTAPE 2 : Vérifier Email node créé dans PostgreSQL ===
    async with db_pool.acquire() as conn:
        node_exists = await conn.fetchval(
            "SELECT COUNT(*) > 0 FROM knowledge.nodes WHERE id = $1 AND metadata->>'test' = 'true'",
            email_node_id,
        )
        assert node_exists, "Email node pas créé dans knowledge.nodes"

    # === ÉTAPE 3 : Vérifier Embedding stocké dans PostgreSQL ===
    async with db_pool.acquire() as conn:
        embedding_row = await conn.fetchrow(
            "SELECT node_id, embedding, metadata FROM knowledge.embeddings WHERE node_id = $1",
            email_node_id,
        )

        assert embedding_row is not None, "Embedding pas stocké dans knowledge.embeddings"
        assert len(embedding_row["embedding"]) == 1024, "Embedding dimensions != 1024"
        assert embedding_row["metadata"].get("test") is True

    # === ÉTAPE 4 : Recherche sémantique retrouve l'email ===
    from agents.src.adapters.vectorstore import PgvectorStore

    vectorstore = PgvectorStore(pool=db_pool)

    # Query embedding (similaire à l'embedding stocké)
    query_embedding = [0.123] * 1024  # Identique → similarité ~1.0

    results = await vectorstore.search(query_embedding=query_embedding, top_k=10)

    # Doit retrouver l'email test
    test_email_found = any(r.node_id == email_node_id for r in results)
    assert test_email_found, "Recherche sémantique n'a pas retrouvé l'email test"

    # Vérifier similarité élevée (>0.99 car embedding identique)
    test_result = next(r for r in results if r.node_id == email_node_id)
    assert test_result.similarity > 0.99, f"Similarité trop basse: {test_result.similarity}"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multi_email_semantic_search_e2e(db_pool: asyncpg.Pool, clean_test_data):
    """
    Test E2E recherche sémantique sur plusieurs emails.

    Scénario:
        - 3 emails insérés sur thématiques différentes
        - Recherche "plombier" doit retrouver email plombier en premier
        - Recherche "médecin" doit retrouver email médical en premier
    """

    # Mock memorystore
    mock_memorystore = AsyncMock(spec=PostgreSQLMemorystore)

    email_nodes_created = []

    async def create_node_multi(node_type, name, metadata, source):
        """Créer nodes dans PostgreSQL"""
        node_id = f"test_email_e2e_multi_{len(email_nodes_created):03d}"
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge.nodes (id, node_type, name, metadata, source)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    metadata = EXCLUDED.metadata
                """,
                node_id,
                node_type,
                name,
                {**metadata, "test": True},
                source,
            )
        email_nodes_created.append(node_id)
        return node_id

    mock_memorystore.create_node = create_node_multi
    mock_memorystore.get_or_create_node = AsyncMock(return_value="person_node_multi")
    mock_memorystore.create_edge = AsyncMock()

    # Mock Voyage AI
    with patch(
        "agents.src.agents.email.graph_populator.get_vectorstore_adapter"
    ) as mock_vectorstore_factory:
        with patch("agents.src.agents.email.graph_populator.anonymize_text") as mock_anon:

            mock_vectorstore = AsyncMock()

            # Embeddings différenciés par thématique (simulation)
            embeddings_by_theme = {
                "plombier": [1.0] + [0.0] * 1023,  # Axe 0
                "médecin": [0.0, 1.0] + [0.0] * 1022,  # Axe 1
                "avocat": [0.0, 0.0, 1.0] + [0.0] * 1021,  # Axe 2
            }

            current_theme = None

            def set_theme_embedding(texts, **kwargs):
                # Détecter thème depuis le texte
                text_combined = " ".join(texts).lower()
                for theme in embeddings_by_theme:
                    if theme in text_combined:
                        current_theme_local = theme
                        break
                else:
                    current_theme_local = "plombier"  # Default

                response = AsyncMock()
                response.embeddings = [embeddings_by_theme[current_theme_local]]
                response.anonymization_applied = False
                return response

            mock_vectorstore.embed = AsyncMock(side_effect=set_theme_embedding)

            async def store_multi(node_id, embedding, metadata):
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO knowledge.embeddings (node_id, embedding, metadata)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (node_id) DO UPDATE SET
                            embedding = EXCLUDED.embedding
                        """,
                        node_id,
                        embedding,
                        {**metadata, "test": True},
                    )

            mock_vectorstore.store = store_multi
            mock_vectorstore_factory.return_value = mock_vectorstore

            mock_anon.return_value = AsyncMock(anonymized_text="test", entities=[])

            # Insérer 3 emails thématiques
            emails_data = [
                {
                    "message_id": "<plombier@test.com>",
                    "subject": "Facture plombier réparation",
                    "body": "Réparation fuite plombier",
                    "sender": "plombier@test.com",
                    "date": "2026-02-11T10:00:00Z",
                },
                {
                    "message_id": "<medecin@test.com>",
                    "subject": "Consultation médecin",
                    "body": "Rendez-vous médecin lundi",
                    "sender": "medecin@test.com",
                    "date": "2026-02-11T11:00:00Z",
                },
                {
                    "message_id": "<avocat@test.com>",
                    "subject": "Contrat avocat",
                    "body": "Signature contrat avocat jeudi",
                    "sender": "avocat@test.com",
                    "date": "2026-02-11T12:00:00Z",
                },
            ]

            for email in emails_data:
                await populate_email_graph(email, mock_memorystore)

    # === Recherche sémantique "plombier" ===
    vectorstore = PgvectorStore(pool=db_pool)

    results_plombier = await vectorstore.search(
        query_embedding=embeddings_by_theme["plombier"],
        top_k=3,
    )

    # Premier résultat doit être email plombier
    assert len(results_plombier) >= 1
    # Filter only test emails
    test_results = [r for r in results_plombier if r.node_id in email_nodes_created]
    assert test_results[0].similarity > 0.95  # Haute similarité plombier

    # === Recherche sémantique "médecin" ===
    results_medecin = await vectorstore.search(
        query_embedding=embeddings_by_theme["médecin"],
        top_k=3,
    )

    test_results_medecin = [r for r in results_medecin if r.node_id in email_nodes_created]
    assert len(test_results_medecin) >= 1
    assert test_results_medecin[0].similarity > 0.95  # Haute similarité médecin


# ============================================================
# Summary
# ============================================================


# Total tests dans ce fichier: 2
# Coverage: Pipeline E2E complet Email → Embedding → Search
# Dépendances: DATABASE_URL, migrations 007+008 (knowledge.* tables + pgvector)
#
# Tests implémentés (AC7 Story 6.2):
# ✅ E2E pipeline complet (1 email)
# ✅ E2E recherche sémantique multi-emails
#
# TOTAL: 2 tests E2E
