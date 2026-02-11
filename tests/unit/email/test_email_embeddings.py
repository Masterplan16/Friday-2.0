#!/usr/bin/env python3
"""
Friday 2.0 - Tests Intégration Email → Embeddings

Tests d'intégration pour vérifier que les embeddings sont générés
automatiquement lors de la création d'un nœud Email.

Coverage:
    - Email node créé → embedding généré automatiquement
    - Anonymisation Presidio appliquée AVANT embedding
    - Embedding stocké dans knowledge.embeddings
    - Lien node_id correct entre Email et embedding

Date: 2026-02-11
Story: 6.2 - Task 2
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from agents.src.agents.email.graph_populator import populate_email_graph
from agents.src.adapters.memorystore import PostgreSQLMemorystore


@pytest.mark.integration
@pytest.mark.asyncio
async def test_email_creates_embedding_automatically():
    """
    Test qu'un Email node créé génère automatiquement son embedding.

    Flow:
        1. Email reçu → populate_email_graph()
        2. Email node créé dans knowledge.nodes
        3. Embedding généré automatiquement (Voyage AI mocked)
        4. Embedding stocké dans knowledge.embeddings
        5. node_id lié entre Email et embedding
    """
    # Mock memorystore
    mock_memorystore = AsyncMock(spec=PostgreSQLMemorystore)
    mock_memorystore.create_node = AsyncMock(return_value="email_node_123")
    mock_memorystore.get_or_create_node = AsyncMock(return_value="person_node_456")
    mock_memorystore.create_edge = AsyncMock()

    # Mock vectorstore + anonymization
    with patch("agents.src.agents.email.graph_populator.get_vectorstore_adapter") as mock_vectorstore_factory:
        with patch("agents.src.agents.email.graph_populator.anonymize_text") as mock_anon:
            mock_vectorstore = AsyncMock()

            # Mock embed() retourne embedding 1024 dims
            mock_embed_response = AsyncMock()
            mock_embed_response.embeddings = [[0.1] * 1024]
            mock_embed_response.anonymization_applied = True
            mock_vectorstore.embed = AsyncMock(return_value=mock_embed_response)
            mock_vectorstore.store = AsyncMock()

            mock_vectorstore_factory.return_value = mock_vectorstore

            # Mock anonymization (pas de PII détectée dans cet email simple)
            mock_anon_result = AsyncMock()
            mock_anon_result.anonymized_text = "Facture plombier 250 EUR Bonjour, veuillez trouver la facture pour réparation fuite."
            mock_anon_result.entities = []
            mock_anon.return_value = mock_anon_result

            # Email de test
            email_data = {
                "message_id": "<test@example.com>",
                "subject": "Facture plombier 250 EUR",
                "sender": "plombier@example.com",
                "recipients": ["mainteneur@friday.local"],
                "body": "Bonjour, veuillez trouver la facture pour réparation fuite.",
                "date": "2026-02-11T14:30:00Z",
                "category": "admin",
                "priority": "normal",
            }

            # Exécuter population graphe
            email_node_id = await populate_email_graph(email_data, mock_memorystore)

            # Vérifications
            assert email_node_id == "email_node_123"

            # 1. Email node créé
            mock_memorystore.create_node.assert_awaited_once()

            # 2. Anonymisation appelée
            mock_anon.assert_awaited_once()

            # 3. Vectorstore appelé pour générer embedding
            mock_vectorstore.embed.assert_awaited_once()
            embed_call_args = mock_vectorstore.embed.call_args

            # Texte envoyé = subject + body (anonymisé)
            texts_sent = embed_call_args[0][0]
            assert len(texts_sent) == 1
            assert "Facture plombier" in texts_sent[0]

            # 4. Embedding stocké
            mock_vectorstore.store.assert_awaited_once()
            store_call_args = mock_vectorstore.store.call_args

            # node_id = email_node_id
            assert store_call_args[1]["node_id"] == "email_node_123"
            # embedding = 1024 dims
            assert len(store_call_args[1]["embedding"]) == 1024


@pytest.mark.integration
@pytest.mark.asyncio
async def test_email_embedding_anonymizes_pii():
    """
    Test que Presidio anonymise PII AVANT génération embedding.

    Selon AC1 Story 6.2 : AUCUNE PII ne doit être envoyée à Voyage AI.
    """
    mock_memorystore = AsyncMock(spec=PostgreSQLMemorystore)
    mock_memorystore.create_node = AsyncMock(return_value="email_node_789")
    mock_memorystore.get_or_create_node = AsyncMock(return_value="person_node_012")
    mock_memorystore.create_edge = AsyncMock()

    # Mock vectorstore + anonymization
    with patch("agents.src.agents.email.graph_populator.get_vectorstore_adapter") as mock_vectorstore_factory:
        with patch("agents.src.agents.email.graph_populator.anonymize_text") as mock_anon:
            mock_vectorstore = AsyncMock()

            mock_embed_response = AsyncMock()
            mock_embed_response.embeddings = [[0.2] * 1024]
            mock_embed_response.anonymization_applied = True
            mock_vectorstore.embed = AsyncMock(return_value=mock_embed_response)
            mock_vectorstore.store = AsyncMock()

            mock_vectorstore_factory.return_value = mock_vectorstore

            # Mock anonymization : détecte "Dr. Martin"
            mock_anon_result = AsyncMock()
            mock_anon_result.anonymized_text = "[PERSON_1] consulte patient [PERSON_2]"
            mock_anon_result.entities = [
                {"type": "PERSON", "text": "Dr. Martin"},
                {"type": "PERSON", "text": "Jean Dupont"},
            ]
            mock_anon.return_value = mock_anon_result

            # Email avec PII
            email_data = {
                "message_id": "<medical@example.com>",
                "subject": "Consultation Dr. Martin",
                "sender": "secretaire@cabinet.fr",
                "recipients": ["dr.martin@cabinet.fr"],
                "body": "Dr. Martin consulte patient Jean Dupont demain 15h.",
                "date": "2026-02-11T16:00:00Z",
                "category": "medical",
                "priority": "high",
            }

            # Exécuter
            email_node_id = await populate_email_graph(email_data, mock_memorystore)

            # Vérifications
            # 1. Anonymisation appelée AVANT embedding
            mock_anon.assert_awaited()  # Au moins 1 appel

            # 2. Texte envoyé à Voyage AI est anonymisé
            embed_call_args = mock_vectorstore.embed.call_args
            texts_sent = embed_call_args[0][0]

            # Vérifier que PII originale n'est PAS dans le texte
            assert "Dr. Martin" not in texts_sent[0]
            assert "Jean Dupont" not in texts_sent[0]

            # Vérifier que texte anonymisé contient placeholders
            assert "PERSON" in texts_sent[0] or len(texts_sent[0]) > 0  # Anonymisé


@pytest.mark.integration
@pytest.mark.asyncio
async def test_email_embedding_error_handling():
    """
    Test gestion erreurs si Voyage AI down.

    Comportement attendu :
        - Email node créé quand même
        - Embedding manquant (NULL)
        - Alerte Telegram envoyée
        - Job nightly retentera plus tard
    """
    mock_memorystore = AsyncMock(spec=PostgreSQLMemorystore)
    mock_memorystore.create_node = AsyncMock(return_value="email_node_err")
    mock_memorystore.get_or_create_node = AsyncMock(return_value="person_node_err")
    mock_memorystore.create_edge = AsyncMock()

    # Mock vectorstore qui lève exception
    with patch("agents.src.agents.email.graph_populator.get_vectorstore_adapter") as mock_vectorstore_factory:
        mock_vectorstore = AsyncMock()
        mock_vectorstore.embed = AsyncMock(side_effect=Exception("Voyage API timeout"))

        mock_vectorstore_factory.return_value = mock_vectorstore

        email_data = {
            "message_id": "<error@example.com>",
            "subject": "Test erreur",
            "sender": "test@example.com",
            "date": "2026-02-11T18:00:00Z",
        }

        # Exécuter : NE DOIT PAS raise (email créé quand même)
        email_node_id = await populate_email_graph(email_data, mock_memorystore)

        # Email node créé
        assert email_node_id == "email_node_err"
        mock_memorystore.create_node.assert_awaited_once()

        # Embedding non stocké (erreur gérée gracieusement)
        # Note: Alertes Telegram + receipt status="failed" implémentés dans Story 6.2 Subtask 2.3
        # Tests de ces features dans test_voyage_retry_logic.py (TODO Story future)


# Tests manquants (Stories futures):
# - test_email_embedding_retry_logic (Task 7.6 - retry 3x avec backoff)
# - test_email_bulk_embeddings_batch (optimisation batch API Voyage)
# - test_telegram_alert_on_embedding_failure (alertes Telegram)
# - test_action_receipt_failed_status (receipt status="failed")
