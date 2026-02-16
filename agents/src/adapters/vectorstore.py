#!/usr/bin/env python3
"""
Friday 2.0 - Vector Store Adapter avec anonymisation RGPD obligatoire

RÈGLE CRITIQUE (AC1 Story 6.2):
    TOUT texte envoyé à Voyage AI DOIT passer par anonymisation Presidio.
    Aucune exception, aucun bypass.

Architecture:
    - VectorStoreAdapter : Interface abstraite pour providers embeddings
    - VoyageAIAdapter : Implémentation Voyage AI voyage-4-large (1024 dims)
    - PgvectorStore : Stockage vectoriel PostgreSQL + pgvector
    - get_vectorstore_adapter() : Factory pattern pour swap providers

Usage:
    from agents.src.adapters.vectorstore import get_vectorstore_adapter

    vectorstore = await get_vectorstore_adapter()

    # Générer embeddings (anonymisation automatique)
    embeddings = await vectorstore.embed(["Texte à embedder"])

    # Stocker
    await vectorstore.store(node_id="email_123", embedding=embeddings[0])

    # Rechercher
    results = await vectorstore.search(
        query_embedding=query_emb,
        top_k=10,
        filters={"node_type": "document"}
    )

Date: 2026-02-11
Version: 1.0.0 (Story 6.2)
"""

import os
from abc import ABC, abstractmethod
from typing import Any, Optional

import asyncpg
import structlog
from agents.src.tools.anonymize import (
    AnonymizationError,
    anonymize_text,
)
from pydantic import BaseModel, Field

from config.exceptions import PipelineError

logger = structlog.get_logger(__name__)


# ============================================================
# Constants (Fix Issue #9: Magic numbers → constantes)
# ============================================================

# Voyage AI constants
VOYAGE_MODEL_DEFAULT = "voyage-4-large"
VOYAGE_DIMENSIONS_DEFAULT = 1024
VOYAGE_BATCH_MAX_TEXTS = 50  # Limite batch API Voyage
VOYAGE_RATE_LIMIT_RPM = 300  # Requests per minute

# PostgreSQL pgvector constants
PGVECTOR_SEARCH_TOP_K_MAX = 100  # Limite recherche pour performance
PGVECTOR_SEARCH_TOP_K_DEFAULT = 10

# Chunking constants (pour documents longs)
CHUNK_SIZE_CHARS = 2000  # Taille chunk pour documents >10k
CHUNK_OVERLAP_CHARS = 200  # Overlap entre chunks

# API cost tracking constants (AC6)
VOYAGE_COST_PER_TOKEN_EUR = 0.000055  # ~0.06 USD/1M tokens batch, converti EUR (rate 1.1)
VOYAGE_COST_PER_TOKEN_CENTS = VOYAGE_COST_PER_TOKEN_EUR * 100  # En centimes EUR


# ============================================================
# Pydantic Models
# ============================================================


class EmbeddingRequest(BaseModel):
    """Requête génération embeddings"""

    texts: list[str] = Field(
        ..., description=f"Textes à embedder (max {VOYAGE_BATCH_MAX_TEXTS} batch Voyage)"
    )
    model: str = Field(default=VOYAGE_MODEL_DEFAULT, description="Modèle embeddings")
    anonymize: bool = Field(default=True, description="Appliquer anonymisation Presidio")


class EmbeddingResponse(BaseModel):
    """Réponse génération embeddings"""

    embeddings: list[list[float]] = Field(..., description="Vecteurs embeddings")
    dimensions: int = Field(
        ..., description=f"Nombre dimensions ({VOYAGE_DIMENSIONS_DEFAULT} pour voyage-4-large)"
    )
    tokens_used: int = Field(..., description="Tokens consommés")
    anonymization_applied: bool = Field(False, description="True si anonymisation appliquée")


class SearchResult(BaseModel):
    """Résultat recherche sémantique"""

    node_id: str = Field(..., description="ID du nœud dans knowledge.nodes")
    similarity: float = Field(..., ge=0.0, le=1.0, description="Score similarité cosine (0-1)")
    node_type: Optional[str] = Field(None, description="Type de nœud (email, document, etc.)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Métadonnées additionnelles")


class VectorStoreError(PipelineError):
    """Erreur vectorstore"""



class EmbeddingProviderError(VectorStoreError):
    """Erreur provider embeddings (Voyage AI, OpenAI, etc.)"""



