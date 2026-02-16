#!/usr/bin/env python3
"""
Friday 2.0 - Gateway Search Routes (Story 6.2 Task 4)

Endpoint recherche sémantique `/api/v1/search/semantic`.

Usage:
    POST /api/v1/search/semantic
    {
        "query": "facture plombier",
        "top_k": 10,
        "filters": {"node_type": "document"}
    }

Date: 2026-02-11
Story: 6.2 - Task 4
"""

from typing import Optional

import structlog
from agents.src.adapters.vectorstore import (
    EmbeddingProviderError,
    VectorStoreError,
    get_vectorstore_adapter,
)
from agents.src.tools.anonymize import AnonymizationError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


class SemanticSearchRequest(BaseModel):
    """Requête recherche sémantique"""

    query: str = Field(..., description="Texte requête utilisateur", min_length=1, max_length=1000)
    top_k: int = Field(default=10, description="Nombre résultats", ge=1, le=100)
    filters: Optional[dict] = Field(
        default=None, description="Filtres optionnels (node_type, date_range)"
    )


class SearchResultResponse(BaseModel):
    """Résultat recherche"""

    node_id: str
    node_type: Optional[str]
    similarity: float
    metadata: dict


class SemanticSearchResponse(BaseModel):
    """Réponse recherche sémantique"""

    query: str
    results: list[SearchResultResponse]
    count: int


@router.post("/semantic", response_model=SemanticSearchResponse)
async def semantic_search(request: SemanticSearchRequest):
    """
    Recherche sémantique dans knowledge graph via embeddings.

    1. Query → embedding Voyage AI (anonymisé)
    2. Recherche pgvector cosine similarity
    3. Retourne top_k résultats triés par similarité

    Example:
        POST /api/v1/search/semantic
        {
            "query": "SGLT2 inhibiteurs",
            "top_k": 5,
            "filters": {"node_type": "document"}
        }

    Returns:
        {
            "query": "SGLT2 inhibiteurs",
            "results": [
                {
                    "node_id": "doc_123",
                    "node_type": "document",
                    "similarity": 0.92,
                    "metadata": {"title": "SGLT2_guide.pdf"}
                },
                ...
            ],
            "count": 5
        }
    """
    try:
        # 1. Obtenir adaptateur vectorstore
        vectorstore = await get_vectorstore_adapter()

        # 2. Générer embedding query (anonymisation automatique)
        # Note: query courte, pas besoin de chunking
        embedding_response = await vectorstore.embed([request.query], anonymize=True)
        query_embedding = embedding_response.embeddings[0]

        # 3. Recherche dans pgvector
        results = await vectorstore.search(
            query_embedding=query_embedding,
            top_k=request.top_k,
            filters=request.filters,
        )

        # 4. Formater réponse
        formatted_results = [
            SearchResultResponse(
                node_id=r.node_id,
                node_type=r.node_type,
                similarity=r.similarity,
                metadata=r.metadata,
            )
            for r in results
        ]

        return SemanticSearchResponse(
            query=request.query,
            results=formatted_results,
            count=len(formatted_results),
        )

    except EmbeddingProviderError as e:
        logger.error("voyage_api_error", error=str(e), query=request.query)
        raise HTTPException(
            status_code=503,
            detail="Embedding service temporarily unavailable. Please try again later.",
        )

    except VectorStoreError as e:
        logger.error("vectorstore_error", error=str(e), query=request.query)
        raise HTTPException(
            status_code=503,
            detail="Search service temporarily unavailable. Please try again later.",
        )

    except AnonymizationError as e:
        logger.error("anonymization_error", error=str(e), query_length=len(request.query))
        raise HTTPException(
            status_code=500, detail="Query anonymization failed. Please try with a different query."
        )

    except ValidationError as e:
        logger.warning("validation_error", error=str(e), query=request.query[:50])
        raise HTTPException(status_code=400, detail="Invalid query format")

    except Exception as e:
        logger.error("search_unexpected_error", error=str(e), query=request.query[:50])
        raise HTTPException(status_code=500, detail="Search failed")
