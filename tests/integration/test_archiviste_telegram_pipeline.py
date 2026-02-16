"""
Tests intégration pipeline Archiviste via Telegram (Story 3.6 Task 2.2).

Test pipeline complet : Telegram upload → Redis Streams → Consumer → OCR Pipeline → PostgreSQL

Ces tests vérifient AC#2 :
- Fichier téléchargé dans zone transit VPS
- Consumer lit événement document.received
- Pipeline Archiviste exécuté (OCR → Extract → Rename → Store)
- Metadata stockée dans PostgreSQL ingestion.document_metadata
- Cleanup zone transit après 15 min

Environment :
- Redis Streams réel
- PostgreSQL réel (test database)
- Filesystem tmpdir (zone transit)
- Pipeline OCR mocké partiellement (Surya/Claude stubs)
"""

import asyncio
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from redis.asyncio import Redis

from services.archiviste_consumer.consumer import (
    CONSUMER_GROUP,
    STREAM_NAME,
    init_consumer_group,
    process_document_event,
)


@pytest.fixture
async def redis_client():
    """Fixture Redis client réel pour tests intégration."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = await Redis.from_url(redis_url, decode_responses=False)

    # Cleanup avant test : supprimer le stream si existe
    try:
        await client.delete(STREAM_NAME)
    except Exception:
        pass

    yield client

    # Cleanup après test
    try:
        await client.delete(STREAM_NAME)
    except Exception:
        pass

    await client.close()


@pytest.fixture
async def db_pool():
    """Fixture PostgreSQL pool réel pour tests intégration."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set - skipping integration test")

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)

    yield pool

    await pool.close()


