"""Test E2E : Pipeline email entrant → graphe complet.

Test Strategy:
- Simuler réception email via EmailEngine
- Appeler populate_email_graph()
- Vérifier création nœuds (Email, Person sender/recipients)
- Vérifier création relations (SENT_BY, RECEIVED_BY)
- Vérifier déduplication Person sur email
- Base de données test réelle (PostgreSQL + pgvector)
"""

import os
from datetime import datetime
from pathlib import Path

import asyncpg
import pytest
from agents.src.adapters.memorystore import PostgreSQLMemorystore
from agents.src.agents.email.graph_populator import populate_email_graph

# Configuration BDD test (override avec env vars)
TEST_DB_CONFIG = {
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
}


@pytest.fixture(scope="module")
async def e2e_db_pool():
    """Créer BDD test pour E2E."""
    conn = await asyncpg.connect(database="postgres", **TEST_DB_CONFIG)

    test_db_name = "friday_test_e2e_email_graph"

    await conn.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
    await conn.execute(f"CREATE DATABASE {test_db_name}")
    await conn.close()

    pool = await asyncpg.create_pool(database=test_db_name, **TEST_DB_CONFIG)

    # Setup schemas + migrations
    async with pool.acquire() as conn:
        await conn.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
        await conn.execute("CREATE SCHEMA IF NOT EXISTS core")

        await conn.execute(
            """
            CREATE OR REPLACE FUNCTION core.update_updated_at()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """
        )

    migrations_dir = Path(__file__).parent.parent.parent / "database" / "migrations"

    async with pool.acquire() as conn:
        migration_007 = (migrations_dir / "007_knowledge_nodes_edges.sql").read_text()
        await conn.execute(migration_007)

        migration_008 = (migrations_dir / "008_knowledge_embeddings.sql").read_text()
        await conn.execute(migration_008)

    yield pool

    await pool.close()

    conn = await asyncpg.connect(database="postgres", **TEST_DB_CONFIG)
    await conn.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
    await conn.close()


@pytest.fixture
async def memorystore_e2e(e2e_db_pool):
    """Fixture PostgreSQLMemorystore pour E2E."""
    adapter = PostgreSQLMemorystore(e2e_db_pool)
    await adapter.init_pgvector()
    return adapter


@pytest.fixture
async def clean_graph(e2e_db_pool):
    """Nettoyer graphe entre tests."""
    async with e2e_db_pool.acquire() as conn:
        await conn.execute("TRUNCATE knowledge.nodes, knowledge.edges CASCADE")
    yield


