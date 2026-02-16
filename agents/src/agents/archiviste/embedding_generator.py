#!/usr/bin/env python3
"""
Friday 2.0 - Archiviste Embedding Generator (Story 3.3 - Task 1)

Génère embeddings pour documents via Voyage AI voyage-4-large.

RÈGLES CRITIQUES:
- Anonymisation Presidio OBLIGATOIRE avant appel Voyage AI (NFR6)
- Retry automatique avec backoff exponentiel (1s, 2s, 4s max 3 tentatives)
- Timeout 5s via asyncio.wait_for
- Budget tracking dans core.api_usage (migration 025)
- Fail-explicit : Exception si erreur critique
- @friday_action decorator pour Trust Layer (trust=auto)

Architecture:
    - EmbeddingGenerator: Classe principale génération embeddings
    - generate_embedding(): Méthode core (anonymize → embed → store)
    - generate_embedding_action(): Wrapper @friday_action pour ActionResult

Usage:
    from agents.src.agents.archiviste.embedding_generator import EmbeddingGenerator

    generator = EmbeddingGenerator(db_pool=db_pool)
    result = await generator.generate_embedding(
        document_id=uuid4(),
        text_content="Contenu document OCR..."
    )

Date: 2026-02-16
Story: 3.3 - Task 1
"""

import asyncio
import time
from datetime import datetime
from typing import Optional
from uuid import UUID

import asyncpg
import structlog
from agents.src.adapters.embedding import get_embedding_adapter
from agents.src.agents.archiviste.models import EmbeddingResult
from agents.src.middleware.models import ActionResult
from agents.src.middleware.trust import friday_action
from agents.src.tools.anonymize import anonymize_text, AnonymizationResult

logger = structlog.get_logger(__name__)

# ============================================================
# Constants
# ============================================================

MODEL_NAME = "voyage-4-large"
EMBEDDING_DIMENSIONS = 1024
MAX_RETRIES = 3
BACKOFF_BASE = 1.0  # seconds
TIMEOUT_SECONDS = 5.0


# ============================================================
# Embedding Generator Class
# ============================================================


