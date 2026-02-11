"""
Tests intégration consumer stub document-processor.

Story 2.4 - Subtask 5.3

Tests avec Redis Streams réel (mock PostgreSQL).
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.asyncio import Redis

from services.document_processor.consumer_stub import (
    init_consumer_group,
    process_document_event,
)


@pytest.fixture
async def redis_client():
    """
    Client Redis asyncio pour tests intégration.

    NOTE : En environnement CI, utiliser Redis Docker temporaire
           ou mock si Redis non disponible.
    """
    try:
        client = Redis(host="localhost", port=6379, decode_responses=False)
        await client.ping()
        yield client
        await client.close()
    except Exception:
        # Fallback mock si Redis non disponible
        pytest.skip("Redis non disponible pour tests intégration")


@pytest.fixture
async def db_pool_mock():
    """Mock asyncpg Pool pour tests."""
    pool = AsyncMock()
    pool.execute = AsyncMock()
    return pool


@pytest.mark.integration
@pytest.mark.asyncio
async def test_init_consumer_group_creates_group(redis_client):
    """
    GIVEN Redis Streams sans consumer group
    WHEN init_consumer_group() est appelé
    THEN group 'document-processor-group' créé sur stream 'documents:received'
    """
    # Cleanup avant test
    stream_name = "documents:received"
    group_name = "test-group-init"

    try:
        await redis_client.xgroup_destroy(stream_name, group_name)
    except Exception:
        pass  # Group n'existait pas

    # Créer group avec nom unique pour ce test
    with patch(
        "services.document_processor.consumer_stub.CONSUMER_GROUP", group_name
    ):
        await init_consumer_group(redis_client)

    # Vérifier group existe
    groups = await redis_client.xinfo_groups(stream_name)
    group_names = [g[b"name"].decode("utf-8") for g in groups]

    assert group_name in group_names

    # Cleanup après test
    await redis_client.xgroup_destroy(stream_name, group_name)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_init_consumer_group_idempotent(redis_client):
    """
    GIVEN consumer group existe déjà
    WHEN init_consumer_group() est appelé 2x
    THEN pas d'erreur (idempotent, log 'consumer_group_exists')
    """
    stream_name = "documents:received"
    group_name = "test-group-idempotent"

    try:
        await redis_client.xgroup_destroy(stream_name, group_name)
    except Exception:
        pass

    with patch(
        "services.document_processor.consumer_stub.CONSUMER_GROUP", group_name
    ):
        # Créer 1ère fois
        await init_consumer_group(redis_client)

        # Créer 2ème fois (doit passer sans erreur)
        await init_consumer_group(redis_client)

    # Cleanup
    await redis_client.xgroup_destroy(stream_name, group_name)


@pytest.mark.asyncio
async def test_process_document_event_updates_status(db_pool_mock):
    """
    GIVEN un événement document.received valide
    WHEN process_document_event() est appelé
    THEN UPDATE ingestion.attachments SET status='processed', processed_at=NOW()
    """
    attachment_id = str(uuid.uuid4())
    event_id = "1234567890-0"
    event_data = {
        b"attachment_id": attachment_id.encode("utf-8"),
        b"email_id": str(uuid.uuid4()).encode("utf-8"),
        b"filename": b"facture.pdf",
        b"filepath": b"/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf",
        b"mime_type": b"application/pdf",
        b"size_bytes": b"150000",
        b"source": b"email",
    }

    await process_document_event(
        event_id=event_id, event_data=event_data, db_pool=db_pool_mock
    )

    # Vérifier UPDATE appelé
    db_pool_mock.execute.assert_awaited_once()

    call_args = db_pool_mock.execute.call_args[0]
    sql = call_args[0]
    attachment_uuid = call_args[1]

    assert "UPDATE ingestion.attachments" in sql
    assert "SET status = 'processed'" in sql
    assert "processed_at = NOW()" in sql
    assert str(attachment_uuid) == attachment_id


@pytest.mark.asyncio
async def test_process_document_event_handles_string_keys(db_pool_mock):
    """
    GIVEN événement avec clés string (pas bytes)
    WHEN process_document_event() est appelé
    THEN traitement réussit (handle bytes OU string)
    """
    attachment_id = str(uuid.uuid4())
    event_id = "1234567890-0"

    # Event data avec clés string
    event_data = {
        "attachment_id": attachment_id,
        "email_id": str(uuid.uuid4()),
        "filename": "facture.pdf",
        "filepath": "/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf",
        "mime_type": "application/pdf",
        "size_bytes": "150000",
        "source": "email",
    }

    await process_document_event(
        event_id=event_id, event_data=event_data, db_pool=db_pool_mock
    )

    # Vérifier UPDATE appelé (pas d'erreur sur clés string)
    db_pool_mock.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_document_event_reraises_db_error(db_pool_mock):
    """
    GIVEN échec UPDATE PostgreSQL
    WHEN process_document_event() est appelé
    THEN raise Exception (pour retry dans consume_loop)
    """
    db_pool_mock.execute = AsyncMock(side_effect=Exception("DB connection failed"))

    attachment_id = str(uuid.uuid4())
    event_id = "1234567890-0"
    event_data = {
        b"attachment_id": attachment_id.encode("utf-8"),
        b"email_id": str(uuid.uuid4()).encode("utf-8"),
        b"filename": b"facture.pdf",
        b"filepath": b"/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf",
        b"mime_type": b"application/pdf",
        b"size_bytes": b"150000",
        b"source": b"email",
    }

    with pytest.raises(Exception, match="DB connection failed"):
        await process_document_event(
            event_id=event_id, event_data=event_data, db_pool=db_pool_mock
        )


@pytest.mark.asyncio
async def test_process_document_event_logs_structured_output(db_pool_mock, caplog):
    """
    GIVEN événement valide
    WHEN process_document_event() est appelé
    THEN logs structurés 'document_event_received' + 'document_processed_stub'
    """
    import structlog

    # Reconfigurer structlog pour capture logs
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.KeyValueRenderer(),
        ]
    )

    attachment_id = str(uuid.uuid4())
    event_id = "1234567890-0"
    event_data = {
        b"attachment_id": attachment_id.encode("utf-8"),
        b"email_id": str(uuid.uuid4()).encode("utf-8"),
        b"filename": b"facture.pdf",
        b"filepath": b"/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf",
        b"mime_type": b"application/pdf",
        b"size_bytes": b"150000",
        b"source": b"email",
    }

    with caplog.at_level("INFO"):
        await process_document_event(
            event_id=event_id, event_data=event_data, db_pool=db_pool_mock
        )

    # Vérifier logs présents
    log_messages = [rec.message for rec in caplog.records]

    assert any("document_event_received" in msg for msg in log_messages)
    assert any("document_processed_stub" in msg for msg in log_messages)
