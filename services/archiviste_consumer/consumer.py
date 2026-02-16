"""
Consumer Archiviste - Redis Streams document.received (Story 3.6 Task 2).

Consomme événements document.received (source=telegram ou source=scanner) et
appelle le pipeline OCR complet (Story 3.1) :
1. OCR via Surya
2. Extract metadata via Claude (anonymisé Presidio)
3. Rename intelligent
4. Store dans PostgreSQL ingestion.document_metadata
5. Classification arborescence (Story 3.2)
6. Embeddings pgvector (Story 6.2)

Workflow :
1. XREADGROUP pour lire messages document.received (block 5s)
2. Pour chaque message : process_document()
3. Appeler pipeline OCR complet
4. XACK pour acknowledger message
5. Cleanup zone transit après traitement (15 min max)
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import structlog
from agents.src.agents.archiviste.pipeline import OCRPipeline
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

# Configuration Redis Streams
STREAM_NAME = "document.received"
CONSUMER_GROUP = "archiviste-processor"
CONSUMER_NAME = "archiviste-processor-1"
BLOCK_MS = 5000  # Block 5s en attente de nouveaux messages
BATCH_SIZE = 10  # Nombre max messages lus par batch

# Configuration cleanup zone transit
TRANSIT_CLEANUP_DELAY_SECONDS = 900  # 15 minutes (AC2 Story 3.6)

# Shutdown graceful
shutdown_event = asyncio.Event()


async def init_consumer_group(redis_client: Redis) -> None:
    """
    Initialise consumer group si n'existe pas.

    Crée group 'archiviste-processor' sur stream 'document.received'.
    Utilise mkstream=True pour créer stream automatiquement si absent.

    Args:
        redis_client: Client Redis asyncio

    Raises:
        Exception si création échoue
    """
    try:
        # Créer group (mkstream=True crée stream si absent)
        await redis_client.xgroup_create(
            name=STREAM_NAME, groupname=CONSUMER_GROUP, id="0", mkstream=True
        )
        logger.info(
            "consumer_group_created",
            stream=STREAM_NAME,
            group=CONSUMER_GROUP,
        )
    except Exception as e:
        # BUSYGROUP = group existe déjà (OK)
        if "BUSYGROUP" in str(e):
            logger.info(
                "consumer_group_exists",
                stream=STREAM_NAME,
                group=CONSUMER_GROUP,
            )
        else:
            logger.error("consumer_group_creation_failed", error=str(e))
            raise


async def cleanup_transit_file(
    file_path: str, delay_seconds: int = TRANSIT_CLEANUP_DELAY_SECONDS
) -> None:
    """
    Supprime fichier zone transit après délai (AC2 Story 3.6).

    Args:
        file_path: Chemin fichier à supprimer
        delay_seconds: Délai avant suppression (default 15 min)
    """
    try:
        # Attendre délai
        await asyncio.sleep(delay_seconds)

        # Vérifier que fichier existe encore
        path = Path(file_path)
        if path.exists():
            path.unlink()
            logger.info(
                "transit_file_cleaned",
                file_path=file_path,
                delay_seconds=delay_seconds,
            )
        else:
            logger.debug(
                "transit_file_already_removed",
                file_path=file_path,
            )

    except Exception as e:
        logger.error(
            "transit_cleanup_failed",
            file_path=file_path,
            error=str(e),
        )


async def process_document_event(
    event_id: str,
    event_data: dict[str, Any],
    pipeline: OCRPipeline,
) -> None:
    """
    Traite un événement document.received via pipeline OCR complet.

    Workflow :
    1. Extraire metadata événement (filename, file_path, source)
    2. Appeler pipeline.process_document() (OCR → Extract → Rename → Store)
    3. Schedule cleanup zone transit après 15 min (AC2 Story 3.6)

    Args:
        event_id: ID événement Redis (e.g., "1234567890-0")
        event_data: Payload événement (filename, file_path, source, etc.)
        pipeline: Instance OCRPipeline

    Raises:
        Exception si traitement échoue
    """
    # Extraire champs (bytes ou str selon source)
    filename = event_data.get(b"filename") or event_data.get("filename")
    file_path = (
        event_data.get(b"file_path")
        or event_data.get("file_path")
        or event_data.get(b"filepath")
        or event_data.get("filepath")
    )
    source = event_data.get(b"source") or event_data.get("source")
    mime_type = event_data.get(b"mime_type") or event_data.get("mime_type")

    # Décoder bytes si nécessaire (Redis Streams peut retourner bytes)
    if isinstance(filename, bytes):
        filename = filename.decode("utf-8")
    if isinstance(file_path, bytes):
        file_path = file_path.decode("utf-8")
    if isinstance(source, bytes):
        source = source.decode("utf-8")
    if isinstance(mime_type, bytes):
        mime_type = mime_type.decode("utf-8")

    log = logger.bind(
        event_id=event_id,
        filename=filename,
        file_path=file_path,
        source=source,
        mime_type=mime_type,
    )

    log.info("document_event_received")

    try:
        # Appeler pipeline OCR complet (Story 3.1)
        # Pipeline : OCR → Extract metadata → Rename → Store PostgreSQL
        result = await pipeline.process_document(
            filename=filename,
            file_path=file_path,
        )

        log.info(
            "document_processed_complete",
            success=result.get("success", False),
            total_duration=result.get("timings", {}).get("total_duration", 0),
        )

        # Schedule cleanup zone transit après 15 min (AC2 Story 3.6)
        # Note : Uniquement pour fichiers Telegram (zone transit VPS)
        if source == "telegram" and file_path:
            # Lancer cleanup en background (fire-and-forget)
            asyncio.create_task(cleanup_transit_file(file_path))

    except NotImplementedError as e:
        # Fail-explicit : composant indisponible (Surya, Presidio, Claude)
        log.error("document_processing_failed_explicit", error=str(e))
        # Ne PAS retry si NotImplementedError
        raise

    except Exception as e:
        log.error("document_processing_failed", error=str(e), error_type=type(e).__name__)
        raise


async def consume_loop(redis_client: Redis, pipeline: OCRPipeline) -> None:
    """
    Boucle principale consumer Redis Streams.

    Workflow :
    1. XREADGROUP pour lire messages (block BLOCK_MS)
    2. Pour chaque message : process_document_event()
    3. XACK pour acknowledger message
    4. Gestion erreurs : log + continue (pas de crash)

    Args:
        redis_client: Client Redis asyncio
        pipeline: Instance OCRPipeline

    Note:
        Boucle infinie jusqu'à shutdown_event.set()
    """
    logger.info("consumer_loop_started", consumer_name=CONSUMER_NAME)

    while not shutdown_event.is_set():
        try:
            # XREADGROUP pour lire messages non-ack du groupe
            messages = await redis_client.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_NAME: ">"},
                count=BATCH_SIZE,
                block=BLOCK_MS,
            )

            # Si aucun message reçu (timeout), continuer
            if not messages:
                continue

            # Traiter chaque message
            for stream_name, stream_messages in messages:
                for event_id, event_data in stream_messages:
                    log = logger.bind(
                        event_id=(
                            event_id.decode("utf-8") if isinstance(event_id, bytes) else event_id
                        )
                    )

                    try:
                        # Traiter événement
                        await process_document_event(
                            event_id=(
                                event_id.decode("utf-8")
                                if isinstance(event_id, bytes)
                                else event_id
                            ),
                            event_data=event_data,
                            pipeline=pipeline,
                        )

                        # XACK : acknowledger message traité avec succès
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, event_id)

                        log.info("event_acked")

                    except NotImplementedError as e:
                        # Fail-explicit : Ne PAS ack (permet retry manuel si composant revient)
                        log.error(
                            "event_processing_failed_explicit",
                            error=str(e),
                        )
                        # Continuer avec messages suivants (pas de crash)
                        continue

                    except Exception as e:
                        # Erreur traitement : log mais continuer (résilience)
                        log.error(
                            "event_processing_failed",
                            error=str(e),
                            error_type=type(e).__name__,
                        )
                        # XACK quand même pour éviter boucle infinie retry
                        # (si erreur persistante, message sera perdu)
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, event_id)
                        log.warning("event_acked_after_error")

        except asyncio.CancelledError:
            logger.info("consumer_loop_cancelled")
            break

        except Exception as e:
            logger.error(
                "consumer_loop_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Attendre 5s avant retry (backoff simple)
            await asyncio.sleep(5)

    logger.info("consumer_loop_stopped")


async def main() -> None:
    """Point d'entrée principal du consumer."""
    # Configuration depuis envvars
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    db_url = os.getenv("DATABASE_URL")

    if not db_url:
        logger.critical("DATABASE_URL envvar manquante")
        sys.exit(1)

    try:
        # Connexion Redis
        redis_client = await Redis.from_url(redis_url, decode_responses=False)
        await redis_client.ping()
        logger.info("redis_connected", redis_url=redis_url)

        # Initialiser consumer group
        await init_consumer_group(redis_client)

        # Initialiser pipeline OCR (Story 3.1)
        pipeline = OCRPipeline(redis_url=redis_url, db_url=db_url)
        await pipeline.connect_redis()
        await pipeline.connect_db()
        logger.info("pipeline_initialized")

        # Démarrer boucle consumer
        await consume_loop(redis_client, pipeline)

    except KeyboardInterrupt:
        logger.info("consumer_interrupted")

    except Exception as e:
        logger.critical("consumer_fatal_error", error=str(e), error_type=type(e).__name__)
        sys.exit(1)

    finally:
        # Cleanup
        if redis_client:
            await redis_client.close()
            logger.info("redis_disconnected")
        if pipeline:
            await pipeline.disconnect_redis()
            await pipeline.disconnect_db()
            logger.info("pipeline_disconnected")


if __name__ == "__main__":
    asyncio.run(main())