# ============================================================
# Interface Abstraite
# ============================================================

class VectorStoreAdapter(ABC):
    """
    Interface abstraite pour providers embeddings.

    Permet de swap Voyage AI → OpenAI/Cohere/Ollama local en changeant 1 fichier.
    """

    @abstractmethod
    async def embed(self, texts: list[str], anonymize: bool = True) -> EmbeddingResponse:
        """
        Générer embeddings pour liste de textes.

        Args:
            texts: Textes à embedder (max 50 pour batch Voyage)
            anonymize: Si True, applique Presidio AVANT envoi au provider

        Returns:
            EmbeddingResponse avec vecteurs + métadonnées

        Raises:
            EmbeddingProviderError: Si provider API down ou erreur
            AnonymizationError: Si Presidio down et anonymize=True
        """

    @abstractmethod
    async def store(
        self, node_id: str, embedding: list[float], metadata: Optional[dict] = None
    ) -> None:
        """
        Stocker embedding dans vectorstore.

        Args:
            node_id: ID du nœud dans knowledge.nodes
            embedding: Vecteur embedding (1024 floats pour Voyage)
            metadata: Métadonnées optionnelles (JSON)

        Raises:
            VectorStoreError: Si échec stockage
        """

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: Optional[dict] = None,
    ) -> list[SearchResult]:
        """
        Rechercher vecteurs similaires.

        Args:
            query_embedding: Vecteur query (1024 floats)
            top_k: Nombre de résultats (max 100)
            filters: Filtres WHERE SQL (node_type, date_range, etc.)

        Returns:
            Liste de SearchResult triés par similarité DESC

        Raises:
            VectorStoreError: Si échec recherche
        """

    @abstractmethod
    async def delete(self, node_id: str) -> None:
        """
        Supprimer embedding(s) d'un nœud.

        Args:
            node_id: ID du nœud dans knowledge.nodes

        Note:
            Normalement géré par CASCADE DELETE (FK constraint)
        """

    @abstractmethod
    async def close(self) -> None:
        """Fermer connexions proprement"""


# ============================================================
# Voyage AI Adapter
# ============================================================


