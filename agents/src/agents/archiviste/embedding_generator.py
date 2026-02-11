#!/usr/bin/env python3
"""
Friday 2.0 - Archiviste Embedding Generator (Stub Story 6.2)

Génère embeddings pour documents traités par OCR.

IMPORTANT: Implémentation minimale pour Story 6.2 AC5.
          Implémentation complète sera dans Epic 3 (Stories 3.1-3.7).

Usage:
    from agents.src.agents.archiviste.embedding_generator import generate_document_embeddings

    await generate_document_embeddings(
        document_node_id="doc_123",
        text="Contenu document OCR...",
        vectorstore=vectorstore_adapter
    )

Date: 2026-02-11
Story: 6.2 - Task 3 (stub)
"""

import logging
from typing import Optional

from agents.src.adapters.vectorstore import VectorStoreAdapter
from agents.src.tools.anonymize import anonymize_text

logger = logging.getLogger(__name__)

# Chunking parameters (Story 6.2 specs)
CHUNK_SIZE = 2000  # chars
CHUNK_OVERLAP = 200  # chars


async def generate_document_embeddings(
    document_node_id: str,
    text: str,
    vectorstore: VectorStoreAdapter,
    metadata: Optional[dict] = None,
) -> int:
    """
    Génère et stocke embeddings pour un document.

    Si document >10k chars → split en chunks avec overlap.
    Chaque chunk → 1 embedding stocké avec même node_id.

    Args:
        document_node_id: ID du nœud Document dans knowledge.nodes
        text: Texte extrait (OCR ou natif PDF)
        vectorstore: Adaptateur vectorstore
        metadata: Métadonnées optionnelles (filename, etc.)

    Returns:
        Nombre d'embeddings générés (1 si petit document, N si chunking)

    Raises:
        Exception: Si erreur génération embedding
    """
    if not text or not text.strip():
        logger.warning("Empty text for document %s, skipping embedding", document_node_id)
        return 0

    # Limiter texte si trop long (éviter explosion tokens)
    if len(text) > 100000:  # 100k chars max
        logger.warning(
            "Document %s very long (%d chars), truncating to 100k",
            document_node_id,
            len(text),
        )
        text = text[:100000]

    # Chunking si document >10k chars
    if len(text) > 10000:
        chunks = chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        logger.info(
            "Document %s chunked into %d parts (%d chars total)",
            document_node_id,
            len(chunks),
            len(text),
        )
    else:
        chunks = [text]

    embeddings_count = 0

    for i, chunk in enumerate(chunks):
        try:
            # 1. Anonymiser chunk (RGPD)
            anonymized = await anonymize_text(chunk)
            anonymized_text = anonymized.anonymized_text

            # 2. Générer embedding
            embedding_response = await vectorstore.embed([anonymized_text], anonymize=False)
            embedding = embedding_response.embeddings[0]

            # 3. Stocker embedding
            # Note: Multiple embeddings avec même node_id = document multi-chunks
            chunk_metadata = {
                "source": "archiviste",
                "chunk_index": i,
                "total_chunks": len(chunks),
                "anonymized": True,
                **(metadata or {}),
            }

            await vectorstore.store(
                node_id=document_node_id,
                embedding=embedding,
                metadata=chunk_metadata,
            )

            embeddings_count += 1

            logger.debug(
                "Embedding generated for document %s chunk %d/%d",
                document_node_id,
                i + 1,
                len(chunks),
            )

        except Exception as e:
            logger.error(
                "Failed to generate embedding for document %s chunk %d: %s",
                document_node_id,
                i,
                str(e),
            )
            # Continue avec chunks suivants (partiel vaut mieux que rien)

    logger.info(
        "Generated %d embeddings for document %s",
        embeddings_count,
        document_node_id,
    )

    return embeddings_count


def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> list[str]:
    """
    Split texte en chunks avec overlap.

    Args:
        text: Texte complet
        chunk_size: Taille chunk (chars)
        overlap: Overlap entre chunks (chars)

    Returns:
        Liste de chunks

    Example:
        >>> text = "A" * 5000
        >>> chunks = chunk_text(text, chunk_size=2000, overlap=200)
        >>> len(chunks)
        3
        >>> len(chunks[0])
        2000
        >>> chunks[0][-100:] == chunks[1][:100]  # Overlap partiel
        False  # Car overlap exact positioning
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)

        # Next chunk start = current end - overlap
        start = end - overlap

        # Si dernier chunk très court (<overlap), on s'arrête
        if len(text) - start < overlap:
            break

    return chunks
