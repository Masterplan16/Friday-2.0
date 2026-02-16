"""
Pipeline Orchestration OCR -> Extract -> Rename -> Store (Story 3.1 - Task 4+5).

Consumer Redis Streams 'document.received' (depuis Epic 2 Story 2.4)
-> OCR via Surya
-> Extract metadata via Claude (anonymise Presidio)
-> Rename intelligent
-> Store dans PostgreSQL (ingestion.document_metadata)
-> Publish 'document.processed' (Redis Streams)

Gestion erreurs fail-explicit (AC7) :
- Surya crash -> NotImplementedError + alerte System topic
- Presidio crash -> NotImplementedError + alerte System topic
- Claude crash -> NotImplementedError + alerte System topic
- Rename crash -> NotImplementedError + alerte System topic

Performance (AC4) :
- Timeout global 45s
- Retry automatique (backoff exponentiel 1s, 2s, 4s max 3 tentatives)
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from agents.src.agents.archiviste.metadata_extractor import MetadataExtractor
from agents.src.agents.archiviste.models import OCRResult
from agents.src.agents.archiviste.ocr import SuryaOCREngine
from agents.src.agents.archiviste.renamer import DocumentRenamer
from redis import asyncio as aioredis

logger = structlog.get_logger(__name__)


def _json_serializer(obj: Any) -> Any:
    """Sérialiseur JSON custom pour datetime et Pydantic models (fix C4)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class OCRPipeline:
    """
    Orchestrateur pipeline OCR (AC3, AC4, AC7).

    Pipeline sequentiel :
    1. OCR via Surya (~5-30s selon pages)
    2. Extract metadata via Claude (~2-5s)
    3. Rename intelligent (~0.5s)
    4. Store metadata dans PostgreSQL (Task 5.2)
    5. Publish evenement 'document.processed'

    Timeout global : 45s (AC4)
    Retry automatique : 3 tentatives (backoff exponentiel)
    Fail-explicit : Si crash -> alerte + NotImplementedError
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        db_url: Optional[str] = None,
        timeout_seconds: int = 45,
    ):
        """
        Initialiser pipeline OCR.

        Args:
            redis_url: URL Redis pour Streams
            db_url: URL PostgreSQL pour stockage metadata (Task 5.2)
            timeout_seconds: Timeout global pipeline (default 45s, AC4)
        """
        self.redis_url = redis_url
        self.db_url = db_url
        self.timeout_seconds = timeout_seconds

        # Composants pipeline
        self.ocr_engine = SuryaOCREngine(device="cpu")
        self.metadata_extractor = MetadataExtractor()
        self.renamer = DocumentRenamer()

        self.redis: Optional[aioredis.Redis] = None
        self._db_pool = None

    async def connect_redis(self):
        """Connecter a Redis Streams."""
        if self.redis is None:
            self.redis = await aioredis.from_url(self.redis_url)
            logger.info("pipeline.redis_connected", redis_url=self.redis_url)

    async def disconnect_redis(self):
        """Deconnecter Redis."""
        if self.redis:
            await self.redis.close()
            self.redis = None
            logger.info("pipeline.redis_disconnected")

    async def _connect_db(self):
        """Connecter a PostgreSQL pour stockage metadata (Task 5.2, fix C1)."""
        if self._db_pool is not None or not self.db_url:
            return
        try:
            import asyncpg

            self._db_pool = await asyncpg.create_pool(self.db_url, min_size=1, max_size=3)
            logger.info("pipeline.db_connected")
        except Exception as e:
            logger.error("pipeline.db_connection_failed", error=str(e))

    async def disconnect_db(self):
        """Fermer pool PostgreSQL."""
        if self._db_pool:
            await self._db_pool.close()
            self._db_pool = None

    async def process_document(
        self, file_path: str, filename: str, metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Traiter document complet : OCR -> Extract -> Rename -> Store (AC3).

        Pipeline sequentiel avec timeout global 45s (AC4) et retry (Task 4.5).

        Args:
            file_path: Chemin fichier a traiter
            filename: Nom fichier original
            metadata: Metadonnees optionnelles (source, category, etc.)

        Returns:
            Dict avec resultats : ocr_result, metadata_extraction, rename_result, timings

        Raises:
            NotImplementedError: Si un composant crash (fail-explicit AC7)
            asyncio.TimeoutError: Si timeout 45s depasse (AC4, Task 4.6)
        """
        start_time = time.time()

        logger.info(
            "pipeline.process_start",
            file_path=file_path,
            filename=filename,
            timeout=self.timeout_seconds,
        )

        try:
            # Timeout global 45s (AC4, Task 4.6)
            async with asyncio.timeout(self.timeout_seconds):
                # 1. OCR via Surya (Task 4.3)
                ocr_start = time.time()
                try:
                    ocr_result = await self._retry_with_backoff(
                        self.ocr_engine.ocr_document, file_path
                    )
                    ocr_duration = time.time() - ocr_start

                    logger.info(
                        "pipeline.ocr_complete",
                        filename=filename,
                        pages=ocr_result.page_count,
                        confidence=ocr_result.confidence,
                        duration=ocr_duration,
                    )

                except NotImplementedError:
                    # Fail-explicit : Surya crash (AC7, Task 4.4)
                    logger.error("pipeline.ocr_failed", filename=filename)
                    await self._publish_error_event(
                        filename=filename,
                        error_type="surya_unavailable",
                        message="Surya OCR unavailable",
                    )
                    raise

                # 2. Extract metadata via Claude (Task 4.3)
                extract_start = time.time()
                try:
                    metadata_result = await self._retry_with_backoff(
                        self.metadata_extractor.extract_metadata, ocr_result, filename
                    )
                    extract_duration = time.time() - extract_start

                    logger.info(
                        "pipeline.metadata_extracted",
                        filename=filename,
                        doc_type=metadata_result.payload["metadata"].doc_type,
                        emitter=metadata_result.payload["metadata"].emitter,
                        duration=extract_duration,
                    )

                except NotImplementedError:
                    # Fail-explicit : Presidio ou Claude crash (AC7, Task 4.4)
                    logger.error("pipeline.metadata_extraction_failed", filename=filename)
                    await self._publish_error_event(
                        filename=filename,
                        error_type="metadata_extraction_unavailable",
                        message="Presidio or Claude unavailable",
                    )
                    raise

                # 3. Rename intelligent (Task 4.3, fix H1: fail-explicit)
                rename_start = time.time()
                try:
                    rename_result = await self._retry_with_backoff(
                        self.renamer.rename_document, filename, metadata_result.payload["metadata"]
                    )
                    rename_duration = time.time() - rename_start

                    logger.info(
                        "pipeline.document_renamed",
                        filename=filename,
                        new_filename=rename_result.payload["new_filename"],
                        duration=rename_duration,
                    )

                except Exception as e:
                    # Fix H1: AC7 dit "JAMAIS renommage silencieux rate"
                    logger.error("pipeline.rename_failed", filename=filename, error=str(e))
                    await self._publish_error_event(
                        filename=filename,
                        error_type="rename_failed",
                        message=f"Document rename failed: {str(e)}",
                    )
                    raise NotImplementedError(f"Document rename failed: {str(e)}") from e

                total_duration = time.time() - start_time

                # 4. Store metadata dans PostgreSQL (Task 5.2, fix C1)
                extracted_meta = metadata_result.payload["metadata"]
                anonymized_text = metadata_result.payload.get("anonymized_text", "")
                await self._store_metadata(
                    filename=filename,
                    file_path=file_path,
                    ocr_text=anonymized_text,
                    extracted_meta=extracted_meta,
                    ocr_result=ocr_result,
                    total_duration=total_duration,
                )

                # 5. Publish evenement 'document.processed' (Task 4.3)
                # Fix C4: model_dump(mode="json") pour serialisation datetime
                result = {
                    "filename": filename,
                    "file_path": file_path,
                    "ocr_result": ocr_result.model_dump(mode="json"),
                    "metadata": extracted_meta.model_dump(mode="json"),
                    "rename_result": rename_result.payload["rename_result"].model_dump(mode="json"),
                    "timings": {
                        "ocr_duration": ocr_duration,
                        "extract_duration": extract_duration,
                        "rename_duration": rename_duration,
                        "total_duration": total_duration,
                    },
                    "success": True,
                }

                await self._publish_processed_event(result)

                # Alerte si latence >35s (seuil 45s avec marge, AC4)
                if total_duration > 35.0:
                    logger.warning(
                        "pipeline.latency_high",
                        filename=filename,
                        duration=total_duration,
                        threshold=35.0,
                    )

                logger.info(
                    "pipeline.process_complete",
                    filename=filename,
                    total_duration=total_duration,
                    success=True,
                )

                return result

        except asyncio.TimeoutError:
            # Timeout 45s depasse (AC4, Task 4.6)
            duration = time.time() - start_time
            logger.error(
                "pipeline.timeout",
                filename=filename,
                duration=duration,
                timeout=self.timeout_seconds,
            )
            await self._publish_error_event(
                filename=filename,
                error_type="timeout",
                message=f"Pipeline timeout apres {duration:.1f}s (limite {self.timeout_seconds}s)",
            )
            raise

    async def _retry_with_backoff(self, func, *args, max_retries: int = 3, **kwargs):
        """
        Retry automatique avec backoff exponentiel (Task 4.5).

        Retry : 1s, 2s, 4s (max 3 tentatives)

        Args:
            func: Fonction async a appeler
            *args: Arguments positionnels
            max_retries: Nombre max de tentatives (default 3)
            **kwargs: Arguments nommes

        Returns:
            Resultat de func()

        Raises:
            Exception de la derniere tentative si toutes echouent
        """
        last_exception = None

        for attempt in range(1, max_retries + 1):
            try:
                return await func(*args, **kwargs)

            except NotImplementedError:
                # Fail-explicit : Ne PAS retry si NotImplementedError (composant indisponible)
                raise

            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    backoff = 2 ** (attempt - 1)  # 1s, 2s, 4s
                    logger.warning(
                        "pipeline.retry",
                        func=func.__name__,
                        attempt=attempt,
                        max_retries=max_retries,
                        backoff=backoff,
                        error=str(e),
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(
                        "pipeline.retry_exhausted",
                        func=func.__name__,
                        attempts=max_retries,
                        error=str(e),
                    )

        raise last_exception

    async def _store_metadata(
        self,
        filename: str,
        file_path: str,
        ocr_text: str,
        extracted_meta,
        ocr_result: OCRResult,
        total_duration: float,
    ):
        """
        Stocker metadata dans PostgreSQL (Task 5.2, fix C1).

        Table: ingestion.document_metadata (migration 030)

        Args:
            filename: Nom fichier
            file_path: Chemin fichier
            ocr_text: Texte OCR anonymise (AC6 RGPD)
            extracted_meta: MetadataExtraction
            ocr_result: OCRResult
            total_duration: Duree totale pipeline
        """
        if not self.db_url:
            logger.warning("pipeline.db_not_configured", filename=filename)
            return

        await self._connect_db()
        if not self._db_pool:
            logger.error("pipeline.db_pool_unavailable", filename=filename)
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO ingestion.document_metadata
                        (filename, file_path, ocr_text, extracted_date, doc_type,
                         emitter, amount, confidence, page_count, processing_duration)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    filename,
                    file_path,
                    ocr_text,
                    extracted_meta.date,
                    extracted_meta.doc_type,
                    extracted_meta.emitter,
                    float(extracted_meta.amount),
                    float(min(ocr_result.confidence, extracted_meta.confidence)),
                    ocr_result.page_count,
                    total_duration,
                )
                logger.info(
                    "pipeline.metadata_stored", filename=filename, doc_type=extracted_meta.doc_type
                )
        except Exception as e:
            logger.error("pipeline.metadata_store_failed", filename=filename, error=str(e))

    async def _publish_processed_event(self, result: Dict[str, Any]):
        """
        Publier evenement 'document.processed' dans Redis Streams (Task 4.3).

        Fix M1: dot notation conforme CLAUDE.md.
        Fix C4: json.dumps avec serialiseur datetime custom.
        """
        if not self.redis:
            await self.connect_redis()

        try:
            await self.redis.xadd(
                "document.processed", {"data": json.dumps(result, default=_json_serializer)}
            )
            logger.info(
                "pipeline.event_published", stream="document.processed", filename=result["filename"]
            )
        except Exception as e:
            logger.error("pipeline.publish_failed", error=str(e))

    async def _publish_error_event(self, filename: str, error_type: str, message: str):
        """
        Publier evenement erreur dans Redis Streams (Task 4.4).

        Fix M1: dot notation conforme CLAUDE.md.
        """
        if not self.redis:
            await self.connect_redis()

        try:
            error_data = {
                "filename": filename,
                "error_type": error_type,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await self.redis.xadd("pipeline.error", {"data": json.dumps(error_data)})
            logger.info(
                "pipeline.error_event_published",
                stream="pipeline.error",
                filename=filename,
                error_type=error_type,
            )
        except Exception as e:
            logger.error("pipeline.error_publish_failed", error=str(e))
