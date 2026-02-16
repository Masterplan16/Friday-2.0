#!/usr/bin/env python3
"""
Friday 2.0 - Archiviste Embedding Pipeline (Story 3.3 - Task 2)

Pipeline orchestration pour génération automatique embeddings.

Architecture:
    Redis Streams `document.classified` (Story 3.2) → Embedding Pipeline → `document.indexed`

Flow:
    1. Consume event document.classified
    2. Extract text_content depuis ingestion.document_metadata
    3. Anonymize via Presidio
    4. Generate embedding via EmbeddingGenerator
    5. Store dans knowledge.embeddings avec document_id FK
    6. Publish event document.indexed
    7. Retry automatique si erreur (backoff exponentiel)

Usage:
    python -m agents.src.agents.archiviste.embedding_pipeline

Date: 2026-02-16
Story: 3.3 - Task 2
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis
import structlog

from agents.src.agents.archiviste.embedding_generator import EmbeddingGenerator
from config.exceptions import PipelineError

logger = structlog.get_logger(__name__)

# ============================================================
# Constants
# ============================================================

REDIS_STREAM_INPUT = "document.classified"  # Input stream (Story 3.2)
REDIS_STREAM_OUTPUT = "document.indexed"  # Output stream
CONSUMER_GROUP = "embedding-pipeline"
CONSUMER_NAME = "embedding-worker-1"

MAX_RETRIES = 3
BACKOFF_BASE = 1.0  # seconds
TIMEOUT_SECONDS = 5.0  # Timeout génération embedding
ALERT_THRESHOLD_FAILURES = 5  # Alertes Telegram si >5 échecs consécutifs


# ============================================================
# Embedding Pipeline Class
# ============================================================


class EmbeddingPipeline:
    """
    Pipeline orchestration génération embeddings (Story 3.3 - Task 2).

    Consume Redis Streams document.classified → Generate embeddings → Publish document.indexed
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        redis_client: aioredis.Redis,
    ):
        """
        Initialise EmbeddingPipeline.

        Args:
            db_pool: Pool asyncpg pour PostgreSQL
            redis_client: Client Redis pour Streams
        """
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.embedding_generator = EmbeddingGenerator(db_pool=db_pool)
        self.running = False
        self.consecutive_failures = 0

        logger.info(
            "EmbeddingPipeline initialized",
            input_stream=REDIS_STREAM_INPUT,
            output_stream=REDIS_STREAM_OUTPUT,
        )

    async def start(self) -> None:
        """
        Démarre le pipeline consumer (boucle infinie).

        Crée consumer group si nécessaire, puis consume events en continu.
        """
        # Créer consumer group si n'existe pas
        try:
            await self.redis_client.xgroup_create(
                name=REDIS_STREAM_INPUT,
                groupname=CONSUMER_GROUP,
                id="0",
                mkstream=True,
            )
            logger.info("Consumer group created", group=CONSUMER_GROUP)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug("Consumer group already exists", group=CONSUMER_GROUP)
            else:
                raise

        self.running = True
        logger.info("EmbeddingPipeline started", consumer=CONSUMER_NAME)

        # Boucle infinie consumer
        while self.running:
            try:
                await self._consume_batch()
            except Exception as e:
                logger.error("Consumer loop error", error=str(e))
                await asyncio.sleep(5)  # Pause avant retry

    async def stop(self) -> None:
        """Arrête le pipeline gracefully."""
        self.running = False
        logger.info("EmbeddingPipeline stopped")

    async def _consume_batch(self) -> None:
        """
        Consume un batch d'events depuis Redis Streams.

        XREADGROUP avec block=5s, count=10.
        """
        try:
            # XREADGROUP block 5 secondes max, max 10 messages
            events = await self.redis_client.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={REDIS_STREAM_INPUT: ">"},
                count=10,
                block=5000,  # 5s timeout
            )

            if not events:
                return  # Pas de nouveaux messages

            # events format: [(stream_name, [(message_id, data), ...])]
            for stream_name, messages in events:
                for message_id, data in messages:
                    await self._process_message(
                        message_id=message_id.decode(),
                        data=data,
                    )

        except Exception as e:
            logger.error("Batch consume error", error=str(e))
            await asyncio.sleep(1)

    async def _process_message(
        self,
        message_id: str,
        data: dict,
    ) -> None:
        """
        Traite un message document.classified.

        Pipeline:
        1. Extract document_id depuis event
        2. Fetch text_content depuis ingestion.document_metadata
        3. Generate embedding via EmbeddingGenerator (avec retry)
        4. Store embedding dans knowledge.embeddings
        5. Publish event document.indexed
        6. ACK message Redis Streams

        Args:
            message_id: ID message Redis Streams
            data: Data event (dict bytes)
        """
        try:
            # Décoder data (bytes → str)
            event_data = {k.decode(): v.decode() for k, v in data.items()}
            raw_doc_id = event_data.get("document_id")
            if not raw_doc_id:
                raise PipelineError(
                    f"Missing document_id in event data: {event_data}"
                )
            document_id = UUID(raw_doc_id)

            logger.info(
                "Processing document.classified event",
                message_id=message_id,
                document_id=str(document_id),
            )

            # 1. Fetch text_content depuis PostgreSQL
            document_metadata = await self._fetch_document_metadata(document_id)

            if not document_metadata:
                logger.warning(
                    "Document metadata not found, skipping",
                    document_id=str(document_id),
                )
                await self._ack_message(message_id)
                return

            text_content = document_metadata.get("ocr_text") or document_metadata.get(
                "text_content"
            )
            if not text_content:
                logger.warning(
                    "No text content for document, skipping",
                    document_id=str(document_id),
                )
                await self._ack_message(message_id)
                return

            # 2. Generate embedding (retries gérés par EmbeddingGenerator)
            embedding_result = await self._generate_embedding(
                document_id=document_id,
                text_content=text_content,
                metadata=document_metadata,
            )

            # 3. Store embedding dans knowledge.embeddings (Task 2.3)
            await self._store_embedding(
                document_id=document_id,
                embedding_vector=embedding_result.embedding_vector,
                model_name=embedding_result.model_name,
                confidence=embedding_result.confidence,
                metadata=embedding_result.metadata,
            )

            # 4. Publish event document.indexed
            await self._publish_indexed_event(
                document_id=document_id,
                metadata=embedding_result.metadata,
            )

            # 5. ACK message Redis
            await self._ack_message(message_id)

            # Reset consecutive failures sur succès
            self.consecutive_failures = 0

            logger.info(
                "Document embedding pipeline completed",
                document_id=str(document_id),
                confidence=round(embedding_result.confidence, 3),
            )

        except Exception as e:
            # Fail-explicit : log error + NACK (Task 2.6)
            self.consecutive_failures += 1
            logger.error(
                "Document embedding pipeline failed",
                message_id=message_id,
                error=str(e),
                consecutive_failures=self.consecutive_failures,
            )

            # Alerte Telegram si >5 échecs consécutifs (Task 2.5)
            if self.consecutive_failures >= ALERT_THRESHOLD_FAILURES:
                await self._send_alert_telegram(
                    f"Embedding pipeline: {self.consecutive_failures} échecs consécutifs. "
                    f"Dernière erreur: {str(e)}"
                )

            # Pas de ACK → message sera redelivered
            # (ou move to DLQ après X tentatives dans Redis config)

    async def _fetch_document_metadata(self, document_id: UUID) -> Optional[dict]:
        """
        Récupère métadonnées document depuis ingestion.document_metadata.

        Args:
            document_id: UUID document

        Returns:
            Dict métadonnées ou None si not found
        """
        query = """
            SELECT
                document_id,
                original_filename,
                final_path,
                ocr_text,
                classification_category,
                classification_subcategory,
                classification_confidence,
                metadata
            FROM ingestion.document_metadata
            WHERE document_id = $1
        """

        row = await self.db_pool.fetchrow(query, document_id)
        if not row:
            return None

        return dict(row)

    async def _generate_embedding(
        self,
        document_id: UUID,
        text_content: str,
        metadata: dict,
    ):
        """
        Génère embedding via EmbeddingGenerator.

        NOTE: PAS de retry ici. EmbeddingGenerator gère déjà son propre
        retry backoff exponentiel (1s, 2s, 4s, 3 tentatives). Un second
        retry ici causerait 3x3=9 tentatives.

        Args:
            document_id: UUID document
            text_content: Texte à embedder
            metadata: Métadonnées document

        Returns:
            EmbeddingResult

        Raises:
            PipelineError: Si échec après retries du generator
        """
        try:
            result = await self.embedding_generator.generate_embedding(
                document_id=document_id,
                text_content=text_content,
                metadata=metadata,
            )
            return result

        except Exception as e:
            error_msg = f"Embedding generation failed for document {document_id}"
            logger.error(error_msg, document_id=str(document_id), error=str(e))

            await self._send_alert_telegram(
                f"Embedding failed pour document {document_id}: {str(e)}"
            )

            raise PipelineError(error_msg) from e

    async def _store_embedding(
        self,
        document_id: UUID,
        embedding_vector: list[float],
        model_name: str,
        confidence: float,
        metadata: dict,
    ) -> None:
        """
        Stocke embedding dans knowledge.embeddings (Task 2.3).

        Args:
            document_id: UUID document (FK vers ingestion.document_metadata)
            embedding_vector: Vecteur 1024 dimensions
            model_name: Modèle utilisé (voyage-4-large)
            confidence: Score de confiance [0.0-1.0]
            metadata: Métadonnées embedding
        """
        query = """
            INSERT INTO knowledge.embeddings (
                document_id,
                embedding,
                model,
                confidence,
                metadata,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (document_id) DO UPDATE
            SET
                embedding = EXCLUDED.embedding,
                model = EXCLUDED.model,
                confidence = EXCLUDED.confidence,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
        """

        # pgvector attend un string formaté '[x,y,z]' ou numpy array
        # asyncpg ne convertit pas list[float] → vector automatiquement
        vector_str = "[" + ",".join(str(x) for x in embedding_vector) + "]"

        await self.db_pool.execute(
            query,
            document_id,
            vector_str,
            model_name,
            confidence,
            metadata,  # asyncpg gère dict → JSONB nativement
        )

        logger.debug(
            "Embedding stored in knowledge.embeddings",
            document_id=str(document_id),
            model=model_name,
        )

    async def _publish_indexed_event(
        self,
        document_id: UUID,
        metadata: dict,
    ) -> None:
        """
        Publie event document.indexed dans Redis Streams (Task 2.3).

        Args:
            document_id: UUID document
            metadata: Métadonnées embedding
        """
        event_data = {
            "document_id": str(document_id),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "model": metadata.get("model_name", "voyage-4-large"),
            "confidence": str(metadata.get("confidence", 0.0)),
        }

        message_id = await self.redis_client.xadd(
            name=REDIS_STREAM_OUTPUT,
            fields=event_data,
        )

        logger.debug(
            "Published document.indexed event",
            document_id=str(document_id),
            message_id=message_id.decode(),
        )

    async def _ack_message(self, message_id: str) -> None:
        """ACK message Redis Streams après traitement réussi."""
        await self.redis_client.xack(
            name=REDIS_STREAM_INPUT,
            groupname=CONSUMER_GROUP,
            id=message_id,
        )

    async def _send_alert_telegram(self, message: str) -> None:
        """
        Envoie alerte Telegram topic System (Task 2.5).

        Args:
            message: Message d'alerte
        """
        try:
            # TODO: Implémenter envoi Telegram via bot (Story 1.9)
            # Pour l'instant, log seulement
            logger.error("TELEGRAM ALERT", message=message)
        except Exception as e:
            logger.error("Failed to send Telegram alert", error=str(e))


# ============================================================
# Main Entry Point
# ============================================================


async def main():
    """Point d'entrée consumer pipeline."""
    # Load env vars
    database_url = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    if not database_url:
        raise ValueError("DATABASE_URL environment variable not set")

    # Connect PostgreSQL
    db_pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
    # Log sans leaker credentials (juste host:port/db)
    safe_url = database_url.split("@")[-1] if "@" in database_url else "***"
    logger.info("PostgreSQL connected", database_url=safe_url)

    # Connect Redis
    redis_client = await aioredis.from_url(redis_url, decode_responses=False)
    logger.info("Redis connected", redis_url=redis_url)

    # Start pipeline
    pipeline = EmbeddingPipeline(db_pool=db_pool, redis_client=redis_client)

    try:
        await pipeline.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Received shutdown signal")
    finally:
        await pipeline.stop()
        await db_pool.close()
        await redis_client.close()
        logger.info("Pipeline shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
