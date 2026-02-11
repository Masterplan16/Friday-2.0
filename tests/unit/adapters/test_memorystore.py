"""Tests unitaires pour memorystore.py (adapters).

Test Strategy:
- Utiliser mocks asyncpg pour éviter dépendance BDD réelle
- Tester les 10 types de nœuds et 14 types de relations
- Tester logique de déduplication par type
- Tester validations ValueError
- Coverage cible: >=90%
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from agents.src.adapters.memorystore import (
    MemorystoreAdapter,
    NodeType,
    RelationType,
)


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg Pool."""
    pool = MagicMock()
    pool.acquire = AsyncMock()
    return pool


@pytest.fixture
def mock_conn():
    """Mock asyncpg Connection."""
    conn = AsyncMock()
    return conn


@pytest.fixture
async def memorystore(mock_db_pool):
    """Fixture MemorystoreAdapter avec mock pool."""
    adapter = MemorystoreAdapter(mock_db_pool)
    adapter._pgvector_initialized = True  # Simuler pgvector disponible
    return adapter


class TestNodeCreation:
    """Tests création de nœuds (Task 5.1, 5.2)."""

    @pytest.mark.asyncio
    async def test_create_node_person_valid(self, memorystore, mock_db_pool, mock_conn):
        """Test création nœud Person avec type valide."""
        # Setup mock
        mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
        expected_id = str(uuid4())
        mock_conn.fetchval = AsyncMock(return_value=expected_id)

        # Execute
        node_id = await memorystore.create_node(
            node_type="person",
            name="Antonio Lopez",
            metadata={"email": "antonio@example.com"},
            source="email"
        )

        # Assert
        assert node_id == expected_id
        mock_conn.fetchval.assert_called_once()
        # Vérifier que le SQL INSERT a été appelé
        call_args = mock_conn.fetchval.call_args
        assert "INSERT INTO knowledge.nodes" in call_args[0][0]
        assert call_args[0][2] == "person"  # validated_type.value
        assert call_args[0][3] == "Antonio Lopez"

    @pytest.mark.asyncio
    async def test_create_node_email_valid(self, memorystore, mock_db_pool, mock_conn):
        """Test création nœud Email avec type valide."""
        mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
        expected_id = str(uuid4())
        mock_conn.fetchval = AsyncMock(return_value=expected_id)

        node_id = await memorystore.create_node(
            node_type="email",
            name="RE: Projet Friday",
            metadata={"message_id": "abc123@example.com"},
            source="email"
        )

        assert node_id == expected_id
        call_args = mock_conn.fetchval.call_args
        assert call_args[0][2] == "email"

    @pytest.mark.asyncio
    async def test_create_node_invalid_type(self, memorystore):
        """Test ValidationError si type de nœud inconnu (Task 5.10)."""
        with pytest.raises(ValueError) as exc_info:
            await memorystore.create_node(
                node_type="invalid_type",
                name="Test",
                metadata={}
            )

        assert "Invalid node_type" in str(exc_info.value)
        assert "invalid_type" in str(exc_info.value)


class TestNodeDeduplication:
    """Tests déduplication de nœuds (Task 5.3, 5.4)."""

    @pytest.mark.asyncio
    async def test_get_or_create_person_dedup_by_email(self, memorystore, mock_db_pool, mock_conn):
        """Test déduplication Person sur metadata.email (Task 5.3)."""
        mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
        existing_id = str(uuid4())

        # Simuler nœud existant trouvé
        mock_conn.fetchval = AsyncMock(return_value=existing_id)

        node_id = await memorystore.get_or_create_node(
            node_type="person",
            name="Antonio Lopez",
            metadata={"email": "antonio@example.com"}
        )

        # Doit retourner l'ID existant (pas créer nouveau)
        assert node_id == existing_id
        # fetchval appelé 1 fois (SELECT), pas de création
        assert mock_conn.fetchval.call_count == 1

    @pytest.mark.asyncio
    async def test_get_or_create_document_dedup_by_source_id(self, memorystore, mock_db_pool, mock_conn):
        """Test déduplication Document sur metadata.source_id (Task 5.4)."""
        mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
        existing_id = str(uuid4())
        mock_conn.fetchval = AsyncMock(return_value=existing_id)

        node_id = await memorystore.get_or_create_node(
            node_type="document",
            name="Facture_2026.pdf",
            metadata={"source_id": "/docs/facture_2026.pdf"}
        )

        assert node_id == existing_id

    @pytest.mark.asyncio
    async def test_get_or_create_person_fallback_by_name(self, memorystore, mock_db_pool, mock_conn):
        """Test déduplication Person fallback sur nom si pas d'email (Bug M1 fix)."""
        mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
        existing_id = str(uuid4())
        mock_conn.fetchval = AsyncMock(return_value=existing_id)

        # Person sans email → déduplication par nom
        node_id = await memorystore.get_or_create_node(
            node_type="person",
            name="Dr. Martin",
            metadata={"phone": "+33612345678"}  # Pas d'email
        )

        assert node_id == existing_id
        # Vérifier que la requête utilise le fallback LOWER(name) = LOWER($3)
        call_args = mock_conn.fetchval.call_args
        assert "LOWER(name)" in call_args[0][0]


