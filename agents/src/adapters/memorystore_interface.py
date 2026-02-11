#!/usr/bin/env python3
"""
Friday 2.0 - Interface abstraite MemoryStore pour graphe de connaissances.

Philosophie abstraction:
    Start Simple (PostgreSQL Day 1), Split When Pain (>300k vecteurs, latence >100ms).

    Cette interface permet de swap facilement le backend memorystore sans toucher
    au code métier (graph_populator, consumers, agents, etc.).

Backends supportés:
    - PostgreSQL + pgvector (Day 1) → Decision D19
    - Graphiti (futur, réévaluation août 2026) → Decision D3
    - Neo4j (futur, si besoin graphe complexe)
    - Qdrant (futur, si >300k vecteurs ou latence >100ms) → Decision D19

Extensibilité:
    Pour ajouter un nouveau backend :
    1. Créer classe XxxMemorystore(MemoryStore) qui implémente tous les @abstractmethod
    2. Ajouter case dans factory get_memorystore_adapter()
    3. Ajouter variable env MEMORYSTORE_PROVIDER=xxx
    4. Tests : Vérifier que XxxMemorystore passe tous les tests interface

Usage:
    from agents.src.adapters.memorystore import get_memorystore_adapter

    adapter = await get_memorystore_adapter()  # Retourne MemoryStore interface
    node_id = await adapter.create_node("person", "Antonio Lopez", {...})

Date: 2026-02-11
Version: 1.0.0 (Story 6.3)
"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Optional


# ============================================================
# Enums partagés (cohérence entre backends)
# ============================================================


class NodeType(str, Enum):
    """
    Types de nœuds dans le graphe de connaissances (10 types).

    Utilisés par tous les backends memorystore pour garantir cohérence.
    """

    PERSON = "person"
    EMAIL = "email"
    DOCUMENT = "document"
    EVENT = "event"
    TASK = "task"
    ENTITY = "entity"
    CONVERSATION = "conversation"
    TRANSACTION = "transaction"
    FILE = "file"
    REMINDER = "reminder"


class RelationType(str, Enum):
    """
    Types de relations entre nœuds (14 types).

    Utilisés par tous les backends memorystore pour garantir cohérence.
    """

    SENT_BY = "sent_by"
    RECEIVED_BY = "received_by"
    ATTACHED_TO = "attached_to"
    MENTIONS = "mentions"
    RELATED_TO = "related_to"
    ASSIGNED_TO = "assigned_to"
    CREATED_FROM = "created_from"
    SCHEDULED = "scheduled"
    REFERENCES = "references"
    PART_OF = "part_of"
    PAID_WITH = "paid_with"
    BELONGS_TO = "belongs_to"
    REMINDS_ABOUT = "reminds_about"
    SUPERSEDES = "supersedes"


# ============================================================
# Interface Abstraite
# ============================================================


class MemoryStore(ABC):
    """
    Interface abstraite pour backends memorystore (graphe de connaissances).

    Permet de swap PostgreSQL → Graphiti/Neo4j/Qdrant en changeant 1 variable env.

    Day 1 Backend:
        PostgreSQL + pgvector (Decision D19)

    Backends futurs:
        - Graphiti (si maturité atteinte ~août 2026) → Decision D3
        - Neo4j (si besoin requêtes graphe complexes)
        - Qdrant (si >300k vecteurs ou latence pgvector >100ms) → Decision D19
    """

    # ============================================================
    # Node Operations
    # ============================================================

    @abstractmethod
    async def create_node(
        self,
        node_type: str,
        name: str,
        metadata: dict[str, Any],
        embedding: Optional[list[float]] = None,
        source: Optional[str] = None,
    ) -> str:
        """
        Crée un nouveau nœud dans le graphe.

        Args:
            node_type: Type de nœud (valeurs: NodeType enum)
            name: Nom du nœud (ex: "Antonio Lopez", "Email RE: Projet X")
            metadata: Métadonnées JSON (ex: {email, company, date, etc.})
            embedding: Vecteur d'embedding optionnel (1024 dims par défaut)
            source: Source du nœud (backward compatibility, deprecated)

        Returns:
            UUID du nœud créé (string)

        Raises:
            ValueError: Si node_type n'est pas dans NodeType enum
            Exception: Si échec création (DB down, constraint violation, etc.)

        Example:
            node_id = await adapter.create_node(
                node_type="person",
                name="Antonio Lopez",
                metadata={"email": "antonio@example.com", "role": "Mainteneur"},
            )
        """
        pass

    @abstractmethod
    async def get_or_create_node(
        self,
        node_type: str,
        name: str,
        metadata: dict[str, Any],
        embedding: Optional[list[float]] = None,
    ) -> str:
        """
        Récupère un nœud existant OU le crée s'il n'existe pas.

        Logique de déduplication :
            - Pour type=person : match sur metadata.email si présent, sinon nom exact
            - Pour type=document : match sur metadata.source_id
            - Pour type=topic : match sur nom exact (case-insensitive)

        Args:
            node_type: Type de nœud (valeurs: NodeType enum)
            name: Nom du nœud
            metadata: Métadonnées JSON
            embedding: Vecteur d'embedding optionnel

        Returns:
            UUID du nœud (existant ou créé)

        Example:
            node_id = await adapter.get_or_create_node(
                node_type="person",
                name="Antonio Lopez",
                metadata={"email": "antonio@example.com"},
            )
        """
        pass

    @abstractmethod
    async def get_node_by_id(self, node_id: str) -> Optional[dict[str, Any]]:
        """
        Récupère un nœud par son ID.

        Args:
            node_id: UUID du nœud

        Returns:
            Dictionnaire {id, type, name, metadata, created_at} ou None si introuvable

        Example:
            node = await adapter.get_node_by_id("uuid-123")
            if node:
                print(node["name"])
        """
        pass

    @abstractmethod
    async def get_nodes_by_type(
        self, node_type: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Récupère tous les nœuds d'un type donné.

        Args:
            node_type: Type de nœud (valeurs: NodeType enum)
            limit: Nombre maximal de résultats (default: 100)

        Returns:
            Liste de nœuds [{id, type, name, metadata, created_at}, ...]

        Example:
            emails = await adapter.get_nodes_by_type("email", limit=50)
        """
        pass

    # ============================================================
    # Edge Operations
    # ============================================================

    @abstractmethod
    async def create_edge(
        self,
        from_node_id: str,
        to_node_id: str,
        relation_type: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Crée une relation (edge) entre deux nœuds.

        Args:
            from_node_id: UUID du nœud source
            to_node_id: UUID du nœud cible
            relation_type: Type de relation (valeurs: RelationType enum)
            metadata: Métadonnées optionnelles (ex: {confidence: 0.95, context: "..."})

        Returns:
            UUID de l'edge créée (string)

        Raises:
            ValueError: Si relation_type n'est pas dans RelationType enum
            Exception: Si from_node_id ou to_node_id introuvable

        Example:
            edge_id = await adapter.create_edge(
                from_node_id="email-uuid",
                to_node_id="person-uuid",
                relation_type="sent_by",
                metadata={"confidence": 0.98},
            )
        """
        pass

    @abstractmethod
    async def get_edges_by_type(
        self, relation_type: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Récupère toutes les relations d'un type donné.

        Args:
            relation_type: Type de relation (valeurs: RelationType enum)
            limit: Nombre maximal de résultats (default: 100)

        Returns:
            Liste d'edges [{id, from_node_id, to_node_id, relation_type, metadata}, ...]

        Example:
            sent_edges = await adapter.get_edges_by_type("sent_by", limit=50)
        """
        pass

    @abstractmethod
    async def get_related_nodes(
        self,
        node_id: str,
        direction: str = "out",
        relation_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Récupère les nœuds reliés à un nœud donné.

        Args:
            node_id: UUID du nœud source
            direction: "out" (sortants), "in" (entrants), ou "both"
            relation_type: Filtrer par type de relation (optionnel)
            limit: Nombre maximal de résultats (default: 100)

        Returns:
            Liste de nœuds [{id, type, name, metadata, relation_type}, ...]

        Raises:
            ValueError: Si direction invalide (pas "out", "in", ou "both")

        Example:
            # Récupérer tous les emails envoyés par une personne
            emails = await adapter.get_related_nodes(
                node_id="person-uuid",
                direction="out",
                relation_type="sent_by",
            )
        """
        pass

    @abstractmethod
    async def get_node_with_relations(
        self, node_id: str, depth: int = 1
    ) -> dict[str, Any]:
        """
        Récupère un nœud avec ses relations sur N niveaux de profondeur.

        Args:
            node_id: UUID du nœud racine
            depth: Profondeur de récursion (1 = relations directes uniquement)

        Returns:
            Dictionnaire {node, edges_out, edges_in}
            - node: {id, type, name, metadata, created_at}
            - edges_out: liste de nœuds reliés sortants
            - edges_in: liste de nœuds reliés entrants

        Raises:
            ValueError: Si node_id introuvable

        Example:
            result = await adapter.get_node_with_relations("email-uuid", depth=2)
            print(result["node"]["name"])
            print(f"Envoyé par: {result['edges_in']}")
        """
        pass

    # ============================================================
    # Graph Query Operations
    # ============================================================

    @abstractmethod
    async def query_path(
        self, from_node_id: str, to_node_id: str, max_depth: int = 3
    ) -> list[dict[str, Any]]:
        """
        Trouve le chemin le plus court entre deux nœuds (BFS).

        Args:
            from_node_id: UUID du nœud source
            to_node_id: UUID du nœud cible
            max_depth: Profondeur maximale de recherche (default: 3)

        Returns:
            Liste d'edges formant le chemin [{relation_type, from_node_id, to_node_id}, ...]
            ou [] si aucun chemin trouvé

        Example:
            path = await adapter.query_path("person-uuid", "document-uuid")
            # Résultat: [
            #     {from_node_id: "person-uuid", to_node_id: "email-uuid", relation_type: "sent_by"},
            #     {from_node_id: "email-uuid", to_node_id: "document-uuid", relation_type: "attached_to"}
            # ]
        """
        pass

    @abstractmethod
    async def query_temporal(
        self,
        start_date: datetime,
        end_date: datetime,
        node_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Requête temporelle : récupère les nœuds créés dans une période donnée.

        Args:
            start_date: Date de début (inclusive)
            end_date: Date de fin (inclusive)
            node_type: Filtrer par type de nœud (optionnel)
            limit: Nombre maximal de résultats (default: 100)

        Returns:
            Liste de nœuds [{id, type, name, metadata, created_at}, ...]
            triés par created_at DESC

        Example:
            # Récupérer tous les emails de la semaine dernière
            from datetime import datetime, timedelta
            emails = await adapter.query_temporal(
                start_date=datetime.now() - timedelta(days=7),
                end_date=datetime.now(),
                node_type="email",
            )
        """
        pass

    # ============================================================
    # Semantic Search (pgvector integration)
    # ============================================================

    @abstractmethod
    async def semantic_search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        score_threshold: float = 0.7,
        source_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Recherche sémantique via embeddings (pgvector cosine distance).

        Args:
            query_embedding: Vecteur de la requête (1024 floats pour Voyage AI)
            limit: Nombre maximal de résultats (default: 10)
            score_threshold: Seuil de similarité cosine 0.0-1.0 (default: 0.7)
            source_type: Filtrer par type de source (optionnel)

        Returns:
            Liste de résultats [{node_id, score, metadata}, ...]
            triés par score DESC (similarité)

        Example:
            # Rechercher documents similaires à une requête
            results = await adapter.semantic_search(
                query_embedding=query_vector,
                limit=10,
                score_threshold=0.8,
                source_type="document",
            )
        """
        pass
