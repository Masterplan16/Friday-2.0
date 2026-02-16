#!/usr/bin/env python3
"""
Friday 2.0 - Archiviste Semantic Search (Story 3.3 - Task 4)

Recherche sémantique via pgvector HNSW + Voyage AI embeddings.

Architecture:
    - SemanticSearcher: Classe principale recherche sémantique
    - search(): Query anonymisé → embedding → pgvector cosinus distance → top-k results
    - Filtres avancés: category, date_range, confidence_min, file_type

Usage:
    from agents.src.agents.archiviste.semantic_search import SemanticSearcher

    searcher = SemanticSearcher(db_pool=db_pool)
    results = await searcher.search(
        query="facture plombier 2026",
        top_k=5,
        filters={"category": "finance"}
    )

Date: 2026-02-16
Story: 3.3 - Task 4
"""

import time
from typing import Optional

import asyncpg
import structlog
from agents.src.adapters.embedding import get_embedding_adapter
from agents.src.agents.archiviste.models import SearchResult
from agents.src.middleware.models import ActionResult
from agents.src.middleware.trust import friday_action
from agents.src.tools.anonymize import AnonymizationResult, anonymize_text
from agents.src.tools.search_metrics import search_metrics

logger = structlog.get_logger(__name__)

# ============================================================
# Constants
# ============================================================

MODEL_NAME = "voyage-4-large"
EMBEDDING_DIMENSIONS = 1024
TOP_K_DEFAULT = 5
TOP_K_MAX = 100
EXCERPT_LENGTH = 200


# ============================================================
# Semantic Searcher Class
# ============================================================