class TestEdgeCreation:
    """Tests création de relations (Task 5.5, 5.6)."""

    @pytest.mark.asyncio
    async def test_create_edge_sent_by_valid(self, memorystore, mock_db_pool, mock_conn):
        """Test création edge SENT_BY avec type valide (Task 5.5)."""
        mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
        expected_id = str(uuid4())
        mock_conn.fetchval = AsyncMock(return_value=expected_id)

        from_node = str(uuid4())
        to_node = str(uuid4())

        edge_id = await memorystore.create_edge(
            from_node_id=from_node,
            to_node_id=to_node,
            relation_type="sent_by",
            metadata={"confidence": 0.95}
        )

        assert edge_id == expected_id
        call_args = mock_conn.fetchval.call_args
        assert "INSERT INTO knowledge.edges" in call_args[0][0]
        assert call_args[0][4] == "sent_by"

    @pytest.mark.asyncio
    async def test_create_edge_attached_to_valid(self, memorystore, mock_db_pool, mock_conn):
        """Test création edge ATTACHED_TO (Task 5.6)."""
        mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
        expected_id = str(uuid4())
        mock_conn.fetchval = AsyncMock(return_value=expected_id)

        edge_id = await memorystore.create_edge(
            from_node_id=str(uuid4()),
            to_node_id=str(uuid4()),
            relation_type="attached_to"
        )

        assert edge_id == expected_id

    @pytest.mark.asyncio
    async def test_create_edge_invalid_relation_type(self, memorystore):
        """Test ValidationError si type de relation inconnu (Task 5.11)."""
        with pytest.raises(ValueError) as exc_info:
            await memorystore.create_edge(
                from_node_id=str(uuid4()),
                to_node_id=str(uuid4()),
                relation_type="invalid_relation"
            )

        assert "Invalid relation_type" in str(exc_info.value)
        assert "invalid_relation" in str(exc_info.value)


