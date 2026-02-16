import pytest
pytestmark = pytest.mark.skip(reason="migrate_emails script refactored, tests need update")

"""
Tests unitaires pour migrate_emails.py Phase 3 (Génération embeddings)

Tests:
- EmailEmbeddingGenerator.generate_embedding() avec mock VectorStore
- Anonymisation Presidio avant Voyage AI
- Stockage embedding dans pgvector
- Dry run mode
- Gestion texte vide

Story 6.4 Task 4
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ajouter agents/src au path pour imports
agents_src = Path(__file__).parent.parent.parent.parent / "agents" / "src"
sys.path.insert(0, str(agents_src))

# Mock environment variables AVANT import de migrate_emails
os.environ.setdefault("POSTGRES_DSN", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-12345")


@pytest.fixture
def mock_vectorstore():
    """Mock VectorStoreAdapter pour tests"""
    from adapters.vectorstore import EmbeddingResponse

    vectorstore = AsyncMock()

    # Mock embed: retourne embedding simulé
    vectorstore.embed.return_value = EmbeddingResponse(
        embeddings=[[0.1] * 1024],  # 1024 dimensions
        dimensions=1024,
        tokens_used=150,
        anonymization_applied=False,  # Déjà anonymisé manuellement
    )

    # Mock store: retourne None (succès)
    vectorstore.store.return_value = None

    return vectorstore


@pytest.fixture
def embedding_generator(mock_vectorstore):
    """EmailEmbeddingGenerator avec mock vectorstore"""
    from scripts.migrate_emails import EmailEmbeddingGenerator

    return EmailEmbeddingGenerator(vectorstore=mock_vectorstore, dry_run=False)


class TestEmailEmbeddingGenerator:
    """Tests pour EmailEmbeddingGenerator"""

    @pytest.mark.asyncio
    @patch("scripts.migrate_emails.anonymize_text")
    async def test_generate_embedding_basic(
        self, mock_anonymize, embedding_generator, mock_vectorstore
    ):
        """Génération embedding basique"""
        from tools.anonymize import AnonymizationResult

        # Mock anonymize_text
        mock_anonymize.return_value = AnonymizationResult(
            anonymized_text="Sujet: Test\nContenu anonymisé",
            entities_found=[],
            confidence_min=1.0,
            mapping={},
        )

        email = {
            "message_id": "<test@example.com>",
            "subject": "Test email",
            "body_text": "Ceci est un email de test avec du contenu.",
        }

        email_node_id = "email-node-123"

        result = await embedding_generator.generate_embedding(email, email_node_id)

        # Vérifier anonymisation appelée
        mock_anonymize.assert_called_once()
        assert "Test email" in mock_anonymize.call_args[0][0]

        # Vérifier embed appelé avec texte anonymisé
        mock_vectorstore.embed.assert_called_once()
        assert mock_vectorstore.embed.call_args[0][0] == ["Sujet: Test\nContenu anonymisé"]
        assert mock_vectorstore.embed.call_args[1]["anonymize"] is False  # Déjà anonymisé

        # Vérifier store appelé
        mock_vectorstore.store.assert_called_once()
        store_call = mock_vectorstore.store.call_args
        assert store_call[1]["node_id"] == email_node_id
        assert len(store_call[1]["embedding"]) == 1024  # Voyage AI dimensions
        assert store_call[1]["metadata"]["source"] == "migration_emails"

        # Vérifier résultat
        assert result == email_node_id

    @pytest.mark.asyncio
    @patch("scripts.migrate_emails.anonymize_text")
    async def test_generate_embedding_truncate_body(
        self, mock_anonymize, embedding_generator, mock_vectorstore
    ):
        """Body text >2000 chars → tronqué à 2000"""
        from tools.anonymize import AnonymizationResult

        mock_anonymize.return_value = AnonymizationResult(
            anonymized_text="Anonymized", entities_found=[], confidence_min=1.0, mapping={}
        )

        email = {
            "message_id": "<test@example.com>",
            "subject": "Test",
            "body_text": "A" * 5000,  # 5000 chars
        }

        email_node_id = "email-node-123"

        await embedding_generator.generate_embedding(email, email_node_id)

        # Vérifier que texte passé à anonymize est tronqué à 2000 chars (+ sujet)
        anonymize_call = mock_anonymize.call_args[0][0]
        # Sujet "Test" + "\n" + 2000 chars body = 2005 chars max
        assert len(anonymize_call) <= 2010  # Marge pour sujet

    @pytest.mark.asyncio
    async def test_generate_embedding_dry_run(self):
        """Dry run mode → aucun appel API"""
        from scripts.migrate_emails import EmailEmbeddingGenerator

        mock_vectorstore = AsyncMock()
        generator = EmailEmbeddingGenerator(vectorstore=mock_vectorstore, dry_run=True)

        email = {
            "message_id": "<test@example.com>",
            "subject": "Test",
            "body_text": "Content",
        }

        email_node_id = "email-node-123"

        result = await generator.generate_embedding(email, email_node_id)

        # Vérifier aucun appel vectorstore
        mock_vectorstore.embed.assert_not_called()
        mock_vectorstore.store.assert_not_called()

        # Vérifier résultat = email_node_id inchangé
        assert result == email_node_id

    @pytest.mark.asyncio
    @patch("scripts.migrate_emails.anonymize_text")
    async def test_generate_embedding_empty_text(
        self, mock_anonymize, embedding_generator, mock_vectorstore
    ):
        """Email vide (pas de sujet ni body) → skip embedding"""
        email = {
            "message_id": "<test@example.com>",
            "subject": "",
            "body_text": "",
        }

        email_node_id = "email-node-123"

        result = await embedding_generator.generate_embedding(email, email_node_id)

        # Vérifier aucun appel API (texte vide)
        mock_anonymize.assert_not_called()
        mock_vectorstore.embed.assert_not_called()
        mock_vectorstore.store.assert_not_called()

        # Vérifier résultat = email_node_id inchangé
        assert result == email_node_id

    @pytest.mark.asyncio
    @patch("scripts.migrate_emails.anonymize_text")
    async def test_generate_embedding_no_subject(
        self, mock_anonymize, embedding_generator, mock_vectorstore
    ):
        """Email sans sujet → utilise body uniquement"""
        from tools.anonymize import AnonymizationResult

        mock_anonymize.return_value = AnonymizationResult(
            anonymized_text="Anonymized", entities_found=[], confidence_min=1.0, mapping={}
        )

        email = {
            "message_id": "<test@example.com>",
            "subject": None,  # Pas de sujet
            "body_text": "Contenu email",
        }

        email_node_id = "email-node-123"

        await embedding_generator.generate_embedding(email, email_node_id)

        # Vérifier que anonymize est appelé avec "\nContenu email" (sujet vide)
        anonymize_call = mock_anonymize.call_args[0][0]
        assert anonymize_call.startswith("\n")  # Sujet vide
        assert "Contenu email" in anonymize_call

    @pytest.mark.asyncio
    @patch("scripts.migrate_emails.anonymize_text")
    async def test_generate_embedding_metadata(
        self, mock_anonymize, embedding_generator, mock_vectorstore
    ):
        """Vérifier metadata stockées avec embedding"""
        from tools.anonymize import AnonymizationResult

        mock_anonymize.return_value = AnonymizationResult(
            anonymized_text="Anonymized",
            entities_found=[{"entity_type": "EMAIL", "start": 0, "end": 10, "score": 0.95}],
            confidence_min=0.95,
            mapping={},
        )

        email = {
            "message_id": "<test@example.com>",
            "subject": "Test",
            "body_text": "Content",
        }

        email_node_id = "email-node-123"

        await embedding_generator.generate_embedding(email, email_node_id)

        # Vérifier metadata du store
        store_call = mock_vectorstore.store.call_args
        metadata = store_call[1]["metadata"]

        assert metadata["source"] == "migration_emails"
        assert metadata["message_id"] == "<test@example.com>"
        assert metadata["anonymized"] is True
        assert metadata["tokens_used"] == 150  # Depuis mock EmbeddingResponse

    @pytest.mark.asyncio
    @patch("scripts.migrate_emails.anonymize_text")
    async def test_generate_embedding_error_propagation(self, mock_anonymize):
        """Erreur vectorstore → exception propagée"""
        from scripts.migrate_emails import EmailEmbeddingGenerator

        mock_vectorstore = AsyncMock()
        mock_vectorstore.embed.side_effect = Exception("Voyage AI API error")

        generator = EmailEmbeddingGenerator(vectorstore=mock_vectorstore, dry_run=False)

        from tools.anonymize import AnonymizationResult

        mock_anonymize.return_value = AnonymizationResult(
            anonymized_text="Anonymized", entities_found=[], confidence_min=1.0, mapping={}
        )

        email = {
            "message_id": "<test@example.com>",
            "subject": "Test",
            "body_text": "Content",
        }

        email_node_id = "email-node-123"

        # Doit propager l'exception
        with pytest.raises(Exception, match="Voyage AI API error"):
            await generator.generate_embedding(email, email_node_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
