"""Friday 2.0 - Adapters Package

Adapters pour composants externes (LLM, Vectorstore, Memorystore, etc.).
Pattern adaptateur permet de swap providers en changeant 1 fichier.

Available adapters:
    - llm.ClaudeAdapter: Claude Sonnet 4.5 avec anonymisation RGPD
    - vectorstore.get_vectorstore_adapter: Voyage AI + pgvector (factory)
    - memorystore: PostgreSQL knowledge graph
"""

from agents.src.adapters.llm import ClaudeAdapter, LLMError, LLMResponse
from agents.src.adapters.memorystore import PostgreSQLMemorystore, get_memorystore_adapter
from agents.src.adapters.memorystore_interface import MemoryStore, NodeType, RelationType
from agents.src.adapters.vectorstore import (
    CombinedVectorStoreAdapter,
    EmbeddingProviderError,
    EmbeddingRequest,
    EmbeddingResponse,
    PgvectorStore,
    SearchResult,
    VectorStoreAdapter,
    VectorStoreError,
    VoyageAIAdapter,
    get_vectorstore_adapter,
)

__all__ = [
    # LLM Adapter
    "ClaudeAdapter",
    "LLMResponse",
    "LLMError",
    # Vectorstore Adapter
    "get_vectorstore_adapter",
    "VectorStoreAdapter",
    "VoyageAIAdapter",
    "PgvectorStore",
    "CombinedVectorStoreAdapter",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "SearchResult",
    "VectorStoreError",
    "EmbeddingProviderError",
    # Memorystore Adapter
    "get_memorystore_adapter",
    "MemoryStore",
    "PostgreSQLMemorystore",
    "NodeType",
    "RelationType",
]
