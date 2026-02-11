"""
Tests unitaires pour publication événements document.received avec retry logic.

Story 2.4 - Subtask 4.2
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agents.src.agents.email.attachment_extractor import _publish_document_received


@pytest.mark.asyncio
async def test_publish_success():
    """
    GIVEN un attachment valide et un client Redis mock
    WHEN _publish_document_received() est appelé
    THEN événement publié dans documents:received avec payload complet
    """
    redis_mock = AsyncMock()
    redis_mock.xadd = AsyncMock(return_value=b"1234567890-0")

    attachment_id = str(uuid.uuid4())
    email_id = str(uuid.uuid4())

    await _publish_document_received(
        attachment_id=attachment_id,
        email_id=email_id,
        filename="facture.pdf",
        filepath="/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf",
        mime_type="application/pdf",
        size_bytes=150000,
        redis_client=redis_mock,
    )

    # Vérifier appel xadd
    redis_mock.xadd.assert_awaited_once()

    call_args = redis_mock.xadd.call_args
    assert call_args[0][0] == "documents:received"
    assert call_args[1]["maxlen"] == 10000

    # Vérifier payload
    payload = call_args[0][1]
    assert payload["attachment_id"] == attachment_id
    assert payload["email_id"] == email_id
    assert payload["filename"] == "facture.pdf"
    assert payload["filepath"] == "/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf"
    assert payload["mime_type"] == "application/pdf"
    assert payload["size_bytes"] == "150000"  # Converti en string
    assert payload["source"] == "email"


@pytest.mark.asyncio
async def test_publish_retry_succeeds_on_2nd_attempt():
    """
    GIVEN Redis échoue 1x puis succède
    WHEN _publish_document_received() est appelé
    THEN retry après 1s et succès sur 2ème tentative
    """
    redis_mock = AsyncMock()
    redis_mock.xadd = AsyncMock(
        side_effect=[
            Exception("Connection timeout"),  # 1er essai échoue
            b"1234567890-0",  # 2ème essai succède
        ]
    )

    attachment_id = str(uuid.uuid4())
    email_id = str(uuid.uuid4())

    # Mock time.sleep pour éviter attente réelle
    with patch("tenacity.nap.sleep", return_value=None):
        await _publish_document_received(
            attachment_id=attachment_id,
            email_id=email_id,
            filename="facture.pdf",
            filepath="/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf",
            mime_type="application/pdf",
            size_bytes=150000,
            redis_client=redis_mock,
        )

    # Vérifier 2 appels xadd (1 échec + 1 succès)
    assert redis_mock.xadd.await_count == 2


@pytest.mark.asyncio
async def test_publish_retry_succeeds_on_3rd_attempt():
    """
    GIVEN Redis échoue 2x puis succède
    WHEN _publish_document_received() est appelé
    THEN retry après 1s, 2s et succès sur 3ème tentative
    """
    redis_mock = AsyncMock()
    redis_mock.xadd = AsyncMock(
        side_effect=[
            Exception("Connection timeout"),  # 1er essai échoue
            Exception("Connection timeout"),  # 2ème essai échoue
            b"1234567890-0",  # 3ème essai succède
        ]
    )

    attachment_id = str(uuid.uuid4())
    email_id = str(uuid.uuid4())

    with patch("tenacity.nap.sleep", return_value=None):
        await _publish_document_received(
            attachment_id=attachment_id,
            email_id=email_id,
            filename="facture.pdf",
            filepath="/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf",
            mime_type="application/pdf",
            size_bytes=150000,
            redis_client=redis_mock,
        )

    # Vérifier 3 appels xadd (2 échecs + 1 succès)
    assert redis_mock.xadd.await_count == 3


@pytest.mark.asyncio
async def test_publish_fails_after_3_attempts():
    """
    GIVEN Redis échoue 3x
    WHEN _publish_document_received() est appelé
    THEN raise Exception après 3 tentatives (1 original + 2 retries)
    """
    redis_mock = AsyncMock()
    redis_mock.xadd = AsyncMock(
        side_effect=Exception("Redis connection failed permanently")
    )

    attachment_id = str(uuid.uuid4())
    email_id = str(uuid.uuid4())

    with patch("tenacity.nap.sleep", return_value=None):
        with pytest.raises(Exception, match="Redis connection failed permanently"):
            await _publish_document_received(
                attachment_id=attachment_id,
                email_id=email_id,
                filename="facture.pdf",
                filepath="/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf",
                mime_type="application/pdf",
                size_bytes=150000,
                redis_client=redis_mock,
            )

    # Vérifier 3 tentatives
    assert redis_mock.xadd.await_count == 3


@pytest.mark.asyncio
async def test_payload_validation_all_fields():
    """
    GIVEN tous les champs payload fournis
    WHEN _publish_document_received() est appelé
    THEN payload contient 7 champs obligatoires
    """
    redis_mock = AsyncMock()
    redis_mock.xadd = AsyncMock(return_value=b"1234567890-0")

    attachment_id = str(uuid.uuid4())
    email_id = str(uuid.uuid4())

    await _publish_document_received(
        attachment_id=attachment_id,
        email_id=email_id,
        filename="photo.jpg",
        filepath="/var/friday/transit/attachments/2026-02-11/456_1_photo.jpg",
        mime_type="image/jpeg",
        size_bytes=2048000,
        redis_client=redis_mock,
    )

    payload = redis_mock.xadd.call_args[0][1]

    # Vérifier tous les champs présents
    assert "attachment_id" in payload
    assert "email_id" in payload
    assert "filename" in payload
    assert "filepath" in payload
    assert "mime_type" in payload
    assert "size_bytes" in payload
    assert "source" in payload

    # Vérifier valeurs exactes
    assert payload["attachment_id"] == attachment_id
    assert payload["email_id"] == email_id
    assert payload["filename"] == "photo.jpg"
    assert payload["filepath"] == "/var/friday/transit/attachments/2026-02-11/456_1_photo.jpg"
    assert payload["mime_type"] == "image/jpeg"
    assert payload["size_bytes"] == "2048000"
    assert payload["source"] == "email"


@pytest.mark.asyncio
async def test_maxlen_enforcement():
    """
    GIVEN publication dans Redis Streams
    WHEN _publish_document_received() est appelé
    THEN xadd appelé avec maxlen=10000
    """
    redis_mock = AsyncMock()
    redis_mock.xadd = AsyncMock(return_value=b"1234567890-0")

    attachment_id = str(uuid.uuid4())
    email_id = str(uuid.uuid4())

    await _publish_document_received(
        attachment_id=attachment_id,
        email_id=email_id,
        filename="facture.pdf",
        filepath="/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf",
        mime_type="application/pdf",
        size_bytes=150000,
        redis_client=redis_mock,
    )

    # Vérifier maxlen=10000
    call_kwargs = redis_mock.xadd.call_args[1]
    assert "maxlen" in call_kwargs
    assert call_kwargs["maxlen"] == 10000


@pytest.mark.asyncio
async def test_stream_name_documents_received():
    """
    GIVEN publication événement
    WHEN _publish_document_received() est appelé
    THEN stream name = 'documents:received'
    """
    redis_mock = AsyncMock()
    redis_mock.xadd = AsyncMock(return_value=b"1234567890-0")

    attachment_id = str(uuid.uuid4())
    email_id = str(uuid.uuid4())

    await _publish_document_received(
        attachment_id=attachment_id,
        email_id=email_id,
        filename="facture.pdf",
        filepath="/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf",
        mime_type="application/pdf",
        size_bytes=150000,
        redis_client=redis_mock,
    )

    # Vérifier stream name
    stream_name = redis_mock.xadd.call_args[0][0]
    assert stream_name == "documents:received"


@pytest.mark.asyncio
async def test_size_bytes_converted_to_string():
    """
    GIVEN size_bytes = int
    WHEN _publish_document_received() est appelé
    THEN payload['size_bytes'] = string (Redis Streams stocke strings)
    """
    redis_mock = AsyncMock()
    redis_mock.xadd = AsyncMock(return_value=b"1234567890-0")

    attachment_id = str(uuid.uuid4())
    email_id = str(uuid.uuid4())

    await _publish_document_received(
        attachment_id=attachment_id,
        email_id=email_id,
        filename="facture.pdf",
        filepath="/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf",
        mime_type="application/pdf",
        size_bytes=150000,  # int
        redis_client=redis_mock,
    )

    payload = redis_mock.xadd.call_args[0][1]

    # Vérifier conversion int → string
    assert isinstance(payload["size_bytes"], str)
    assert payload["size_bytes"] == "150000"