class EmbeddingGenerator:
    """
    Générateur d'embeddings pour documents (Story 3.3 - Task 1).

    Utilise Voyage AI voyage-4-large (1024 dimensions) avec anonymisation Presidio.
    """

    def __init__(self, db_pool: asyncpg.Pool):
        """
        Initialise EmbeddingGenerator.

        Args:
            db_pool: Pool asyncpg pour budget tracking (core.api_usage)
        """
        self.db_pool = db_pool
        logger.info("EmbeddingGenerator initialized", model=MODEL_NAME)

    async def generate_embedding(
        self,
        document_id: UUID,
        text_content: str,
        metadata: Optional[dict] = None,
        timeout: float = TIMEOUT_SECONDS,
    ) -> EmbeddingResult:
        """
        Génère embedding pour un document (AC2).

        Pipeline:
        1. Valider text_content non vide
        2. Anonymiser via Presidio (RGPD NFR6)
        3. Générer embedding via Voyage AI (retry automatique)
        4. Valider dimensions (1024)
        5. Valider normalization (L2 norm ≈ 1.0)
        6. Log budget tracking core.api_usage
        7. Retourner EmbeddingResult

        Args:
            document_id: UUID document dans ingestion.document_metadata
            text_content: Texte extrait (OCR ou natif)
            metadata: Métadonnées optionnelles (filename, category, etc.)
            timeout: Timeout génération embedding (default 5s)

        Returns:
            EmbeddingResult avec embedding_vector, model_name, confidence, metadata

        Raises:
            ValueError: Si text_content vide ou dimensions invalides
            asyncio.TimeoutError: Si génération > timeout
            Exception: Si échec après MAX_RETRIES tentatives (fail-explicit)
        """
        # Validation text_content
        if not text_content or not text_content.strip():
            raise ValueError("Text content cannot be empty")

        # Métriques timing
        start_time = time.time()

        # 1. Anonymisation Presidio (RGPD NFR6)
        logger.debug(
            "Anonymizing text before embedding",
            document_id=str(document_id),
            text_length=len(text_content),
        )

        anonymization_result: AnonymizationResult = await anonymize_text(text_content)
        anonymized_text = anonymization_result.anonymized_text
        anonymization_confidence = anonymization_result.confidence_min

        # 2. Générer embedding avec retry automatique
        embedding_response = await self._generate_with_retry(
            texts=[anonymized_text], timeout=timeout
        )

        embedding_vector = embedding_response["embeddings"][0]
        tokens_used = embedding_response["tokens_used"]
        dimensions = embedding_response["dimensions"]

        # 3. Valider dimensions (1024 pour voyage-4-large)
        if dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Expected {EMBEDDING_DIMENSIONS} dimensions, got {dimensions}"
            )

        # 4. Valider normalization (L2 norm ≈ 1.0)
        l2_norm = sum(x**2 for x in embedding_vector) ** 0.5
        if abs(l2_norm - 1.0) > 0.01:
            logger.warning(
                "Embedding vector not normalized",
                document_id=str(document_id),
                l2_norm=l2_norm,
            )

        # 5. Budget tracking core.api_usage (AC7)
        await self._log_api_usage(
            document_id=document_id,
            tokens_used=tokens_used,
            model=MODEL_NAME,
            provider="voyage-ai",
        )

        # 6. Calculer métriques
        duration_ms = (time.time() - start_time) * 1000

        # Confidence = moyenne anonymization + normalization quality
        normalization_quality = max(0.0, 1.0 - abs(l2_norm - 1.0) * 10)
        confidence = (anonymization_confidence + normalization_quality) / 2.0

        logger.info(
            "Embedding generated successfully",
            document_id=str(document_id),
            dimensions=dimensions,
            tokens_used=tokens_used,
            duration_ms=round(duration_ms, 2),
            confidence=round(confidence, 3),
        )

        # 7. Retourner EmbeddingResult
        return EmbeddingResult(
            document_id=str(document_id),
            embedding_vector=embedding_vector,
            model_name=MODEL_NAME,
            confidence=confidence,
            metadata={
                "tokens_used": tokens_used,
                "duration_ms": round(duration_ms, 2),
                "anonymization_confidence": round(anonymization_confidence, 3),
                "l2_norm": round(l2_norm, 4),
                **(metadata or {}),
            },
        )

    async def _generate_with_retry(
        self, texts: list[str], timeout: float
    ) -> dict:
        """
        Génère embeddings avec retry automatique (backoff exponentiel).

        Retry policy:
        - Tentative 1: Immédiat
        - Tentative 2: Après 1s (BACKOFF_BASE * 2^0)
        - Tentative 3: Après 2s (BACKOFF_BASE * 2^1)
        - Tentative 4: Après 4s (BACKOFF_BASE * 2^2)

        Args:
            texts: Textes à embedder (déjà anonymisés)
            timeout: Timeout total par tentative

        Returns:
            Dict response Voyage AI

        Raises:
            Exception: Si échec après MAX_RETRIES tentatives
        """
        adapter = get_embedding_adapter()
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                # Appel avec timeout
                response = await asyncio.wait_for(
                    adapter.embed(texts=texts, anonymize=False),  # Déjà anonymisé
                    timeout=timeout,
                )
                return response

            except asyncio.TimeoutError:
                last_exception = TimeoutError(
                    f"Embedding generation timeout after {timeout}s"
                )
                logger.warning(
                    "Embedding timeout, retrying",
                    attempt=attempt + 1,
                    max_retries=MAX_RETRIES,
                    timeout=timeout,
                )

            except Exception as e:
                last_exception = e
                logger.warning(
                    "Embedding generation failed, retrying",
                    attempt=attempt + 1,
                    max_retries=MAX_RETRIES,
                    error=str(e),
                )

            # Backoff exponentiel (sauf dernière tentative)
            if attempt < MAX_RETRIES - 1:
                backoff_time = BACKOFF_BASE * (2**attempt)
                logger.debug("Backoff before retry", backoff_seconds=backoff_time)
                await asyncio.sleep(backoff_time)

        # Fail-explicit après MAX_RETRIES tentatives
        error_msg = f"Failed to generate embedding after {MAX_RETRIES} retries"
        logger.error(error_msg, last_error=str(last_exception))
        raise Exception(error_msg) from last_exception

    async def _log_api_usage(
        self,
        document_id: UUID,
        tokens_used: int,
        model: str,
        provider: str,
    ) -> None:
        """
        Log API usage dans core.api_usage pour budget tracking (AC7).

        Args:
            document_id: UUID document
            tokens_used: Tokens consommés
            model: Nom modèle (voyage-4-large)
            provider: Provider (voyage-ai)
        """
        try:
            query = """
                INSERT INTO core.api_usage (
                    request_timestamp,
                    provider,
                    model,
                    tokens_input,
                    tokens_output,
                    cost_eur,
                    endpoint,
                    request_metadata
                ) VALUES (
                    NOW(),
                    $1,
                    $2,
                    $3,
                    0,  -- embeddings = input only
                    $4,
                    'embeddings',
                    $5
                )
            """

            # Coût Voyage AI: ~0.055 EUR / 1M tokens (batch)
            cost_per_token_eur = 0.000000055
            cost_eur = tokens_used * cost_per_token_eur

            metadata = {
                "document_id": str(document_id),
                "source": "archiviste",
                "action": "generate_embedding",
            }

            await self.db_pool.execute(
                query,
                provider,
                model,
                tokens_used,
                cost_eur,
                metadata,
            )

            logger.debug(
                "API usage logged",
                document_id=str(document_id),
                tokens=tokens_used,
                cost_eur=round(cost_eur, 6),
            )

        except Exception as e:
            # Non-blocking : budget tracking failure ne doit pas bloquer embedding
            logger.error(
                "Failed to log API usage",
                document_id=str(document_id),
                error=str(e),
            )

    @friday_action(module="archiviste", action="generate_embedding", trust_default="auto")
    async def generate_embedding_action(
        self,
        document_id: UUID,
        text_content: str,
        metadata: Optional[dict] = None,
        **kwargs,
    ) -> ActionResult:
        """
        Wrapper @friday_action pour génération embedding (AC7).

        Retourne ActionResult standardisé pour Trust Layer.
        Le décorateur @friday_action gère : trust level, correction_rules injection,
        receipt creation, error handling, Telegram validation si propose.

        Args:
            document_id: UUID document
            text_content: Texte à embedder
            metadata: Métadonnées optionnelles
            **kwargs: Injectés par @friday_action (_correction_rules, _rules_prompt)

        Returns:
            ActionResult avec input_summary, output_summary, confidence, reasoning
        """
        result = await self.generate_embedding(
            document_id=document_id,
            text_content=text_content,
            metadata=metadata,
        )

        return ActionResult(
            input_summary=f"Document {document_id} ({len(text_content)} chars)",
            output_summary=f"Embedding {EMBEDDING_DIMENSIONS} dims, confidence {result.confidence:.2f}",
            confidence=result.confidence,
            reasoning=(
                f"Generated embedding via {MODEL_NAME}. "
                f"Anonymization applied (confidence {result.metadata.get('anonymization_confidence', 0):.2f}). "
                f"Vector normalized (L2 norm {result.metadata.get('l2_norm', 0):.4f}). "
                f"Duration {result.metadata.get('duration_ms', 0):.0f}ms."
            ),
            payload={
                "document_id": str(document_id),
                "embedding_dimensions": EMBEDDING_DIMENSIONS,
                "model_name": MODEL_NAME,
                "tokens_used": result.metadata.get("tokens_used", 0),
                "metadata": result.metadata,
            },
        )