class VoyageAIAdapter:
    """
    Adapter pour Voyage AI voyage-4-large (1024 dims, multilingual).

    Features:
        - Batch API (-33% cost vs endpoint standard)
        - Multilingual (français supporté)
        - Rate limits: 300 RPM
        - Context: 32k tokens
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = VOYAGE_MODEL_DEFAULT,
        dimensions: int = VOYAGE_DIMENSIONS_DEFAULT,
    ):
        """
        Initialise Voyage AI adapter.

        Args:
            api_key: Clé API Voyage (défaut: env VOYAGE_API_KEY)
            model: Modèle embeddings (voyage-4-large, voyage-3.5, etc.)
            dimensions: Nombre dimensions (1024 default)

        Raises:
            ValueError: Si api_key manquante
        """
        self.api_key = api_key or os.getenv("VOYAGE_API_KEY")
        if not self.api_key:
            raise ValueError("VOYAGE_API_KEY manquante (env var ou paramètre constructor)")

        self.model = model
        self.dimensions = dimensions

        # Import voyageai client (lazy import pour tests mocks)
        try:
            import httpx
            import voyageai

            # Configure timeout 30s (specs Story 6.2 Subtask 1.3)
            timeout = httpx.Timeout(30.0, connect=5.0)
            self.client = voyageai.Client(api_key=self.api_key, timeout=timeout)
        except ImportError as e:
            if "voyageai" in str(e):
                raise ImportError("voyageai package manquant. Installer avec: pip install voyageai")
            elif "httpx" in str(e):
                raise ImportError("httpx package manquant. Installer avec: pip install httpx")
            raise

        logger.info(
            "voyage_adapter_initialized",
            model=model,
            dimensions=dimensions,
        )

    async def embed(self, texts: list[str], anonymize: bool = True) -> EmbeddingResponse:
        """
        Générer embeddings via Voyage AI.

        Args:
            texts: Textes à embedder (max 50 batch)
            anonymize: Si True, applique Presidio AVANT Voyage

        Returns:
            EmbeddingResponse avec vecteurs

        Raises:
            EmbeddingProviderError: Si Voyage API erreur
            AnonymizationError: Si Presidio down
        """
        if not texts:
            raise ValueError("texts ne peut pas être vide")

        if len(texts) > VOYAGE_BATCH_MAX_TEXTS:
            raise ValueError(
                f"Batch max {VOYAGE_BATCH_MAX_TEXTS} textes (Voyage limit), reçu {len(texts)}. "
                "Splittez en plusieurs batches."
            )

        # Anonymisation RGPD obligatoire
        processed_texts = texts
        anonymization_applied = False

        if anonymize:
            try:
                # Anonymiser tous les textes et stocker les résultats complets
                anon_results = []
                for text in texts:
                    result = await anonymize_text(text)
                    anon_results.append(result)

                processed_texts = [r.anonymized_text for r in anon_results]
                anonymization_applied = True

                # Fix Issue #6: Pas de double anonymisation - réutiliser résultats existants
                pii_detected = any(len(r.entities) > 0 for r in anon_results)

                logger.info(
                    "voyage_texts_anonymized",
                    count=len(texts),
                    pii_detected=pii_detected,
                    pii_entities_total=sum(len(r.entities) for r in anon_results),
                )

            except AnonymizationError as e:
                logger.error(
                    "voyage_anonymization_failed",
                    error=str(e),
                )
                raise

        # Appel Voyage API (batch endpoint)
        try:
            response = self.client.embed(
                texts=processed_texts,
                model=self.model,
                input_type="document",  # "document" pour stockage, "query" pour recherche
            )

            embeddings = response.embeddings
            tokens_used = getattr(
                response, "total_tokens", len(processed_texts) * 100
            )  # Estimation

            logger.info(
                "voyage_embeddings_generated",
                count=len(embeddings),
                tokens=tokens_used,
                model=self.model,
            )

            # AC6: Track API usage pour budget monitoring
            await self._track_api_usage(
                tokens_input=tokens_used,
                operation="embed",
                metadata={
                    "model": self.model,
                    "batch_size": len(texts),
                    "anonymized": anonymization_applied,
                },
            )

            return EmbeddingResponse(
                embeddings=embeddings,
                dimensions=self.dimensions,
                tokens_used=tokens_used,
                anonymization_applied=anonymization_applied,
            )

        except Exception as e:
            logger.error(
                "voyage_api_error",
                error=str(e),
                model=self.model,
            )
            raise EmbeddingProviderError(f"Voyage API error: {e}") from e

    async def embed_query(self, query: str, anonymize: bool = True) -> list[float]:
        """
        Générer embedding pour requête utilisateur.

        Utilise input_type="query" (optimisé pour recherche).

        Args:
            query: Texte requête
            anonymize: Anonymiser query

        Returns:
            Vecteur embedding (1024 floats)
        """
        if anonymize:
            anonymized = await anonymize_text(query)
            query_text = anonymized.anonymized_text
        else:
            query_text = query

        try:
            response = self.client.embed(texts=[query_text], model=self.model, input_type="query")

            tokens_used = getattr(response, "total_tokens", 100)  # Estimation

            # AC6: Track API usage
            await self._track_api_usage(
                tokens_input=tokens_used,
                operation="embed_query",
                metadata={"model": self.model, "anonymized": anonymize},
            )

            return response.embeddings[0]

        except Exception as e:
            logger.error("voyage_query_embed_error", error=str(e))
            raise EmbeddingProviderError(f"Voyage query embed error: {e}") from e

    async def _track_api_usage(
        self,
        tokens_input: int,
        operation: str,
        metadata: dict[str, Any],
    ) -> None:
        """
        Track API usage pour budget monitoring (AC6).

        Args:
            tokens_input: Nombre de tokens consommés
            operation: Type d'opération ('embed', 'embed_query')
            metadata: Métadonnées additionnelles (model, batch_size, etc.)
        """
        try:
            # Calculer coût en centimes EUR
            cost_cents = round(tokens_input * VOYAGE_COST_PER_TOKEN_CENTS, 4)

            # Connexion PostgreSQL (utiliser pool existant ou créer si nécessaire)
            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                logger.warning("DATABASE_URL manquante, skip API tracking")
                return

            conn = await asyncpg.connect(db_url)

            try:
                # Appeler fonction SQL core.log_api_usage()
                await conn.execute(
                    "SELECT core.log_api_usage($1, $2, $3, $4, $5, $6, $7, $8)",
                    "voyage-ai",  # service
                    operation,  # operation
                    tokens_input,  # tokens_input
                    0,  # tokens_output (N/A pour embeddings)
                    cost_cents,  # cost_input_cents
                    0,  # cost_output_cents
                    metadata.get("module"),  # module (optionnel)
                    metadata,  # metadata JSON
                )

                logger.debug(
                    "api_usage_tracked",
                    service="voyage-ai",
                    operation=operation,
                    tokens=tokens_input,
                    cost_cents=cost_cents,
                )

            finally:
                await conn.close()

        except Exception as e:
            # Ne pas bloquer le flow si tracking échoue
            logger.error(
                "api_usage_tracking_failed",
                error=str(e),
                operation=operation,
            )


# ============================================================
# Pgvector Store
# ============================================================


class PgvectorStore:
    """
    Stockage vectoriel PostgreSQL + pgvector extension.

    Features:
        - Index HNSW (m=16, ef_construction=64)
        - Cosine similarity (<=> operator)
        - Filtres SQL (node_type, date_range, etc.)
        - CASCADE delete (FK constraint)
    """

    def __init__(self, pool: Optional[asyncpg.Pool] = None):
        """
        Initialise pgvector store.

        Args:
            pool: Pool asyncpg existant (si None, créé depuis DATABASE_URL)
        """
        self.pool = pool
        self._owns_pool = pool is None  # Si on crée le pool, on doit le fermer

    async def _ensure_pool(self) -> asyncpg.Pool:
        """Assure que pool existe (lazy initialization)"""
        if self.pool is None:
            database_url = os.getenv("DATABASE_URL")
            if not database_url:
                raise ValueError("DATABASE_URL manquante")

            self.pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)

            logger.info("pgvector_pool_created")

        return self.pool

    async def store(
        self, node_id: str, embedding: list[float], metadata: Optional[dict] = None
    ) -> None:
        """
        Stocker embedding dans knowledge.embeddings.

        Args:
            node_id: ID nœud (FK vers knowledge.nodes)
            embedding: Vecteur 1024 floats
            metadata: JSON optionnel
        """
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO knowledge.embeddings (node_id, embedding, metadata, created_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (node_id) DO UPDATE
                    SET embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    """,
                    node_id,
                    embedding,  # pgvector auto-cast list[float] → vector
                    metadata or {},
                )

                logger.info(
                    "pgvector_embedding_stored",
                    node_id=node_id,
                    dimensions=len(embedding),
                )

            except Exception as e:
                logger.error(
                    "pgvector_store_error",
                    node_id=node_id,
                    error=str(e),
                )
                raise VectorStoreError(f"Échec stockage embedding: {e}") from e

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = PGVECTOR_SEARCH_TOP_K_DEFAULT,
        filters: Optional[dict] = None,
    ) -> list[SearchResult]:
        """
        Rechercher vecteurs similaires via HNSW index.

        Args:
            query_embedding: Vecteur query ({VOYAGE_DIMENSIONS_DEFAULT} floats)
            top_k: Nombre résultats (max {PGVECTOR_SEARCH_TOP_K_MAX})
            filters: Filtres {"node_type": "document", "date_range": {...}}

        Returns:
            Liste SearchResult triés par similarity DESC
        """
        if top_k > PGVECTOR_SEARCH_TOP_K_MAX:
            raise ValueError(f"top_k max {PGVECTOR_SEARCH_TOP_K_MAX} (limiter coût compute)")

        pool = await self._ensure_pool()

        # Construire WHERE clause depuis filtres
        where_clauses = []
        params = [query_embedding, top_k]

        if filters:
            if "node_type" in filters:
                where_clauses.append(f"n.node_type = ${len(params) + 1}")
                params.append(filters["node_type"])

            if "date_range" in filters:
                date_range = filters["date_range"]
                if "start" in date_range:
                    where_clauses.append(f"e.created_at >= ${len(params) + 1}")
                    params.append(date_range["start"])
                if "end" in date_range:
                    where_clauses.append(f"e.created_at <= ${len(params) + 1}")
                    params.append(date_range["end"])

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        query = f"""
            SELECT
                e.node_id,
                1 - (e.embedding <=> $1) AS similarity,
                n.node_type,
                e.metadata
            FROM knowledge.embeddings e
            JOIN knowledge.nodes n ON e.node_id = n.id
            {where_sql}
            ORDER BY e.embedding <=> $1
            LIMIT $2
        """

        async with pool.acquire() as conn:
            try:
                rows = await conn.fetch(query, *params)

                results = [
                    SearchResult(
                        node_id=row["node_id"],
                        similarity=float(row["similarity"]),
                        node_type=row["node_type"],
                        metadata=row["metadata"] or {},
                    )
                    for row in rows
                ]

                logger.info(
                    "pgvector_search_completed",
                    top_k=top_k,
                    results_count=len(results),
                    filters=filters,
                )

                return results

            except Exception as e:
                logger.error(
                    "pgvector_search_error",
                    error=str(e),
                )
                raise VectorStoreError(f"Échec recherche: {e}") from e

    async def delete(self, node_id: str) -> None:
        """
        Supprimer embedding(s) d'un nœud.

        Note: Normalement CASCADE DELETE via FK, mais utile pour purge manuelle.
        """
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM knowledge.embeddings WHERE node_id = $1",
                node_id,
            )

            logger.info("pgvector_embedding_deleted", node_id=node_id)

    async def close(self) -> None:
        """Fermer pool si on l'a créé"""
        if self._owns_pool and self.pool:
            await self.pool.close()
            logger.info("pgvector_pool_closed")


