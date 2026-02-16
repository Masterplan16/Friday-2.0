"""
Pipeline de classification de documents pour l'agent Archiviste.

Story 3.2 - Task 4
Consumer Redis Streams document.processed → classify → move → PostgreSQL → document.classified
"""

import asyncio
import json
import time
from collections import deque
import structlog
import asyncpg
import redis.asyncio as redis

from agents.src.agents.archiviste.classifier import DocumentClassifier
from agents.src.agents.archiviste.file_mover import FileMover
from agents.src.agents.archiviste.models import ClassificationResult

logger = structlog.get_logger(__name__)

# Latency monitoring (Task 9.2-9.3)
LATENCY_ALERT_MEDIAN_MS = 8_000  # Alerte si médiane > 8s
LATENCY_WINDOW_SIZE = 10  # Fenêtre glissante 10 derniers documents

# Retry configuration (Task 4.5)
MAX_RETRIES = 3
INITIAL_BACKOFF_S = 1.0
BACKOFF_MULTIPLIER = 2.0

# Timeout configuration (Task 4.6)
PROCESS_TIMEOUT_S = 10.0


class ClassificationPipeline:
    """
    Pipeline de classification et déplacement de documents.

    Consumer Redis Streams document.processed
    Séquence : Classify → Validate → Move → Update PG → Publish document.classified
    """

    def __init__(self, redis_client: redis.Redis, db_pool: asyncpg.Pool):
        """
        Initialise le pipeline.

        Args:
            redis_client: Client Redis pour Streams
            db_pool: Pool PostgreSQL
        """
        self.redis_client = redis_client
        self.db_pool = db_pool
        self.classifier = DocumentClassifier()
        self.file_mover = FileMover(db_pool=db_pool)
        self.consumer_group = "archiviste-classification"
        self.consumer_name = "classification-worker-1"
        self.stream_key = "document.processed"
        self._latency_window: deque = deque(maxlen=LATENCY_WINDOW_SIZE)

    async def start(self):
        """Démarre le consumer Redis Streams."""
        logger.info("classification_pipeline_starting")

        # Créer consumer group si n'existe pas
        try:
            await self.redis_client.xgroup_create(
                self.stream_key, self.consumer_group, id="0", mkstream=True
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

        logger.info("classification_pipeline_started", stream=self.stream_key)

        # Boucle de consommation
        while True:
            try:
                # Lire messages (blocking 5s)
                messages = await self.redis_client.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.stream_key: ">"},
                    count=1,
                    block=5000,
                )

                if not messages:
                    continue

                # Traiter chaque message
                for stream, msgs in messages:
                    for msg_id, data in msgs:
                        await self._process_with_retry(msg_id, data)
                        # Acknowledge message
                        await self.redis_client.xack(self.stream_key, self.consumer_group, msg_id)

            except Exception as e:
                logger.error("pipeline_consumer_error", error=str(e))
                await asyncio.sleep(INITIAL_BACKOFF_S)

    async def _process_with_retry(self, msg_id: bytes, data: dict):
        """
        Traite un document avec retry et backoff exponentiel (Task 4.5).

        Args:
            msg_id: ID du message Redis
            data: Données du document
        """
        backoff = INITIAL_BACKOFF_S

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Timeout global 10s (Task 4.6)
                await asyncio.wait_for(
                    self._process_document(msg_id, data), timeout=PROCESS_TIMEOUT_S
                )
                return  # Succès, on sort
            except asyncio.TimeoutError:
                document_id = data.get(b"document_id", b"unknown").decode()
                logger.error(
                    "document_processing_timeout",
                    document_id=document_id,
                    timeout_s=PROCESS_TIMEOUT_S,
                    attempt=attempt,
                )
                if attempt == MAX_RETRIES:
                    await self._notify_processing_failure(
                        document_id, f"Timeout {PROCESS_TIMEOUT_S}s after {MAX_RETRIES} attempts"
                    )
                    return
            except (ConnectionError, TimeoutError, OSError) as e:
                document_id = data.get(b"document_id", b"unknown").decode()
                logger.warning(
                    "document_processing_retryable_error",
                    document_id=document_id,
                    error=str(e),
                    attempt=attempt,
                    next_backoff_s=backoff,
                )
                if attempt == MAX_RETRIES:
                    await self._notify_processing_failure(
                        document_id, f"{type(e).__name__}: {e} after {MAX_RETRIES} attempts"
                    )
                    return
                await asyncio.sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
            except Exception as e:
                # Erreur non-retryable (ValueError, etc.) → pas de retry
                document_id = data.get(b"document_id", b"unknown").decode()
                logger.error(
                    "document_processing_failed",
                    document_id=document_id,
                    error=str(e),
                    attempt=attempt,
                )
                await self._notify_processing_failure(document_id, str(e))
                return

    async def _process_document(self, msg_id: bytes, data: dict):
        """
        Traite un document : classify → move → update PG.

        Args:
            msg_id: ID du message Redis
            data: Données du document (document_id, file_path, metadata)
        """
        t_start = time.monotonic()

        document_id = data.get(b"document_id", b"").decode()
        file_path = data.get(b"file_path", b"").decode()
        metadata_json = data.get(b"metadata", b"{}").decode()
        metadata = json.loads(metadata_json)

        logger.info("document_processing_started", document_id=document_id, file_path=file_path)

        # === PHASE 1 : Classification ===
        t_classify_start = time.monotonic()
        classification_result = await self.classifier.classify(
            {"ocr_text": metadata.get("ocr_text", ""), "document_id": document_id}
        )
        classify_duration_ms = (time.monotonic() - t_classify_start) * 1000

        # Extraire ClassificationResult du payload
        classification = ClassificationResult(**classification_result.payload)

        # === PHASE 2 : Validation anti-contamination (AC6) ===
        if classification.category == "finance":
            valid_perimeters = {"selarl", "scm", "sci_ravas", "sci_malbosc", "personal"}
            if classification.subcategory not in valid_perimeters:
                raise ValueError(f"Invalid financial perimeter: {classification.subcategory}")

        # === PHASE 3 : Déplacement fichier ===
        move_duration_ms = 0.0
        if classification.confidence >= 0.7:
            t_move_start = time.monotonic()
            move_result = await self.file_mover.move_document(
                source_path=file_path, classification=classification, document_id=document_id
            )
            move_duration_ms = (time.monotonic() - t_move_start) * 1000

            if not move_result.success:
                raise RuntimeError(f"Move failed: {move_result.error}")

            final_path = move_result.destination_path
        else:
            # Confidence <0.7 → status pending, pas de déplacement (Task 4.7)
            logger.warning(
                "low_confidence_classification",
                document_id=document_id,
                confidence=classification.confidence,
                category=classification.category,
            )
            # Notification Telegram topic System (M4)
            await self._notify_low_confidence(document_id, classification)
            final_path = file_path  # Reste en transit

        # === PHASE 4 : Update PostgreSQL (déjà fait par file_mover si document_id) ===
        # file_mover._update_database() a déjà mis à jour

        # === PHASE 5 : Publish document.classified ===
        status = "classified" if classification.confidence >= 0.7 else "pending"
        await self.redis_client.xadd(
            "document.classified",
            {
                "document_id": document_id,
                "category": classification.category,
                "subcategory": classification.subcategory or "",
                "final_path": final_path,
                "confidence": str(classification.confidence),
                "status": status,
            },
        )

        # === Latency monitoring (Task 9.2-9.3) ===
        total_duration_ms = (time.monotonic() - t_start) * 1000
        self._latency_window.append(total_duration_ms)

        logger.info(
            "document_processing_completed",
            document_id=document_id,
            category=classification.category,
            final_path=final_path,
            status=status,
            classify_duration_ms=round(classify_duration_ms, 1),
            move_duration_ms=round(move_duration_ms, 1),
            total_duration_ms=round(total_duration_ms, 1),
        )

        # Alerte si médiane latence > 8s (Task 9.3)
        await self._check_latency_alert()

    async def _notify_low_confidence(self, document_id: str, classification: ClassificationResult):
        """
        Notifie via Redis Streams quand confidence <0.7 (Task 4.7).

        Publication sur stream notification.system pour que le bot Telegram
        envoie une alerte dans le topic System.
        """
        await self.redis_client.xadd(
            "notification.system",
            {
                "type": "low_confidence_classification",
                "document_id": document_id,
                "category": classification.category,
                "subcategory": classification.subcategory or "",
                "confidence": str(classification.confidence),
                "message": (
                    f"Classification confidence {classification.confidence:.2f} < 0.7 "
                    f"pour document {document_id}. Validation manuelle requise."
                ),
            },
        )

    async def _notify_processing_failure(self, document_id: str, error: str):
        """
        Notifie via Redis Streams quand le traitement échoue après retries.

        Publication sur stream notification.system pour alerte Telegram.
        """
        await self.redis_client.xadd(
            "notification.system",
            {
                "type": "classification_failure",
                "document_id": document_id,
                "error": error,
                "message": (f"Classification echouee pour document {document_id}: {error}"),
            },
        )

    async def _check_latency_alert(self):
        """
        Vérifie la médiane de latence et alerte si > 8s (Task 9.3).

        Utilise une fenêtre glissante des N derniers documents.
        """
        if len(self._latency_window) < 3:
            return  # Pas assez de données

        sorted_latencies = sorted(self._latency_window)
        n = len(sorted_latencies)
        median = sorted_latencies[n // 2]

        if median > LATENCY_ALERT_MEDIAN_MS:
            logger.warning(
                "classification_latency_alert",
                median_ms=round(median, 1),
                threshold_ms=LATENCY_ALERT_MEDIAN_MS,
                window_size=n,
            )
            await self.redis_client.xadd(
                "notification.system",
                {
                    "type": "latency_alert",
                    "message": (
                        f"Latence classification elevee: mediane {median:.0f}ms "
                        f"(seuil {LATENCY_ALERT_MEDIAN_MS}ms) "
                        f"sur les {n} derniers documents"
                    ),
                },
            )


async def main():
    """Point d'entrée pour exécution standalone."""
    import os

    redis_url = os.getenv("REDIS_URL")
    db_url = os.getenv("DATABASE_URL")

    if not redis_url:
        raise ValueError("REDIS_URL environment variable is required")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is required")

    redis_client = await redis.from_url(redis_url, decode_responses=False)
    db_pool = await asyncpg.create_pool(dsn=db_url)

    pipeline = ClassificationPipeline(redis_client, db_pool)
    await pipeline.start()


if __name__ == "__main__":
    asyncio.run(main())