# ============================================================
# Utility Functions (for tests compatibility)
# ============================================================


def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> list[str]:
    """
    Split text into overlapping chunks.

    Args:
        text: Text to chunk
        chunk_size: Maximum size of each chunk (chars)
        overlap: Overlap between chunks (chars)

    Returns:
        List of text chunks
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)

        # Move start forward by (chunk_size - overlap)
        start += chunk_size - overlap

        # Stop if we've reached the end
        if end >= len(text):
            break

    return chunks


async def generate_document_embeddings(
    document_node_id: str,
    text: str,
    vectorstore,
    chunk_size: int = 2000,
    overlap: int = 200,
) -> int:
    """
    Generate embeddings for document with chunking support.

    Args:
        document_node_id: Document node ID
        text: Text content to embed
        vectorstore: Vectorstore adapter (mock in tests)
        chunk_size: Maximum chunk size
        overlap: Overlap between chunks

    Returns:
        Number of embeddings generated
    """
    # Chunk text
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)

    count = 0
    for i, chunk in enumerate(chunks):
        # Anonymize chunk
        anon_result = await anonymize_text(chunk)
        anonymized = anon_result.anonymized_text

        # Generate embedding
        response = await vectorstore.embed([anonymized])

        # Store embedding
        await vectorstore.store(
            node_id=f"{document_node_id}_chunk_{i}",
            embedding=response.embeddings[0],
            metadata={"chunk_index": i, "total_chunks": len(chunks)},
        )

        count += 1

    return count
