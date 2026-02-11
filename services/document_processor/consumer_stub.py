"""
Consumer stub Archiviste - Redis Streams documents:received.

Story 2.4 - Task 5 (MVP stub Epic 2)

Workflow MVP stub :
1. Consume événements documents:received (Redis Streams)
2. UPDATE ingestion.attachments SET status='processed', processed_at=NOW()
3. Log document_processed_stub

NOTE : Pipeline complet (OCR, renommage intelligent, classement BeeStation)
       implémenté dans Epic 3 - Archiviste & Recherche Documentaire.
       Ce stub permet simplement de valider la plomberie Event-Driven.
"""

import asyncio
import os
import sys
import uuid
from typing import Any

import asyncpg
import structlog
from redis.asyncio import Redis

# Configuration logging structuré
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)

logger = structlog.get_logger(__name__)

# Configuration Redis Streams
STREAM_NAME = "documents:received"
CONSUMER_GROUP = "document-processor-group"
CONSUMER_NAME = "document-processor-1"
BLOCK_MS = 5000  # Block 5s en attente de nouveaux messages
BATCH_SIZE = 10  # Nombre max messages lus par batch

# Shutdown graceful
shutdown_event = asyncio.Event()


async def init_consumer_group(redis_client: Redis) -> None:
    """
    Initialise consumer group si n'existe pas.

    Crée group 'document-processor-group' sur stream 'documents:received'.
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


async def process_document_event(
    event_id: str, event_data: dict[str, Any], db_pool: asyncpg.Pool
) -> None:
    """
    Traite un événement document.received (stub MVP).

    Workflow stub :
    1. Log événement reçu
    2. UPDATE ingestion.attachments SET status='processed', processed_at=NOW()
    3. Log document_processed_stub

    Args:
        event_id: ID événement Redis (e.g., "1234567890-0")
        event_data: Payload événement (attachment_id, email_id, filename, etc.)
        db_pool: Pool asyncpg PostgreSQL

    Raises:
        Exception si traitement échoue
    """
    attachment_id = event_data.get(b"attachment_id") or event_data.get("attachment_id")
    filename = event_data.get(b"filename") or event_data.get("filename")
    mime_type = event_data.get(b"mime_type") or event_data.get("mime_type")

    # Décoder bytes si nécessaire (Redis Streams peut retourner bytes)
    if isinstance(attachment_id, bytes):
        attachment_id = attachment_id.decode("utf-8")
    if isinstance(filename, bytes):
        filename = filename.decode("utf-8")
    if isinstance(mime_type, bytes):
        mime_type = mime_type.decode("utf-8")

    log = logger.bind(
        event_id=event_id,
        attachment_id=attachment_id,
        filename=filename,
        mime_type=mime_type,
    )

    log.info("document_event_received")

    try:
        # UPDATE status = 'processed'
        await db_pool.execute(
            """
            UPDATE ingestion.attachments
            SET status = 'processed', processed_at = NOW(), updated_at = NOW()
            WHERE id = $1
            """,
            uuid.UUID(attachment_id),
        )

        log.info("document_processed_stub")

    except Exception as e:
        log.error("document_processing_failed", error=str(e))
        raise


async def consume_loop(redis_client: Redis, db_pool: asyncpg.Pool) -> None:
    """
    Boucle principale consumer Redis Streams.

    Workflow :
    1. XREADGROUP pour lire messages (block BLOCK_MS)
    2. Pour chaque message : process_document_event()
    3. XACK pour acknowledger message
    4. Gestion erreurs : log + continue (pas de crash)

    Args:
        redis_client: Client Redis asyncio
        db_pool: Pool asyncpg PostgreSQL

    Stops:
        Quand shutdown_event est set
    """
    logger.info(
        "consumer_started",
        stream=STREAM_NAME,
        group=CONSUMER_GROUP,
        consumer=CONSUMER_NAME,
    )

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

            # messages format : [(stream_name, [(event_id, event_data), ...])]
            if not messages:
                continue  # Timeout, retry

            for stream_name, events in messages:
                for event_id, event_data in events:
                    try:
                        # Traiter événement
                        await process_document_event(
                            event_id=event_id.decode("utf-8")
                            if isinstance(event_id, bytes)
                            else event_id,
                            event_data=event_data,
                            db_pool=db_pool,
                        )

                        # ACK événement traité
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, event_id)

                        logger.info(
                            "event_acked",
                            event_id=event_id.decode("utf-8")
                            if isinstance(event_id, bytes)
                            else event_id,
                        )

                    except Exception as e:
                        logger.error(
                            "event_processing_error",
                            event_id=event_id.decode("utf-8")
                            if isinstance(event_id, bytes)
                            else event_id,
                            error=str(e),
                        )
                        # Continue sans ACK -> message sera relivré

        except Exception as e:
            logger.error("consume_loop_error", error=str(e))
            await asyncio.sleep(5)  # Backoff avant retry


async def shutdown_handler(sig: Any) -> None:
    """
    Handler graceful shutdown.

    Set shutdown_event pour arrêter consume_loop proprement.

    Args:
        sig: Signal reçu (SIGINT, SIGTERM)
    """
    logger.info("shutdown_signal_received", signal=sig)
    shutdown_event.set()


async def main() -> None:
    """
    Point d'entrée consumer stub.

    Workflow :
    1. Connexion PostgreSQL + Redis
    2. Initialisation consumer group
    3. Lancement consume_loop
    4. Graceful shutdown sur SIGINT/SIGTERM
    """
    # Configuration depuis env
    database_url = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL")

    if not database_url or not redis_url:
        logger.error("missing_env_vars", DATABASE_URL=database_url, REDIS_URL=redis_url)
        sys.exit(1)

    logger.info("consumer_initializing", stream=STREAM_NAME, group=CONSUMER_GROUP)

    # Connexion PostgreSQL
    db_pool = await asyncpg.create_pool(database_url, min_size=2, max_size=5)

    # Connexion Redis
    redis_client = Redis.from_url(redis_url, decode_responses=False)

    try:
        # Initialiser consumer group
        await init_consumer_group(redis_client)

        # Lancer consume loop
        await consume_loop(redis_client, db_pool)

    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
    finally:
        # Cleanup
        logger.info("consumer_shutting_down")
        await db_pool.close()
        await redis_client.close()
        logger.info("consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
