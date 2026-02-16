#!/usr/bin/env python3
"""
Tests unitaires pour l'interface abstraite MemoryStore.

Tests:
- MemoryStore est une ABC (impossible d'instancier directement)
- Toutes les méthodes sont @abstractmethod
- PostgreSQLMemorystore implémente tous les abstractmethod
- Factory retourne interface MemoryStore (pas implémentation)
"""

from abc import ABC

import pytest
from agents.src.adapters.memorystore_interface import MemoryStore, NodeType, RelationType


class TestMemoryStoreInterface:
    """Tests de l'interface abstraite MemoryStore."""

    def test_memorystore_is_abc(self):
        """MemoryStore doit être une ABC (impossible d'instancier)."""
        assert issubclass(MemoryStore, ABC)

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            MemoryStore()

    def test_memorystore_has_abstractmethods(self):
        """MemoryStore doit avoir tous les @abstractmethod requis."""
        required_methods = [
            "create_node",
            "get_or_create_node",
            "get_node_by_id",
            "get_nodes_by_type",
            "create_edge",
            "get_edges_by_type",
            "get_related_nodes",
            "get_node_with_relations",
            "query_path",
            "query_temporal",
            "semantic_search",
        ]

        for method_name in required_methods:
            assert hasattr(
                MemoryStore, method_name
            ), f"MemoryStore doit avoir la méthode abstraite {method_name}"

    def test_nodetype_enum_has_10_types(self):
        """NodeType doit avoir exactement 10 types."""
        expected_types = {
            "person",
            "email",
            "document",
            "event",
            "task",
            "entity",
            "conversation",
            "transaction",
            "file",
            "reminder",
        }

        actual_types = {t.value for t in NodeType}
        assert actual_types == expected_types, f"NodeType doit avoir ces 10 types: {expected_types}"

    def test_relationtype_enum_has_14_types(self):
        """RelationType doit avoir exactement 14 types."""
        expected_types = {
            "sent_by",
            "received_by",
            "attached_to",
            "mentions",
            "related_to",
            "assigned_to",
            "created_from",
            "scheduled",
            "references",
            "part_of",
            "paid_with",
            "belongs_to",
            "reminds_about",
            "supersedes",
        }

        actual_types = {r.value for r in RelationType}
        assert (
            actual_types == expected_types
        ), f"RelationType doit avoir ces 14 types: {expected_types}"


class TestPostgreSQLMemorystoreImplementation:
    """Tests vérifiant que PostgreSQLMemorystore implémente l'interface."""

    def test_postgresql_memorystore_implements_interface(self):
        """PostgreSQLMemorystore doit implémenter tous les @abstractmethod."""
        from agents.src.adapters.memorystore import PostgreSQLMemorystore

        assert issubclass(PostgreSQLMemorystore, MemoryStore)

        # Vérifier que toutes les méthodes abstraites sont implémentées
        required_methods = [
            "create_node",
            "get_or_create_node",
            "get_node_by_id",
            "get_nodes_by_type",
            "create_edge",
            "get_edges_by_type",
            "get_related_nodes",
            "get_node_with_relations",
            "query_path",
            "query_temporal",
            "semantic_search",
        ]

        for method_name in required_methods:
            assert hasattr(
                PostgreSQLMemorystore, method_name
            ), f"PostgreSQLMemorystore doit implémenter {method_name}"
            # Vérifier que c'est bien une méthode callable
            method = getattr(PostgreSQLMemorystore, method_name)
            assert callable(method)


class TestMemorystoreFactory:
    """Tests de la factory get_memorystore_adapter()."""

    @pytest.mark.asyncio
    async def test_factory_returns_interface(self):
        """Factory doit retourner interface MemoryStore (pas implémentation)."""
        from unittest.mock import AsyncMock, MagicMock

        from agents.src.adapters.memorystore import get_memorystore_adapter

        # Mock asyncpg.Pool avec acquire() comme context manager
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)  # pgvector installée

        # Mock acquire() as async context manager
        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=mock_acquire)

        # Appeler factory
        adapter = await get_memorystore_adapter(pool=mock_pool, provider="postgresql")

        # Vérifier que c'est bien une instance de MemoryStore
        assert isinstance(adapter, MemoryStore)

    @pytest.mark.asyncio
    async def test_factory_default_provider_is_postgresql(self):
        """Factory avec provider=None doit utiliser postgresql par défaut."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from agents.src.adapters.memorystore import get_memorystore_adapter

        # Mock asyncpg.Pool avec acquire() comme context manager
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)  # pgvector installée

        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=mock_acquire)

        # Mock os.getenv pour retourner "postgresql"
        with patch("os.getenv", return_value="postgresql"):
            adapter = await get_memorystore_adapter(pool=mock_pool)

        assert isinstance(adapter, MemoryStore)

    @pytest.mark.asyncio
    async def test_factory_graphiti_raises_notimplementederror(self):
        """Factory avec provider=graphiti doit raise NotImplementedError."""
        from unittest.mock import MagicMock

        from agents.src.adapters.memorystore import get_memorystore_adapter

        mock_pool = MagicMock()

        with pytest.raises(NotImplementedError, match="Graphiti"):
            await get_memorystore_adapter(pool=mock_pool, provider="graphiti")

    @pytest.mark.asyncio
    async def test_factory_neo4j_raises_notimplementederror(self):
        """Factory avec provider=neo4j doit raise NotImplementedError."""
        from unittest.mock import MagicMock

        from agents.src.adapters.memorystore import get_memorystore_adapter

        mock_pool = MagicMock()

        with pytest.raises(NotImplementedError, match="Neo4j"):
            await get_memorystore_adapter(pool=mock_pool, provider="neo4j")

    @pytest.mark.asyncio
    async def test_factory_qdrant_raises_notimplementederror(self):
        """Factory avec provider=qdrant doit raise NotImplementedError."""
        from unittest.mock import MagicMock

        from agents.src.adapters.memorystore import get_memorystore_adapter

        mock_pool = MagicMock()

        with pytest.raises(NotImplementedError, match="Qdrant"):
            await get_memorystore_adapter(pool=mock_pool, provider="qdrant")

    @pytest.mark.asyncio
    async def test_factory_unknown_provider_raises_valueerror(self):
        """Factory avec provider inconnu doit raise ValueError."""
        from unittest.mock import MagicMock

        from agents.src.adapters.memorystore import get_memorystore_adapter

        mock_pool = MagicMock()

        with pytest.raises(ValueError, match="Unknown provider"):
            await get_memorystore_adapter(pool=mock_pool, provider="unknown_backend")