@pytest.mark.e2e
class TestEmailToGraphPipeline:
    """Tests E2E pipeline email → graphe (Task 9.6)."""

    @pytest.mark.asyncio
    async def test_email_entrant_creates_full_graph(self, memorystore_e2e, clean_graph):
        """
        Test E2E complet : Email entrant → Person + Email + relations.

        Scénario :
        1. Email reçu de john@example.com
        2. Destinataires : antonio@example.com, alice@example.com
        3. Vérifier création 3 Person nodes (déduplication)
        4. Vérifier création 1 Email node
        5. Vérifier relation SENT_BY (Email → john)
        6. Vérifier relations RECEIVED_BY (Email → antonio, alice)
        """
        # Simuler email entrant
        email_data = {
            "message_id": "<test-email-001@example.com>",
            "subject": "RE: Projet Friday 2.0",
            "sender": "john@example.com",
            "sender_name": "John Doe",
            "recipients": ["antonio@example.com", "alice@example.com"],
            "body": "Bonjour Antonio, voici les documents...",
            "date": "2026-02-11T14:30:00Z",
            "category": "admin",
            "priority": "normal",
        }

        # Appeler graph_populator
        email_node_id = await populate_email_graph(email_data, memorystore_e2e)

        assert email_node_id is not None

        # Vérifier Email node créé
        email_node = await memorystore_e2e.get_node_by_id(email_node_id)
        assert email_node is not None
        assert email_node["type"] == "email"
        assert email_node["name"] == "RE: Projet Friday 2.0"
        assert email_node["metadata"]["message_id"] == email_data["message_id"]

        # Vérifier Person nodes créés (sender + 2 recipients = 3 total)
        person_nodes = await memorystore_e2e.get_nodes_by_type("person", limit=10)
        assert len(person_nodes) == 3

        # Vérifier emails des Person nodes
        person_emails = {p["metadata"]["email"] for p in person_nodes}
        assert person_emails == {"john@example.com", "antonio@example.com", "alice@example.com"}

        # Vérifier relation SENT_BY (Email → John)
        related_sender = await memorystore_e2e.get_related_nodes(
            email_node_id, relation_type="sent_by", direction="out"
        )
        assert len(related_sender) == 1
        assert related_sender[0]["metadata"]["email"] == "john@example.com"

        # Vérifier relations RECEIVED_BY (Email → Antonio, Alice)
        related_recipients = await memorystore_e2e.get_related_nodes(
            email_node_id, relation_type="received_by", direction="out"
        )
        assert len(related_recipients) == 2

        recipient_emails = {r["metadata"]["email"] for r in related_recipients}
        assert recipient_emails == {"antonio@example.com", "alice@example.com"}

    @pytest.mark.asyncio
    async def test_deduplication_person_by_email(self, memorystore_e2e, clean_graph):
        """
        Test déduplication Person : 2 emails du même expéditeur → 1 seul Person node.
        """
        # Email 1 de john@example.com
        email1_data = {
            "message_id": "<email1@example.com>",
            "subject": "Email 1",
            "sender": "john@example.com",
            "sender_name": "John Doe",
            "recipients": [],
            "date": "2026-02-11T10:00:00Z",
        }

        await populate_email_graph(email1_data, memorystore_e2e)

        # Email 2 de john@example.com (même sender)
        email2_data = {
            "message_id": "<email2@example.com>",
            "subject": "Email 2",
            "sender": "john@example.com",
            "sender_name": "John Doe",
            "recipients": [],
            "date": "2026-02-11T11:00:00Z",
        }

        await populate_email_graph(email2_data, memorystore_e2e)

        # Vérifier qu'un seul Person node existe pour john@example.com
        person_nodes = await memorystore_e2e.get_nodes_by_type("person", limit=10)
        assert len(person_nodes) == 1
        assert person_nodes[0]["metadata"]["email"] == "john@example.com"

        # Vérifier que les 2 emails existent
        email_nodes = await memorystore_e2e.get_nodes_by_type("email", limit=10)
        assert len(email_nodes) == 2

    @pytest.mark.asyncio
    async def test_email_with_attachments(self, memorystore_e2e, clean_graph):
        """
        Test Email avec PJ → relations ATTACHED_TO vers Document nodes.
        """
        # Créer Document node (simuler PJ déjà traitée par archiviste)
        doc_id = await memorystore_e2e.create_node(
            node_type="document",
            name="Facture_250EUR.pdf",
            metadata={"source_id": "/docs/facture_250.pdf", "mime_type": "application/pdf"},
            source="archiviste",
        )

        # Email avec PJ
        email_data = {
            "message_id": "<email-with-attachment@example.com>",
            "subject": "Facture plombier",
            "sender": "plombier@example.com",
            "recipients": ["antonio@example.com"],
            "date": "2026-02-11T14:00:00Z",
        }

        attachments = [
            {"doc_id": doc_id, "filename": "Facture_250EUR.pdf", "mime_type": "application/pdf"}
        ]

        email_node_id = await populate_email_graph(
            email_data, memorystore_e2e, attachments=attachments
        )

        # Vérifier relation ATTACHED_TO (Document → Email)
        related_docs = await memorystore_e2e.get_related_nodes(
            email_node_id, relation_type="attached_to", direction="in"
        )
        assert len(related_docs) == 1
        assert related_docs[0]["id"] == doc_id

    @pytest.mark.asyncio
    async def test_missing_required_fields_raises_error(self, memorystore_e2e, clean_graph):
        """
        Test validation : données email invalides lèvent ValueError.
        """
        # Email sans message_id
        invalid_email = {
            "subject": "Test",
            "sender": "test@example.com",
            "date": "2026-02-11T14:00:00Z",
        }

        with pytest.raises(ValueError, match="Missing required field"):
            await populate_email_graph(invalid_email, memorystore_e2e)
