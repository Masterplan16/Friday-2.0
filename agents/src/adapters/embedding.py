#!/usr/bin/env python3
"""
Friday 2.0 - Embedding Adapter (Story 3.3 - Task 1.3)

Factory pattern pour swap providers embeddings (Voyage AI, OpenAI, etc.).
Day 1: Voyage AI voyage-4-large (1024 dimensions).

REGLE CRITIQUE (NFR6):
    Anonymisation Presidio OBLIGATOIRE avant appel API.

Usage:
    from agents.src.adapters.embedding import get_embedding_adapter

    adapter = get_embedding_adapter()
    response = await adapter.embed(
        texts=["Document content..."],
        anonymize=True  # Default True
    )

Date: 2026-02-16
Story: 3.3 - Task 1.3
"""

import os
from abc import ABC, abstractmethod
from typing import Optional

import structlog
from agents.src.adapters.vectorstore import (
    EmbeddingResponse,
    VoyageAIAdapter,
)
from agents.src.tools.anonymize import anonymize_text

logger = structlog.get_logger(__name__)


# ============================================================
# Abstract Base Class
# ============================================================


class EmbeddingAdapter(ABC):
    """
    Interface abstraite pour providers embeddings.

    Permet swap provider en changeant 1 variable d'environnement.
    """

    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        anonymize: bool = True,
        model: Optional[str] = None,
    ) -> dict:
        """
        Genere embeddings pour liste de textes.

        Args:
            texts: Liste de textes a embedder
            anonymize: Appliquer anonymisation Presidio (default True)
            model: Modele embeddings (override default)

        Returns:
            Dict avec keys:
                - embeddings: list[list[float]] (vecteurs)
                - dimensions: int (1024 pour voyage-4-large)
                - tokens_used: int
                - model: str (nom modele utilise)

        Raises:
            Exception: Si erreur generation embeddings
        """
        pass


# ============================================================
# Voyage AI Implementation
# ============================================================


class VoyageEmbeddingAdapter(EmbeddingAdapter):
    """
    Adaptateur Voyage AI pour embeddings.

    Delegue a VoyageAIAdapter de vectorstore.py (code existant Story 6.2).
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("VOYAGE_API_KEY")
        if not self.api_key:
            raise ValueError("VOYAGE_API_KEY environment variable not set")

        self.voyage_adapter = VoyageAIAdapter(api_key=self.api_key)
        logger.info("VoyageEmbeddingAdapter initialized", model="voyage-4-large")

    async def embed(
        self,
        texts: list[str],
        anonymize: bool = True,
        model: Optional[str] = None,
    ) -> dict:
        if not texts:
            raise ValueError("texts list cannot be empty")

        # Anonymiser textes si demande (RGPD NFR6)
        if anonymize:
            anonymized_texts = []
            for text in texts:
                result = await anonymize_text(text)
                anonymized_texts.append(result.anonymized_text)
            texts_to_embed = anonymized_texts
        else:
            texts_to_embed = texts

        # Appeler Voyage AI via adaptateur vectorstore existant
        response: EmbeddingResponse = await self.voyage_adapter.embed(
            texts_to_embed, anonymize=False
        )

        return {
            "embeddings": response.embeddings,
            "dimensions": response.dimensions,
            "tokens_used": response.tokens_used,
            "model": model or "voyage-4-large",
        }


# ============================================================
# OpenAI Implementation (Future)
# ============================================================


class OpenAIEmbeddingAdapter(EmbeddingAdapter):
    """Placeholder pour text-embedding-3-large (future)."""

    def __init__(self, api_key: Optional[str] = None):
        raise NotImplementedError("OpenAI adapter not implemented yet")

    async def embed(
        self,
        texts: list[str],
        anonymize: bool = True,
        model: Optional[str] = None,
    ) -> dict:
        raise NotImplementedError("OpenAI adapter not implemented yet")


# ============================================================
# Factory Function
# ============================================================

# Singleton pour eviter re-creation a chaque appel
_adapter_instance: Optional[EmbeddingAdapter] = None


def get_embedding_adapter(
    provider: Optional[str] = None,
) -> EmbeddingAdapter:
    """
    Factory function pour recuperer adaptateur embeddings (singleton).

    Permet swap provider via env var EMBEDDING_PROVIDER.

    Args:
        provider: Provider name (voyage-ai, openai, etc.)
                  Si None, utilise EMBEDDING_PROVIDER env var

    Returns:
        Instance de EmbeddingAdapter

    Raises:
        ValueError: Si provider inconnu
    """
    global _adapter_instance

    provider = provider or os.getenv("EMBEDDING_PROVIDER", "voyage-ai")

    # Retourner singleton si deja initialise
    if _adapter_instance is not None:
        return _adapter_instance

    if provider == "voyage-ai":
        _adapter_instance = VoyageEmbeddingAdapter()
    elif provider == "openai":
        _adapter_instance = OpenAIEmbeddingAdapter()
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")

    return _adapter_instance