# ============================================================
# Combined Adapter
# ============================================================


class CombinedVectorStoreAdapter(VectorStoreAdapter):
    """
    Adapter combiné Voyage AI (embeddings) + Pgvector (stockage).

    Implémente l'interface complète VectorStoreAdapter.
    """

    def __init__(
        self,
        voyage_adapter: VoyageAIAdapter,
        pgvector_store: PgvectorStore,
    ):
        self.voyage = voyage_adapter
        self.pgvector = pgvector_store

    async def embed(self, texts: list[str], anonymize: bool = True) -> EmbeddingResponse:
        """Délègue à VoyageAIAdapter"""
        return await self.voyage.embed(texts, anonymize=anonymize)

    async def store(
        self, node_id: str, embedding: list[float], metadata: Optional[dict] = None
    ) -> None:
        """Délègue à PgvectorStore"""
        await self.pgvector.store(node_id, embedding, metadata)

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: Optional[dict] = None,
    ) -> list[SearchResult]:
        """Délègue à PgvectorStore"""
        return await self.pgvector.search(query_embedding, top_k, filters)

    async def delete(self, node_id: str) -> None:
        """Délègue à PgvectorStore"""
        await self.pgvector.delete(node_id)

    async def close(self) -> None:
        """Ferme toutes les connexions"""
        await self.pgvector.close()


