"""
Implémentation PostgreSQL du MemoryStore pour Friday 2.0.

Backend Day 1 : PostgreSQL (tables knowledge.*) + pgvector (embeddings)
  Decision D19 : pgvector remplace Qdrant Day 1 (100k vecteurs, 1 utilisateur)
  Réévaluation Qdrant si >300k vecteurs ou latence >100ms

Implémente l'interface MemoryStore avec PostgreSQL comme backend.

Pour swap vers Graphiti/Neo4j/Qdrant : créer nouvelle classe XxxMemorystore(MemoryStore)
et modifier MEMORYSTORE_PROVIDER env var.

Date: 2026-02-11
Version: 2.0.0 (Story 6.3 - Interface abstraite)
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Optional

import asyncpg

from .memorystore_interface import MemoryStore, NodeType, RelationType

logger = logging.getLogger(__name__)


class PostgreSQLMemorystore(MemoryStore):
    """
    Implémentation PostgreSQL de l'interface MemoryStore.

    Backend : PostgreSQL (knowledge.* tables) + pgvector (embeddings)

    Features:
        - Nœuds stockés dans knowledge.nodes
        - Relations stockées dans knowledge.edges
        - Embeddings stockés dans knowledge.embeddings (pgvector)
        - Recherche sémantique via cosine distance (<=>)
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
        source: Optional[str] = None,
    ) -> str:
        """
        Crée un nouveau nœud dans le graphe.

        Args:
            node_type: Type de nœud (person, document, topic, event, etc.)
            name: Nom du nœud (ex: "owner Lopez", "Email RE: Projet X")
            metadata: Métadonnées JSON (ex: {email, company, date, etc.})
            embedding: Vecteur d'embedding optionnel (1024 dims par défaut)
            source: Source du nœud (backward compatibility, deprecated)

        Returns:
            UUID du nœud créé (string)

        Raises:
            ValueError: Si node_type n'est pas dans NodeType enum
        """
        # Validation node_type
        valid_types = [t.value for t in NodeType]
        if node_type not in valid_types:
            raise ValueError(f"Invalid node_type '{node_type}'. Must be one of: {valid_types}")

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

    async def get_node_by_id(self, node_id: str) -> Optional[dict[str, Any]]:
        """
        Récupère un nœud par son ID.

        Args:
            node_id: UUID du nœud

        Returns:
            Dictionnaire {id, type, name, metadata, created_at} ou None si introuvable
        """
        row = await self.db_pool.fetchrow(
            """
            SELECT id, type, name, metadata, created_at, updated_at
            FROM knowledge.nodes
            WHERE id = $1
            """,
            node_id,
        )

        if not row:
            return None

        return {
            "id": str(row["id"]),
            "type": row["type"],
            "name": row["name"],
            "metadata": row["metadata"],
            "created_at": row["created_at"],
            "updated_at": row.get("updated_at"),
        }

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
        """
        rows = await self.db_pool.fetch(
            """
            SELECT id, type, name, metadata, created_at, updated_at
            FROM knowledge.nodes
            WHERE type = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            node_type,
            limit,
        )

        return [
            {
                "id": str(row["id"]),
                "type": row["type"],
                "name": row["name"],
                "metadata": row["metadata"],
                "created_at": row["created_at"],
                "updated_at": row.get("updated_at"),
            }
            for row in rows
        ]

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
        """
        rows = await self.db_pool.fetch(
            """
            SELECT id, from_node_id, to_node_id, relation_type, metadata, created_at
            FROM knowledge.edges
            WHERE relation_type = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            relation_type,
            limit,
        )

        return [
            {
                "id": str(row["id"]),
                "from_node_id": str(row["from_node_id"]),
                "to_node_id": str(row["to_node_id"]),
                "relation_type": row["relation_type"],
                "metadata": row["metadata"] or {},
                "created_at": row["created_at"],
            }
            for row in rows
        ]

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

        Raises:
            ValueError: Si relation_type n'est pas dans RelationType enum
        """
        # Validation relation_type
        valid_relations = [r.value for r in RelationType]
        if relation_type not in valid_relations:
            raise ValueError(
                f"Invalid relation_type '{relation_type}'. Must be one of: {valid_relations}"
            )

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
            Liste de résultats [{node_id, score, metadata}, ...] ou [] si erreur
        """
        try:
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

        except Exception as e:
            # Circuit breaker : retourner liste vide si pgvector indisponible
            logger.warning(f"semantic_search failed: {e}")
            return []

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
            limit: Nombre maximal de résultats

        Returns:
            Liste de nœuds [{id, type, name, metadata, relation_type}, ...]
        """
        if direction == "out":
            query = """
                SELECT n.id, n.type, n.name, n.metadata, e.relation_type
                FROM knowledge.edges e
                JOIN knowledge.nodes n ON e.to_node_id = n.id
                WHERE e.from_node_id = $1
            """
            params = [node_id]
        elif direction == "in":
            query = """
                SELECT n.id, n.type, n.name, n.metadata, e.relation_type
                FROM knowledge.edges e
                JOIN knowledge.nodes n ON e.from_node_id = n.id
                WHERE e.to_node_id = $1
            """
            params = [node_id]
        elif direction == "both":
            query = """
                SELECT n.id, n.type, n.name, n.metadata, e.relation_type
                FROM knowledge.edges e
                JOIN knowledge.nodes n ON (
                    (e.from_node_id = $1 AND n.id = e.to_node_id) OR
                    (e.to_node_id = $1 AND n.id = e.from_node_id)
                )
                WHERE e.from_node_id = $1 OR e.to_node_id = $1
            """
            params = [node_id]
        else:
            raise ValueError(f"Invalid direction '{direction}'. Must be 'out', 'in', or 'both'")

        if relation_type:
            query += " AND e.relation_type = $2 LIMIT $3"
            params.extend([relation_type, limit])
        else:
            query += " LIMIT $2"
            params.append(limit)

        rows = await self.db_pool.fetch(query, *params)
        return [
            {
                "id": str(row["id"]),
                "type": row["type"],
                "name": row["name"],
                "metadata": row["metadata"],
                "relation_type": row["relation_type"],
            }
            for row in rows
        ]

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
            limit: Nombre maximal de résultats

        Returns:
            Liste de nœuds [{id, type, name, metadata, created_at}, ...]
        """
        if node_type:
            query = """
                SELECT id, type, name, metadata, created_at
                FROM knowledge.nodes
                WHERE created_at >= $1 AND created_at <= $2 AND type = $3
                ORDER BY created_at DESC
                LIMIT $4
            """
            params = [start_date, end_date, node_type, limit]
        else:
            query = """
                SELECT id, type, name, metadata, created_at
                FROM knowledge.nodes
                WHERE created_at >= $1 AND created_at <= $2
                ORDER BY created_at DESC
                LIMIT $3
            """
            params = [start_date, end_date, limit]

        rows = await self.db_pool.fetch(query, *params)
        return [
            {
                "id": str(row["id"]),
                "type": row["type"],
                "name": row["name"],
                "metadata": row["metadata"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def get_node_with_relations(self, node_id: str, depth: int = 1) -> dict[str, Any]:
        """
        Récupère un nœud avec ses relations sur N niveaux de profondeur.

        Args:
            node_id: UUID du nœud racine
            depth: Profondeur de récursion (1 = relations directes uniquement)

        Returns:
            Dictionnaire {node, edges_out, edges_in}
        """
        # Récupérer le nœud racine
        node_row = await self.db_pool.fetchrow(
            "SELECT id, type, name, metadata, created_at FROM knowledge.nodes WHERE id = $1",
            node_id,
        )

        if not node_row:
            raise ValueError(f"Node {node_id} not found")

        node = {
            "id": str(node_row["id"]),
            "type": node_row["type"],
            "name": node_row["name"],
            "metadata": node_row["metadata"],
            "created_at": node_row["created_at"],
        }

        # Récupérer relations sortantes (depth = 1)
        edges_out = await self.get_related_nodes(node_id, direction="out")

        # Récupérer relations entrantes (depth = 1)
        edges_in = await self.get_related_nodes(node_id, direction="in")

        result = {"node": node, "edges_out": edges_out, "edges_in": edges_in}

        # Si depth > 1, récursion sur les nœuds liés
        if depth > 1:
            for rel in edges_out:
                rel["children"] = await self.get_node_with_relations(rel["id"], depth - 1)
            for rel in edges_in:
                rel["children"] = await self.get_node_with_relations(rel["id"], depth - 1)

        return result

    async def query_path(
        self, from_node_id: str, to_node_id: str, max_depth: int = 3
    ) -> list[dict[str, Any]]:
        """
        Trouve le chemin le plus court entre deux nœuds (BFS).

        Args:
            from_node_id: UUID du nœud source
            to_node_id: UUID du nœud cible
            max_depth: Profondeur maximale de recherche

        Returns:
            Liste d'edges formant le chemin [{relation_type, from_node_id, to_node_id}, ...]
        """
        # Cas simple : connexion directe
        direct_edge = await self.db_pool.fetchrow(
            """
            SELECT id, from_node_id, to_node_id, relation_type, metadata
            FROM knowledge.edges
            WHERE from_node_id = $1 AND to_node_id = $2
            LIMIT 1
            """,
            from_node_id,
            to_node_id,
        )

        if direct_edge:
            return [
                {
                    "id": str(direct_edge["id"]),
                    "from_node_id": str(direct_edge["from_node_id"]),
                    "to_node_id": str(direct_edge["to_node_id"]),
                    "relation_type": direct_edge["relation_type"],
                    "metadata": direct_edge["metadata"],
                }
            ]

        # Cas complexe : BFS pour trouver chemin multi-hop
        from collections import deque

        queue = deque([([from_node_id], [])])  # (nodes_path, edges_path)

        visited = {from_node_id}

        while queue:
            nodes_path, edges_path = queue.popleft()
            current_node = nodes_path[-1]

            if len(nodes_path) > max_depth + 1:
                continue

            # Explorer les voisins (relations sortantes)
            neighbors = await self.get_related_nodes(current_node, direction="out")

            for neighbor in neighbors:
                neighbor_id = neighbor["id"]

                if neighbor_id == to_node_id:
                    # Chemin trouvé !
                    final_edge = {
                        "from_node_id": current_node,
                        "to_node_id": neighbor_id,
                        "relation_type": neighbor["relation_type"],
                        "metadata": neighbor.get("metadata", {}),
                    }
                    return edges_path + [final_edge]

                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    new_edge = {
                        "from_node_id": current_node,
                        "to_node_id": neighbor_id,
                        "relation_type": neighbor["relation_type"],
                        "metadata": neighbor.get("metadata", {}),
                    }
                    queue.append((nodes_path + [neighbor_id], edges_path + [new_edge]))

        return []  # Aucun chemin trouvé


# ============================================================
# Factory Pattern
# ============================================================


async def get_memorystore_adapter(
    pool: Optional[asyncpg.Pool] = None,
    provider: Optional[str] = None,
) -> MemoryStore:
    """
    Factory pour créer adaptateur memorystore (graphe de connaissances).

    Args:
        pool: Pool asyncpg existant (si None, créé depuis DATABASE_URL)
        provider: Provider memorystore ("postgresql", "graphiti", "neo4j", "qdrant")
                  Si None, lit depuis env MEMORYSTORE_PROVIDER (default: "postgresql")

    Returns:
        Instance MemoryStore prête à l'usage (interface abstraite)

    Raises:
        ValueError: Si provider inconnu

    Example:
        adapter = await get_memorystore_adapter()  # PostgreSQL par défaut
        node_id = await adapter.create_node("person", "Antonio", {...})
    """
    provider = provider or os.getenv("MEMORYSTORE_PROVIDER", "postgresql")

    if provider == "postgresql":
        # PostgreSQL Day 1 (Decision D19)
        if pool is None:
            database_url = os.getenv("DATABASE_URL")
            if not database_url:
                raise ValueError("DATABASE_URL manquante")

            pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
            logger.info("memorystore_pool_created", provider="postgresql")

        adapter = PostgreSQLMemorystore(pool)
        await adapter.init_pgvector()

        logger.info(
            "memorystore_factory_created",
            provider="postgresql",
            backend="PostgreSQL + pgvector",
        )

        return adapter

    # Extensible: Ajouter d'autres providers
    elif provider == "graphiti":
        # Réévaluation août 2026 (Decision D3, Addendum §10)
        raise NotImplementedError(
            "Graphiti backend pas encore implémenté. "
            "Day 1 = PostgreSQL + pgvector. "
            "Réévaluation si maturité Graphiti atteinte (~août 2026)."
        )

    elif provider == "neo4j":
        # Swap futur si besoin requêtes graphe complexes
        raise NotImplementedError(
            "Neo4j backend pas encore implémenté. "
            "Day 1 = PostgreSQL. "
            "Swap vers Neo4j si besoin requêtes graphe complexes (Cypher, shortest path, etc.)."
        )

    elif provider == "qdrant":
        # Decision D19 : Qdrant si >300k vecteurs ou latence pgvector >100ms
        raise NotImplementedError(
            "Qdrant backend pas encore implémenté. "
            "Day 1 = pgvector dans PostgreSQL. "
            "Swap vers Qdrant si >300k vecteurs ou latence >100ms (réévaluation)."
        )

    else:
        raise ValueError(
            f"Unknown provider: {provider}. "
            "Supportés: postgresql, graphiti (futur), neo4j (futur), qdrant (futur)"
        )