class SemanticSearcher:
    """
    Recherche sémantique documents via pgvector (Story 3.3 - Task 4).

    Utilise cosinus distance (<=> operator) pour similarité.
    """

    def __init__(self, db_pool: asyncpg.Pool):
        """
        Initialise SemanticSearcher.

        Args:
            db_pool: Pool asyncpg pour PostgreSQL + pgvector
        """
        self.db_pool = db_pool
        logger.info("SemanticSearcher initialized", model=MODEL_NAME)

    async def search(
        self,
        query: str,
        top_k: int = TOP_K_DEFAULT,
        filters: Optional[dict] = None,
    ) -> list[SearchResult]:
        """
        Recherche sémantique documents (AC1, AC4).

        Pipeline:
        1. Anonymiser query (Presidio RGPD)
        2. Générer embedding query via Voyage AI
        3. Query pgvector avec cosinus distance (<=>)
        4. Jointure ingestion.document_metadata
        5. Extraction extrait pertinent (200 chars)
        6. Retourner top-k SearchResults

        Args:
            query: Texte requête utilisateur (natural language)
            top_k: Nombre résultats max (default 5, max 100)
            filters: Filtres optionnels (category, date_range, confidence_min, file_type)

        Returns:
            Liste SearchResult triés par score descendant

        Raises:
            ValueError: Si query vide ou top_k invalide
        """
        # Validation query
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        # Validation top_k
        if top_k < 1 or top_k > TOP_K_MAX:
            raise ValueError(f"top_k must be between 1 and {TOP_K_MAX}")

        # Métriques timing
        start_time = time.time()

        # 1. Anonymiser query (Task 4.4)
        logger.debug("Anonymizing query", query_length=len(query))
        anonymization_result: AnonymizationResult = await anonymize_text(query)
        anonymized_query = anonymization_result.anonymized_text

        # 2. Générer embedding query (Task 4.5)
        logger.debug("Generating query embedding")
        adapter = get_embedding_adapter()
        embedding_response = await adapter.embed(
            texts=[anonymized_query],
            anonymize=False,  # Déjà anonymisé
        )
        query_embedding = embedding_response["embeddings"][0]

        # 3. Query pgvector avec filtres (Task 4.6, 4.7)
        results = await self._query_pgvector(
            query_embedding=query_embedding,
            top_k=top_k,
            filters=filters or {},
        )

        # 4. Calculer et enregistrer métriques (Task 8)
        duration_ms = (time.time() - start_time) * 1000
        top_score = results[0].score if results else 0.0

        search_metrics.record_query(
            query_duration_ms=duration_ms,
            results_count=len(results),
            top_score=top_score,
        )

        logger.info(
            "Semantic search completed",
            query_length=len(query),
            results_count=len(results),
            duration_ms=round(duration_ms, 2),
            top_score=round(top_score, 3),
        )

        return results

    async def _query_pgvector(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict,
    ) -> list[SearchResult]:
        """
        Query pgvector avec cosinus distance (Task 4.6, 4.7).

        Jointure avec ingestion.document_metadata pour récupérer metadata.

        Args:
            query_embedding: Vecteur query (1024 dims)
            top_k: Nombre résultats
            filters: Filtres (category, date_range, confidence_min, file_type)

        Returns:
            Liste SearchResult
        """
        # Construire WHERE clauses depuis filters (Task 7)
        where_clauses = []
        params = [query_embedding, top_k]
        param_idx = 3  # $1 = embedding, $2 = limit

        # Filter: category
        if "category" in filters:
            where_clauses.append(f"dm.classification_category = ${param_idx}")
            params.append(filters["category"])
            param_idx += 1

        # Filter: date_range (after, before)
        if "after" in filters:
            where_clauses.append(f"dm.created_at >= ${param_idx}")
            params.append(filters["after"])
            param_idx += 1

        if "before" in filters:
            where_clauses.append(f"dm.created_at <= ${param_idx}")
            params.append(filters["before"])
            param_idx += 1

        # Filter: confidence_min
        if "confidence_min" in filters:
            where_clauses.append(f"e.confidence >= ${param_idx}")
            params.append(filters["confidence_min"])
            param_idx += 1

        # Filter: file_type (extension)
        if "file_type" in filters:
            where_clauses.append(f"dm.original_filename ILIKE ${param_idx}")
            params.append(f"%.{filters['file_type']}")
            param_idx += 1

        # Construire WHERE clause
        where_sql = " AND " + " AND ".join(where_clauses) if where_clauses else ""

        # Activer hnsw.iterative_scan si filtres (pgvector 0.8.0, Task 7.3)
        if where_clauses:
            await self.db_pool.execute("SET LOCAL hnsw.iterative_scan = on")

        # Query pgvector avec jointure (Task 4.6, 4.7)
        # Cosinus distance (<=>): 0 = identique, 2 = opposés
        # Score = 1 - (distance / 2) pour normaliser [0, 1]
        query = f"""
            SELECT
                e.document_id,
                dm.original_filename AS title,
                dm.final_path AS path,
                1 - (e.embedding <=> $1) / 2 AS score,
                dm.ocr_text,
                dm.classification_category,
                dm.classification_subcategory,
                dm.classification_confidence,
                dm.metadata AS document_metadata
            FROM knowledge.embeddings e
            INNER JOIN ingestion.document_metadata dm
                ON e.document_id = dm.document_id
            WHERE e.document_id IS NOT NULL
            {where_sql}
            ORDER BY e.embedding <=> $1
            LIMIT $2
        """

        rows = await self.db_pool.fetch(query, *params)

        # 5. Construire SearchResults avec excerpts (Task 4.8)
        results = []
        for row in rows:
            excerpt = self._extract_excerpt(
                text=row["ocr_text"] or "",
                max_length=EXCERPT_LENGTH,
            )

            result = SearchResult(
                document_id=str(row["document_id"]),
                title=row["title"],
                path=row["path"],
                score=float(row["score"]),
                excerpt=excerpt,
                metadata={
                    "category": row["classification_category"],
                    "subcategory": row["classification_subcategory"],
                    "classification_confidence": float(row["classification_confidence"] or 0.0),
                    "document_metadata": row["document_metadata"],
                },
            )
            results.append(result)

        return results

    def _extract_excerpt(self, text: str, max_length: int = EXCERPT_LENGTH) -> str:
        """
        Extrait extrait pertinent du texte (Task 4.8).

        Pour l'instant : début du texte (200 chars).
        TODO: Améliorer avec match keywords query.

        Args:
            text: Texte OCR complet
            max_length: Longueur max excerpt (200)

        Returns:
            Extrait texte
        """
        if not text:
            return ""

        if len(text) > max_length:
            # Réserve 3 chars pour "..." afin de rester <= max_length
            excerpt = text[: max_length - 3].strip() + "..."
        else:
            excerpt = text[:max_length].strip()

        return excerpt

    @friday_action(module="archiviste", action="semantic_search", trust_default="auto")
    async def search_action(
        self,
        query: str,
        top_k: int = TOP_K_DEFAULT,
        filters: Optional[dict] = None,
        **kwargs,
    ) -> ActionResult:
        """
        Wrapper @friday_action pour recherche sémantique (Task 4.2).

        Retourne ActionResult standardisé pour Trust Layer.
        Le décorateur @friday_action gère : trust level, correction_rules injection,
        receipt creation, error handling, Telegram validation si propose.

        Args:
            query: Texte requête
            top_k: Nombre résultats
            filters: Filtres optionnels
            **kwargs: Injectés par @friday_action (_correction_rules, _rules_prompt)

        Returns:
            ActionResult avec results, confidence, reasoning
        """
        start_time = time.time()

        results = await self.search(
            query=query,
            top_k=top_k,
            filters=filters,
        )

        duration_ms = (time.time() - start_time) * 1000

        # Confidence = score moyen des résultats
        avg_score = sum(r.score for r in results) / len(results) if results else 0.0

        return ActionResult(
            input_summary=f"Query: '{query}' (top_{top_k})",
            output_summary=f"{len(results)} resultats trouves, score moyen {avg_score:.2f}",
            confidence=avg_score,
            reasoning=(
                f"Recherche semantique via {MODEL_NAME}. "
                f"Query anonymisee, embedding genere, pgvector cosinus distance. "
                f"{len(results)} documents trouves. "
                f"Duree {duration_ms:.0f}ms."
            ),
            payload={
                "results_count": len(results),
                "avg_score": round(avg_score, 3),
                "duration_ms": round(duration_ms, 2),
                "filters_applied": filters or {},
                "results": [
                    {
                        "document_id": r.document_id,
                        "title": r.title,
                        "score": round(r.score, 3),
                    }
                    for r in results[:5]  # Top-5 dans payload
                ],
            },
        )
