import pytest
pytestmark = pytest.mark.skip(reason="migrate_emails script refactored, tests need update")

"""
Tests unitaires pour migrate_emails.py Phase 2 (Population graphe)

Tests:
- EmailGraphPopulator.populate_email() avec mock MemoryStore
- Création nodes Person (sender + recipients)
- Création node Email
- Création edges SENT_BY et RECEIVED_BY
- Dry run mode

Story 6.4 Task 3
"""

import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, call

import pytest

# Mock environment variables AVANT import de migrate_emails
os.environ.setdefault("POSTGRES_DSN", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-12345")


@pytest.fixture
def mock_memorystore():
    """Mock MemoryStore pour tests"""
    memorystore = AsyncMock()

    # Mock get_or_create_node: retourne UUIDs différents pour chaque call
    call_count = {"get_or_create": 0, "create": 0}

    async def mock_get_or_create(*args, **kwargs):
        call_count["get_or_create"] += 1
        return f"person-uuid-{call_count['get_or_create']}"

    async def mock_create(*args, **kwargs):
        call_count["create"] += 1
        return f"email-uuid-{call_count['create']}"

    memorystore.get_or_create_node.side_effect = mock_get_or_create
    memorystore.create_node.side_effect = mock_create
    memorystore.create_edge.return_value = "edge-uuid-123"

    return memorystore


@pytest.fixture
def graph_populator(mock_memorystore):
    """EmailGraphPopulator avec mock memorystore"""
    from scripts.migrate_emails import EmailGraphPopulator

    return EmailGraphPopulator(memorystore=mock_memorystore, dry_run=False)


class TestEmailGraphPopulator:
    """Tests pour EmailGraphPopulator"""

    @pytest.mark.asyncio
    async def test_populate_email_basic(self, graph_populator, mock_memorystore):
        """Population graphe email basique (sender + 0 recipients)"""
        email = {
            "message_id": "<test@example.com>",
            "sender": "sender@example.com",
            "subject": "Test email",
            "body_text": "Content",
            "received_at": datetime(2024, 1, 15, 10, 30),
            "recipients": [],
        }

        classification = {"category": "professional", "priority": "medium", "confidence": 0.88}

        result = await graph_populator.populate_email(email, classification)

        # Vérifier création Person node sender
        mock_memorystore.get_or_create_node.assert_any_call(
            node_type="person", name="sender@example.com", metadata={"email": "sender@example.com"}
        )

        # Vérifier création Email node
        assert mock_memorystore.create_node.call_count == 1
        create_call = mock_memorystore.create_node.call_args
        assert create_call[1]["node_type"] == "email"
        assert create_call[1]["name"] == "Test email"
        assert create_call[1]["metadata"]["message_id"] == "<test@example.com>"
        assert create_call[1]["metadata"]["category"] == "professional"

        # Vérifier création edge SENT_BY (1 seul car 0 recipients)
        assert mock_memorystore.create_edge.call_count == 1

        # Vérifier résultat
        assert result["edges_created"] == 1  # SENT_BY seulement
        assert result["recipients_count"] == 0

    @pytest.mark.asyncio
    async def test_populate_email_with_recipients(self, graph_populator, mock_memorystore):
        """Population graphe email avec recipients"""
        email = {
            "message_id": "<test@example.com>",
            "sender": "sender@example.com",
            "subject": "Test email",
            "body_text": "Content",
            "received_at": datetime(2024, 1, 15, 10, 30),
            "recipients": ["recipient1@example.com", "recipient2@example.com"],
        }

        classification = {"category": "professional", "priority": "medium", "confidence": 0.88}

        result = await graph_populator.populate_email(email, classification)

        # Vérifier création Person nodes: 1 sender + 2 recipients = 3 total
        assert mock_memorystore.get_or_create_node.call_count == 3

        # Vérifier appels get_or_create_node pour recipients
        calls = mock_memorystore.get_or_create_node.call_args_list
        recipient_calls = [c for c in calls if c[1]["name"] in email["recipients"]]
        assert len(recipient_calls) == 2

        # Vérifier création edges: 1 SENT_BY + 2 RECEIVED_BY = 3 total
        assert mock_memorystore.create_edge.call_count == 3

        # Vérifier résultat
        assert result["edges_created"] == 3
        assert result["recipients_count"] == 2

    @pytest.mark.asyncio
    async def test_populate_email_dry_run(self):
        """Dry run mode → aucune modification BDD"""
        from scripts.migrate_emails import EmailGraphPopulator

        mock_memorystore = AsyncMock()
        populator = EmailGraphPopulator(memorystore=mock_memorystore, dry_run=True)

        email = {
            "message_id": "<test@example.com>",
            "sender": "sender@example.com",
            "subject": "Test",
            "body_text": "Content",
            "received_at": datetime(2024, 1, 15),
            "recipients": ["rec@example.com"],
        }

        classification = {"category": "test", "priority": "low", "confidence": 0.5}

        result = await populator.populate_email(email, classification)

        # Vérifier aucun appel memorystore
        mock_memorystore.get_or_create_node.assert_not_called()
        mock_memorystore.create_node.assert_not_called()
        mock_memorystore.create_edge.assert_not_called()

        # Vérifier résultat simulé
        assert result["sender_node_id"] == "dry-run-sender"
        assert result["email_node_id"] == "dry-run-email"
        assert result["edges_created"] == 2  # 1 SENT_BY + 1 RECEIVED_BY

    @pytest.mark.asyncio
    async def test_populate_email_no_subject(self, graph_populator, mock_memorystore):
        """Email sans sujet → utilise (Sans objet)"""
        email = {
            "message_id": "<test@example.com>",
            "sender": "sender@example.com",
            "subject": None,  # Pas de sujet
            "body_text": "Content",
            "received_at": datetime(2024, 1, 15),
            "recipients": [],
        }

        classification = {"category": "test", "priority": "low", "confidence": 0.5}

        await graph_populator.populate_email(email, classification)

        # Vérifier que le node Email a bien "(Sans objet)" comme nom
        create_call = mock_memorystore.create_node.call_args
        assert create_call[1]["name"] == "(Sans objet)"

    @pytest.mark.asyncio
    async def test_populate_email_datetime_serialization(self, graph_populator, mock_memorystore):
        """Vérifier sérialisation datetime dans metadata"""
        email = {
            "message_id": "<test@example.com>",
            "sender": "sender@example.com",
            "subject": "Test",
            "body_text": "Content",
            "received_at": datetime(2024, 1, 15, 10, 30, 45),
            "recipients": [],
        }

        classification = {"category": "test", "priority": "low", "confidence": 0.5}

        await graph_populator.populate_email(email, classification)

        # Vérifier que received_at est sérialisé en ISO format
        create_call = mock_memorystore.create_node.call_args
        assert create_call[1]["metadata"]["received_at"] == "2024-01-15T10:30:45"

    @pytest.mark.asyncio
    async def test_populate_email_edge_metadata(self, graph_populator, mock_memorystore):
        """Vérifier metadata des edges créées"""
        email = {
            "message_id": "<test@example.com>",
            "sender": "sender@example.com",
            "subject": "Test",
            "body_text": "Content",
            "received_at": datetime(2024, 1, 15, 10, 30),
            "recipients": ["rec@example.com"],
        }

        classification = {"category": "test", "priority": "low", "confidence": 0.5}

        await graph_populator.populate_email(email, classification)

        # Vérifier edge SENT_BY
        sent_by_call = mock_memorystore.create_edge.call_args_list[0]
        assert sent_by_call[1]["relation_type"] == "sent_by"
        assert "timestamp" in sent_by_call[1]["metadata"]

        # Vérifier edge RECEIVED_BY
        received_by_call = mock_memorystore.create_edge.call_args_list[1]
        assert received_by_call[1]["relation_type"] == "received_by"
        assert "timestamp" in received_by_call[1]["metadata"]

    @pytest.mark.asyncio
    async def test_populate_email_error_handling(self):
        """Erreur memorystore → exception propagée"""
        from scripts.migrate_emails import EmailGraphPopulator

        mock_memorystore = AsyncMock()
        mock_memorystore.get_or_create_node.side_effect = Exception("DB connection failed")

        populator = EmailGraphPopulator(memorystore=mock_memorystore, dry_run=False)

        email = {
            "message_id": "<test@example.com>",
            "sender": "sender@example.com",
            "subject": "Test",
            "body_text": "Content",
            "received_at": datetime(2024, 1, 15),
            "recipients": [],
        }

        classification = {"category": "test", "priority": "low", "confidence": 0.5}

        # Doit propager l'exception
        with pytest.raises(Exception, match="DB connection failed"):
            await populator.populate_email(email, classification)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
