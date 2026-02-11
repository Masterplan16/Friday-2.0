"""
Adaptateur memorystore pour Friday 2.0 - Abstraction graphe de connaissances.

Day 1 : PostgreSQL (tables knowledge.*) + pgvector (embeddings)
  Decision D19 : pgvector remplace Qdrant Day 1 (100k vecteurs, 1 utilisateur)
  Réévaluation Qdrant si >300k vecteurs ou latence >100ms
Futur possible (6+ mois) : Migration vers Graphiti (si mature) ou Neo4j

Ce module fournit une interface unifiée pour :
- Créer/récupérer des nœuds (entités : personnes, docs, topics)
- Créer des relations (edges) entre nœuds
- Recherche sémantique via pgvector (embeddings dans PostgreSQL)
- Requêtes sur le graphe PostgreSQL

Philosophie : Start simple (PostgreSQL relationnel + pgvector),
migrer uniquement si douleur réelle (>300k vecteurs, latence, filtres complexes).
"""

import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)


class NodeType(str, Enum):
    """Types de nœuds dans le graphe de connaissances (10 types)."""

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
    """Types de relations entre nœuds (14 types)."""

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


class MemorystoreAdapter:
    """
    Adaptateur pour le graphe de connaissances Friday 2.0.

    Backend Day 1 : PostgreSQL (knowledge.* tables) + pgvector (embeddings)
    """

    def __init__(self, db_pool: asyncpg.Pool):
        """
        Initialise l'adaptateur memorystore.

        Args:
            db_pool: Pool de connexions PostgreSQL (avec extension pgvector)
        """
        self.db_pool = db_pool
        self._pgvector_initialized = False

    async def init_pgvector(self) -> None:
        """
        Vérifie que l'extension pgvector est installée.
        L'extension est créée par la migration 008, cette méthode vérifie seulement.
        """
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                if not result:
                    logger.warning("pgvector extension not found - run migration 008 first")
                    return

            self._pgvector_initialized = True
            logger.info("pgvector extension verified")

        except Exception as e:
            logger.error("Failed to verify pgvector extension: %s", e)
            raise

    async def create_node(
        self,
        node_type: str,
        name: str,
        metadata: dict[str, Any],
        embedding: Optional[list[float]] = None,
    ) -> str:
        """
        Crée un nouveau nœud dans le graphe.

        Args:
            node_type: Type de nœud (person, document, topic, event, etc.)
            name: Nom du nœud (ex: "owner Lopez", "Email RE: Projet X")
            metadata: Métadonnées JSON (ex: {email, company, date, etc.})
            embedding: Vecteur d'embedding optionnel (1024 dims par défaut)

        Returns:
            UUID du nœud créé (string)
        """
        node_id = str(uuid.uuid4())
        now = datetime.utcnow()

        async with self.db_pool.acquire() as conn:
            # 1. Créer nœud dans PostgreSQL knowledge.nodes
            created_id = await conn.fetchval(
                """
                INSERT INTO knowledge.nodes (id, type, name, metadata, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                node_id,
                node_type,
                name,
                metadata,
                now,
                now,
            )

            logger.info("Created node: %s (%s)", name, node_type)

            # 2. Si embedding fourni, stocker dans pgvector
            if embedding:
                await self._store_embedding(conn, node_id, node_type, embedding, metadata)

        return str(created_id)

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
            node_type: Type de nœud
            name: Nom du nœud
            metadata: Métadonnées JSON
            embedding: Vecteur d'embedding optionnel

        Returns:
            UUID du nœud (existant ou créé)
        """
        email = metadata.get("email", "")
        source_id = metadata.get("source_id", "")

        async with self.db_pool.acquire() as conn:
            existing_id = await conn.fetchval(
                """
                SELECT id FROM knowledge.nodes
                WHERE type = $1 AND (
                    (type = 'person' AND metadata->>'email' = $2) OR
                    (type = 'document' AND metadata->>'source_id' = $3) OR
                    (type = 'topic' AND LOWER(name) = LOWER($4))
                )
                LIMIT 1
                """,
                node_type,
                email,
                source_id,
                name,
            )

        if existing_id:
            logger.debug("Node already exists: %s (%s)", name, existing_id)
            return str(existing_id)

        return await self.create_node(node_type, name, metadata, embedding)

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
            relation_type: Type de relation (authored, mentions, related_to, etc.)
            metadata: Métadonnées optionnelles (ex: {confidence: 0.95, context: "..."})

        Returns:
            UUID de l'edge créée (string)
        """
        edge_id = str(uuid.uuid4())
        now = datetime.utcnow()
        metadata = metadata or {}

        async with self.db_pool.acquire() as conn:
            created_id = await conn.fetchval(
                """
                INSERT INTO knowledge.edges
                (id, from_node_id, to_node_id, relation_type, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                edge_id,
                from_node_id,
                to_node_id,
                relation_type,
                metadata,
                now,
            )

        logger.info(
            "Created edge: %s -[%s]-> %s",
            from_node_id[:8],
            relation_type,
            to_node_id[:8],
        )

        return str(created_id)

    async def _store_embedding(
        self,
        conn: asyncpg.Connection,
        source_id: str,
        source_type: str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> None:
        """
        Stocke un embedding dans pgvector (knowledge.embeddings).

        Args:
            conn: Connexion PostgreSQL active
            source_id: UUID du nœud source
            source_type: Type de source (person, document, etc.)
            embedding: Vecteur d'embedding
            metadata: Métadonnées à stocker
        """
        # pgvector attend un string format '[0.1, 0.2, ...]'
        vector_str = "[" + ",".join(str(v) for v in embedding) + "]"

        await conn.execute(
            """
            INSERT INTO knowledge.embeddings
            (source_type, source_id, embedding, metadata)
            VALUES ($1, $2, $3::vector, $4)
            """,
            source_type,
            source_id,
            vector_str,
            metadata,
        )

        logger.debug("Stored embedding for node: %s", source_id)

    async def semantic_search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        score_threshold: float = 0.7,
        source_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Recherche sémantique via pgvector (cosine distance).

        Args:
            query_embedding: Vecteur de la requête
            limit: Nombre maximal de résultats
            score_threshold: Seuil de similarité cosine (0.0-1.0)
            source_type: Filtrer par type de source (optionnel)

        Returns:
            Liste de résultats [{node_id, score, metadata}, ...]
        """
        vector_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        # cosine distance: 1 - cosine_similarity
        # pgvector <=> = cosine distance, on veut similarity = 1 - distance
        if source_type:
            rows = await self.db_pool.fetch(
                """
                SELECT source_id, 1 - (embedding <=> $1::vector) AS score, metadata
                FROM knowledge.embeddings
                WHERE source_type = $2
                  AND 1 - (embedding <=> $1::vector) >= $3
                ORDER BY embedding <=> $1::vector
                LIMIT $4
                """,
                vector_str,
                source_type,
                score_threshold,
                limit,
            )
        else:
            rows = await self.db_pool.fetch(
                """
                SELECT source_id, 1 - (embedding <=> $1::vector) AS score, metadata
                FROM knowledge.embeddings
                WHERE 1 - (embedding <=> $1::vector) >= $2
                ORDER BY embedding <=> $1::vector
                LIMIT $3
                """,
                vector_str,
                score_threshold,
                limit,
            )

        return [
            {
                "node_id": str(row["source_id"]),
                "score": float(row["score"]),
                "metadata": row["metadata"],
            }
            for row in rows
        ]

    async def count_nodes(self, node_type: Optional[str] = None) -> int:
        """Compte le nombre de nœuds dans le graphe."""
        if node_type:
            return await self.db_pool.fetchval(
                "SELECT COUNT(*) FROM knowledge.nodes WHERE type = $1", node_type
            )
        return await self.db_pool.fetchval("SELECT COUNT(*) FROM knowledge.nodes")

    async def count_edges(self, relation_type: Optional[str] = None) -> int:
        """Compte le nombre de relations dans le graphe."""
        if relation_type:
            return await self.db_pool.fetchval(
                "SELECT COUNT(*) FROM knowledge.edges WHERE relation_type = $1",
                relation_type,
            )
        return await self.db_pool.fetchval("SELECT COUNT(*) FROM knowledge.edges")


# Factory function pour initialiser l'adaptateur
async def get_memorystore_adapter(
    db_pool: asyncpg.Pool,
) -> MemorystoreAdapter:
    """
    Factory pour créer et initialiser un MemorystoreAdapter.

    Args:
        db_pool: Pool PostgreSQL (avec extension pgvector installée)

    Returns:
        Instance MemorystoreAdapter initialisée
    """
    adapter = MemorystoreAdapter(db_pool)
    await adapter.init_pgvector()
    return adapter