class TestGraphQueries:
    """Tests requêtes graphe (Task 5.7-5.14)."""

    @pytest.mark.asyncio
    async def test_get_related_nodes_direction_out(self, memorystore, mock_db_pool):
        """Test get_related_nodes() direction 'out' (Task 5.7)."""
        # Mock fetch pour retourner nœuds reliés
        mock_db_pool.fetch = AsyncMock(return_value=[
            {
                "id": uuid4(),
                "type": "person",
                "name": "John Doe",
                "metadata": {},
                "source": "email",
                "created_at": datetime.utcnow(),
                "relation_type": "sent_by",
                "edge_id": uuid4(),
                "edge_metadata": {}
            }
        ])

        node_id = str(uuid4())
        results = await memorystore.get_related_nodes(node_id, direction="out")

        assert len(results) == 1
        assert results[0]["type"] == "person"
        assert results[0]["relation_type"] == "sent_by"

    @pytest.mark.asyncio
    async def test_get_related_nodes_direction_in(self, memorystore, mock_db_pool):
        """Test get_related_nodes() direction 'in' (Task 5.8)."""
        mock_db_pool.fetch = AsyncMock(return_value=[
            {
                "id": uuid4(),
                "type": "email",
                "name": "Test Email",
                "metadata": {},
                "source": "email",
                "created_at": datetime.utcnow(),
                "relation_type": "received_by",
                "edge_id": uuid4(),
                "edge_metadata": {}
            }
        ])

        results = await memorystore.get_related_nodes(str(uuid4()), direction="in")

        assert len(results) == 1
        assert results[0]["type"] == "email"

    @pytest.mark.asyncio
    async def test_query_temporal(self, memorystore, mock_db_pool):
        """Test query_temporal() avec plage de dates (Task 5.9)."""
        now = datetime.utcnow()
        mock_db_pool.fetch = AsyncMock(return_value=[
            {
                "id": uuid4(),
                "type": "email",
                "name": "Recent Email",
                "metadata": {},
                "source": "email",
                "created_at": now,
                "updated_at": now
            }
        ])

        start = now - timedelta(days=1)
        end = now + timedelta(days=1)

        results = await memorystore.query_temporal("email", start, end)

        assert len(results) == 1
        assert results[0]["type"] == "email"

    @pytest.mark.asyncio
    async def test_get_node_with_relations_depth_1(self, memorystore, mock_db_pool):
        """Test get_node_with_relations() depth=1 (Task 5.12)."""
        node_id = str(uuid4())

        # Mock get_node_by_id
        mock_db_pool.fetchrow = AsyncMock(return_value={
            "id": node_id,
            "type": "email",
            "name": "Test Email",
            "metadata": {},
            "source": "email",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })

        # Mock get_related_nodes (2 calls: out + in)
        mock_db_pool.fetch = AsyncMock(return_value=[])

        result = await memorystore.get_node_with_relations(node_id, depth=1)

        assert "node" in result
        assert "edges_out" in result
        assert "edges_in" in result
        assert result["node"]["id"] == node_id

    @pytest.mark.asyncio
    async def test_query_path_simple(self, memorystore, mock_db_pool):
        """Test query_path() chemin simple (Task 5.13)."""
        from_id = str(uuid4())
        to_id = str(uuid4())
        edge_id = uuid4()

        # Mock connexion directe trouvée
        mock_db_pool.fetchrow = AsyncMock(return_value={
            "id": edge_id,
            "from_node_id": from_id,
            "to_node_id": to_id,
            "relation_type": "sent_by",
            "metadata": {}
        })

        path = await memorystore.query_path(from_id, to_id)

        assert path is not None
        assert len(path) == 1
        assert path[0]["relation_type"] == "sent_by"

    @pytest.mark.asyncio
    async def test_count_nodes_and_edges(self, memorystore, mock_db_pool):
        """Test count_nodes() / count_edges() (Task 5.15)."""
        mock_db_pool.fetchval = AsyncMock(return_value=42)

        count = await memorystore.count_nodes()
        assert count == 42

        count = await memorystore.count_edges()
        assert count == 42


class TestCircuitBreakers:
    """Tests circuit breakers et fallbacks."""

    @pytest.mark.asyncio
    async def test_semantic_search_pgvector_unavailable(self, memorystore):
        """Test semantic_search retourne [] si pgvector indisponible (Bug 4 fix)."""
        memorystore._pgvector_initialized = False

        results = await memorystore.semantic_search(
            query_embedding=[0.1] * 1024,
            limit=10
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_semantic_search_query_exception(self, memorystore, mock_db_pool):
        """Test semantic_search retourne [] si exception lors requête."""
        mock_db_pool.fetch = AsyncMock(side_effect=Exception("pgvector error"))

        results = await memorystore.semantic_search(
            query_embedding=[0.1] * 1024,
            limit=10
        )

        assert results == []


class TestNodeTypeEnumValidation:
    """Tests validation Enum pour tous les types (AC1)."""

    def test_all_10_node_types_valid(self):
        """Vérifier que les 10 types de nœuds sont définis dans l'Enum."""
        expected_types = {
            "person", "email", "document", "event", "task",
            "entity", "conversation", "transaction", "file", "reminder"
        }

        actual_types = {t.value for t in NodeType}
        assert actual_types == expected_types


class TestRelationTypeEnumValidation:
    """Tests validation Enum pour tous les types de relations (AC2)."""

    def test_all_14_relation_types_valid(self):
        """Vérifier que les 14 types de relations sont définis dans l'Enum."""
        expected_relations = {
            "sent_by", "received_by", "attached_to", "mentions", "related_to",
            "assigned_to", "created_from", "scheduled", "references", "part_of",
            "paid_with", "belongs_to", "reminds_about", "supersedes"
        }

        actual_relations = {r.value for r in RelationType}
        assert actual_relations == expected_relations