# ============================================================
# Factory Pattern
# ============================================================


async def get_vectorstore_adapter(
    provider: Optional[str] = None,
    pool: Optional[asyncpg.Pool] = None,
) -> VectorStoreAdapter:
    """
    Factory pour créer adaptateur vectorstore.

    Args:
        provider: Provider embeddings ("voyage", "openai", "cohere", "ollama")
                  Si None, lit depuis env EMBEDDING_PROVIDER
        pool: Pool asyncpg existant (optionnel)

    Returns:
        Instance VectorStoreAdapter prête à l'usage

    Raises:
        ValueError: Si provider inconnu

    Example:
        vectorstore = await get_vectorstore_adapter()
        embeddings = await vectorstore.embed(["Texte test"])
    """
    provider = provider or os.getenv("EMBEDDING_PROVIDER", "voyage")

    if provider == "voyage":
        voyage_adapter = VoyageAIAdapter()
        pgvector_store = PgvectorStore(pool=pool)

        logger.info(
            "vectorstore_factory_created",
            provider="voyage",
            model="voyage-4-large",
        )

        return CombinedVectorStoreAdapter(
            voyage_adapter=voyage_adapter,
            pgvector_store=pgvector_store,
        )

    # Extensible: Ajouter d'autres providers
    elif provider == "openai":
        raise NotImplementedError("OpenAI embeddings adapter pas encore implémenté")

    elif provider == "cohere":
        raise NotImplementedError("Cohere embeddings adapter pas encore implémenté")

    elif provider == "ollama":
        raise NotImplementedError("Ollama embeddings adapter pas encore implémenté")

    else:
        raise ValueError(
            f"Provider embeddings inconnu: {provider}. " "Supportés: voyage, openai, cohere, ollama"
        )
