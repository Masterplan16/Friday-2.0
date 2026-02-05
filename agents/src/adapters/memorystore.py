"""
Adaptateur memorystore pour Friday 2.0 - Abstraction graphe de connaissances.

Day 1 : PostgreSQL (tables knowledge.*) + Qdrant (embeddings)
Futur possible (6+ mois) : Migration vers Graphiti (si mature) ou Neo4j

Ce module fournit une interface unifiée pour :
- Créer/récupérer des nœuds (entités : personnes, docs, topics)
- Créer des relations (edges) entre nœuds
- Recherche sémantique via embeddings Qdrant
- Requêtes sur le graphe PostgreSQL

Philosophie : Start simple (PostgreSQL relationnel + Qdrant vecteurs),
migrer uniquement si douleur réelle (requêtes graphe complexes, performances).
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

import asyncpg
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

logger = logging.getLogger(__name__)


class MemorystoreAdapter:
    """
    Adaptateur pour le graphe de connaissances Friday 2.0.

    Backend Day 1 : PostgreSQL (knowledge.* tables) + Qdrant (embeddings)
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        qdrant_client: AsyncQdrantClient,
        collection_name: str = "friday_knowledge",
    ):
        """
        Initialise l'adaptateur memorystore.

        Args:
            db_pool: Pool de connexions PostgreSQL
            qdrant_client: Client Qdrant (async)
            collection_name: Nom de la collection Qdrant (défaut: friday_knowledge)
        """
        self.db_pool = db_pool
        self.qdrant = qdrant_client
        self.collection_name = collection_name
        self._collection_initialized = False

    async def init_qdrant_collection(self, vector_size: int = 1024) -> None:
        """
        Initialise la collection Qdrant si elle n'existe pas.

        Args:
            vector_size: Dimension des vecteurs (1024 pour Mistral Embed)
        """
        try:
            collections = await self.qdrant.get_collections()
            collection_names = [c.name for c in collections.collections]

            if self.collection_name not in collection_names:
                await self.qdrant.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
                logger.info("Created Qdrant collection: %s", self.collection_name)
            else:
                logger.info("Qdrant collection already exists: %s", self.collection_name)

            self._collection_initialized = True

        except Exception as e:
            logger.error("Failed to initialize Qdrant collection: %s", e)
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
            name: Nom du nœud (ex: "Antonio Lopez", "Email RE: Projet X")
            metadata: Métadonnées JSON (ex: {email, company, date, etc.})
            embedding: Vecteur d'embedding optionnel (1024 dims pour Mistral Embed)

        Returns:
            UUID du nœud créé (string)
        """
        node_id = str(uuid.uuid4())
        now = datetime.utcnow()

        # 1. Créer nœud dans PostgreSQL knowledge.nodes
        query = """
            INSERT INTO knowledge.nodes (id, type, name, metadata, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """

        async with self.db_pool.acquire() as conn:
            created_id = await conn.fetchval(
                query, node_id, node_type, name, metadata, now, now
            )

        logger.info("Created node: %s (%s)", name, node_type)

        # 2. Si embedding fourni, stocker dans Qdrant
        if embedding:
            await self._store_embedding(node_id, embedding, metadata)

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
        # 1. Tenter de trouver nœud existant
        query = """
            SELECT id FROM knowledge.nodes
            WHERE type = $1 AND (
                (type = 'person' AND metadata->>'email' = $2) OR
                (type = 'document' AND metadata->>'source_id' = $3) OR
                (type = 'topic' AND LOWER(name) = LOWER($4))
            )
            LIMIT 1
        """

        email = metadata.get("email", "")
        source_id = metadata.get("source_id", "")

        async with self.db_pool.acquire() as conn:
            existing_id = await conn.fetchval(
                query, node_type, email, source_id, name
            )

        if existing_id:
            logger.debug("Node already exists: %s (%s)", name, existing_id)
            return str(existing_id)

        # 2. Nœud n'existe pas → créer
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

        query = """
            INSERT INTO knowledge.edges (id, from_node_id, to_node_id, relation_type, metadata, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """

        async with self.db_pool.acquire() as conn:
            created_id = await conn.fetchval(
                query, edge_id, from_node_id, to_node_id, relation_type, metadata, now
            )

        logger.info(
            "Created edge: %s -[%s]-> %s",
            from_node_id[:8],
            relation_type,
            to_node_id[:8],
        )

        return str(created_id)

    async def _store_embedding(
        self, node_id: str, embedding: list[float], metadata: dict[str, Any]
    ) -> None:
        """
        Stocke un embedding dans Qdrant.

        Args:
            node_id: UUID du nœud (utilisé comme point ID dans Qdrant)
            embedding: Vecteur d'embedding (1024 dims)
            metadata: Métadonnées à stocker avec le point (pour filtrage)
        """
        if not self._collection_initialized:
            await self.init_qdrant_collection()

        point = PointStruct(
            id=node_id, vector=embedding, payload=metadata
        )

        await self.qdrant.upsert(
            collection_name=self.collection_name, points=[point]
        )

        logger.debug("Stored embedding for node: %s", node_id)

    async def semantic_search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        score_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Recherche sémantique via embeddings Qdrant.

        Args:
            query_embedding: Vecteur de la requête (1024 dims)
            limit: Nombre maximal de résultats
            score_threshold: Seuil de similarité cosine (0.0-1.0)

        Returns:
            Liste de résultats [{node_id, score, metadata}, ...]
        """
        if not self._collection_initialized:
            await self.init_qdrant_collection()

        results = await self.qdrant.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=limit,
            score_threshold=score_threshold,
        )

        return [
            {
                "node_id": str(hit.id),
                "score": hit.score,
                "metadata": hit.payload,
            }
            for hit in results
        ]

    async def count_nodes(self, node_type: Optional[str] = None) -> int:
        """
        Compte le nombre de nœuds dans le graphe.

        Args:
            node_type: Type de nœud à compter (None = tous types)

        Returns:
            Nombre de nœuds
        """
        if node_type:
            query = "SELECT COUNT(*) FROM knowledge.nodes WHERE type = $1"
            async with self.db_pool.acquire() as conn:
                return await conn.fetchval(query, node_type)
        else:
            query = "SELECT COUNT(*) FROM knowledge.nodes"
            async with self.db_pool.acquire() as conn:
                return await conn.fetchval(query)

    async def count_edges(self, relation_type: Optional[str] = None) -> int:
        """
        Compte le nombre de relations dans le graphe.

        Args:
            relation_type: Type de relation à compter (None = tous types)

        Returns:
            Nombre d'edges
        """
        if relation_type:
            query = "SELECT COUNT(*) FROM knowledge.edges WHERE relation_type = $1"
            async with self.db_pool.acquire() as conn:
                return await conn.fetchval(query, relation_type)
        else:
            query = "SELECT COUNT(*) FROM knowledge.edges"
            async with self.db_pool.acquire() as conn:
                return await conn.fetchval(query)


# Factory function pour initialiser l'adaptateur
async def get_memorystore_adapter(
    db_pool: asyncpg.Pool,
    qdrant_url: str = "http://localhost:6333",
    collection_name: str = "friday_knowledge",
) -> MemorystoreAdapter:
    """
    Factory pour créer et initialiser un MemorystoreAdapter.

    Args:
        db_pool: Pool PostgreSQL
        qdrant_url: URL du serveur Qdrant
        collection_name: Nom de la collection Qdrant

    Returns:
        Instance MemorystoreAdapter initialisée
    """
    qdrant_client = AsyncQdrantClient(url=qdrant_url)
    adapter = MemorystoreAdapter(db_pool, qdrant_client, collection_name)
    await adapter.init_qdrant_collection()
    return adapter