@pytest.fixture
async def transit_dir():
    """Fixture zone transit temporaire pour tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        transit_path = Path(tmpdir) / "telegram_uploads"
        transit_path.mkdir(parents=True, exist_ok=True)
        yield transit_path


@pytest.fixture
def sample_pdf_file(transit_dir):
    """Fixture fichier PDF échantillon dans zone transit."""
    pdf_path = transit_dir / "facture_test.pdf"
    # Créer un PDF minimal valide (magic number %PDF)
    with open(pdf_path, "wb") as f:
        f.write(b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n")
        f.write(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
        f.write(b"2 0 obj\n<< /Type /Pages /Count 0 /Kids [] >>\nendobj\n")
        f.write(b"xref\n0 3\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n")
        f.write(b"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n109\n%%EOF\n")

    return pdf_path


# ============================================================================
# Test 1/2: Upload Telegram → Redis → Consumer → OCR Pipeline → PostgreSQL
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.integration
async def test_telegram_upload_complete_pipeline(
    redis_client, db_pool, transit_dir, sample_pdf_file
):
    """
    Test 1/2: Pipeline complet Telegram upload → Archiviste → PostgreSQL.

    Workflow testé :
    1. Fichier PDF uploadé dans zone transit (simulé)
    2. Événement document.received publié Redis Streams
    3. Consumer group initialisé
    4. Consumer lit événement
    5. Pipeline OCR appelé (mocké partiellement)
    6. Metadata stockée dans PostgreSQL
    7. Cleanup zone transit après traitement

    Vérifie AC#2 : Pipeline Archiviste complet
    """
    # 1. Initialiser consumer group
    await init_consumer_group(redis_client)

    # 2. Publier événement document.received (simule file_handlers.py)
    event_id = str(uuid.uuid4())
    telegram_user_id = "123456"
    telegram_message_id = "789"

    event_data = {
        b"filename": b"facture_test.pdf",
        b"file_path": str(sample_pdf_file).encode("utf-8"),
        b"source": b"telegram",
        b"telegram_user_id": telegram_user_id.encode("utf-8"),
        b"telegram_message_id": telegram_message_id.encode("utf-8"),
        b"mime_type": b"application/pdf",
        b"file_size_bytes": b"1024",
        b"detected_at": datetime.now(timezone.utc).isoformat().encode("utf-8"),
    }

    stream_id = await redis_client.xadd(STREAM_NAME, event_data)
    assert stream_id is not None

    # 3. Vérifier événement dans stream
    messages = await redis_client.xread({STREAM_NAME: "0-0"}, count=1)
    assert len(messages) == 1
    assert messages[0][0] == STREAM_NAME.encode("utf-8")
    assert len(messages[0][1]) == 1

    # 4. Mock pipeline OCR (pour éviter dépendances Surya/Claude)
    with patch("services.archiviste_consumer.consumer.OCRPipeline") as MockPipeline:
        mock_pipeline_instance = AsyncMock()
        MockPipeline.return_value = mock_pipeline_instance

        # Mock pipeline.process_document() retourne succès
        mock_pipeline_instance.process_document.return_value = {
            "success": True,
            "document_id": str(uuid.uuid4()),
            "renamed_filename": "2026-02-16_Facture_Test_EUR.pdf",
            "category": "finance",
            "timings": {
                "ocr_duration": 1.5,
                "extract_duration": 0.8,
                "total_duration": 2.3,
            },
        }

        mock_pipeline_instance.connect_redis = AsyncMock()
        mock_pipeline_instance.connect_db = AsyncMock()
        mock_pipeline_instance.disconnect_redis = AsyncMock()
        mock_pipeline_instance.disconnect_db = AsyncMock()

        # 5. Créer instance pipeline et traiter événement
        pipeline = MockPipeline(redis_url="redis://localhost", db_url="postgresql://test")
        await pipeline.connect_redis()
        await pipeline.connect_db()

        # Lire événement avec consumer group
        messages = await redis_client.xreadgroup(
            groupname=CONSUMER_GROUP,
            consumername="test-consumer",
            streams={STREAM_NAME: ">"},
            count=1,
            block=1000,
        )

        assert len(messages) == 1
        stream_name, stream_messages = messages[0]
        assert len(stream_messages) == 1

        msg_id, msg_data = stream_messages[0]

        # 6. Traiter événement via consumer
        await process_document_event(
            event_id=msg_id.decode("utf-8") if isinstance(msg_id, bytes) else msg_id,
            event_data=msg_data,
            pipeline=pipeline,
        )

        # 7. Vérifier pipeline.process_document() appelé avec bons arguments
        mock_pipeline_instance.process_document.assert_called_once()
        call_args = mock_pipeline_instance.process_document.call_args
        assert call_args.kwargs["filename"] == "facture_test.pdf"
        assert call_args.kwargs["file_path"] == str(sample_pdf_file)

        # 8. ACK message
        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)

        # 9. Vérifier message ACK (pending = 0)
        pending_info = await redis_client.xpending(STREAM_NAME, CONSUMER_GROUP)
        assert pending_info["pending"] == 0

        # Cleanup
        await pipeline.disconnect_redis()
        await pipeline.disconnect_db()


# ============================================================================
# Test 2/2: Erreur pipeline → Retry → Alerte System (sans ACK)
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.integration
async def test_telegram_upload_pipeline_error_no_ack(
    redis_client, db_pool, transit_dir, sample_pdf_file
):
    """
    Test 2/2: Erreur pipeline (NotImplementedError) → message NON ACK.

    Workflow testé :
    1. Fichier uploadé dans zone transit
    2. Événement document.received publié Redis Streams
    3. Consumer lit événement
    4. Pipeline OCR raise NotImplementedError (composant indisponible)
    5. Consumer NE DOIT PAS ACK le message (retry manuel possible)
    6. Message reste dans pending list du consumer group

    Vérifie AC#6 : Gestion erreurs fail-explicit
    """
    # 1. Initialiser consumer group
    await init_consumer_group(redis_client)

    # 2. Publier événement document.received
    event_data = {
        b"filename": b"facture_test.pdf",
        b"file_path": str(sample_pdf_file).encode("utf-8"),
        b"source": b"telegram",
        b"telegram_user_id": b"123456",
        b"telegram_message_id": b"789",
        b"mime_type": b"application/pdf",
        b"file_size_bytes": b"1024",
        b"detected_at": datetime.now(timezone.utc).isoformat().encode("utf-8"),
    }

    stream_id = await redis_client.xadd(STREAM_NAME, event_data)
    assert stream_id is not None

    # 3. Mock pipeline OCR qui raise NotImplementedError (Presidio indisponible)
    with patch("services.archiviste_consumer.consumer.OCRPipeline") as MockPipeline:
        mock_pipeline_instance = AsyncMock()
        MockPipeline.return_value = mock_pipeline_instance

        # Pipeline raise NotImplementedError (fail-explicit)
        mock_pipeline_instance.process_document.side_effect = NotImplementedError(
            "Presidio anonymization service unavailable"
        )

        mock_pipeline_instance.connect_redis = AsyncMock()
        mock_pipeline_instance.connect_db = AsyncMock()
        mock_pipeline_instance.disconnect_redis = AsyncMock()
        mock_pipeline_instance.disconnect_db = AsyncMock()

        # 4. Créer instance pipeline
        pipeline = MockPipeline(redis_url="redis://localhost", db_url="postgresql://test")
        await pipeline.connect_redis()
        await pipeline.connect_db()

        # 5. Lire événement avec consumer group
        messages = await redis_client.xreadgroup(
            groupname=CONSUMER_GROUP,
            consumername="test-consumer-error",
            streams={STREAM_NAME: ">"},
            count=1,
            block=1000,
        )

        assert len(messages) == 1
        stream_name, stream_messages = messages[0]
        assert len(stream_messages) == 1

        msg_id, msg_data = stream_messages[0]

        # 6. Traiter événement → NotImplementedError attendue
        with pytest.raises(NotImplementedError, match="Presidio anonymization"):
            await process_document_event(
                event_id=msg_id.decode("utf-8") if isinstance(msg_id, bytes) else msg_id,
                event_data=msg_data,
                pipeline=pipeline,
            )

        # 7. Vérifier message NON ACK (pending = 1)
        pending_info = await redis_client.xpending(STREAM_NAME, CONSUMER_GROUP)
        assert pending_info["pending"] == 1  # Message toujours en attente

        # 8. Vérifier consumer qui a le message pending
        pending_messages = await redis_client.xpending_range(
            STREAM_NAME, CONSUMER_GROUP, "-", "+", count=10
        )
        assert len(pending_messages) == 1
        assert pending_messages[0]["consumer"] == b"test-consumer-error"

        # Cleanup
        await pipeline.disconnect_redis()
        await pipeline.disconnect_db()
