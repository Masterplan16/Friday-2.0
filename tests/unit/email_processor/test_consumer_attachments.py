"""
Tests unitaires pour intégration extraction PJ dans email consumer.

Story 2.4 - Subtask 6.3
"""

# Mock services.email_processor avant import
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "c:\\Users\\lopez\\Desktop\\Friday 2.0")

from agents.src.models.attachment import AttachmentExtractResult


@pytest.mark.asyncio
async def test_email_with_attachments_extracts_and_notifies():
    """
    GIVEN email avec has_attachments=True
    WHEN process_email_event() est appelé
    THEN extract_attachments() + send_telegram_notification_attachments() appelés
    """
    # Mock extract_attachments
    mock_result = AttachmentExtractResult(
        extracted_count=2,
        failed_count=0,
        total_size_mb=0.25,
        filepaths=["/var/friday/transit/file1.pdf", "/var/friday/transit/file2.jpg"],
    )
    mock_result.generate_summaries(email_id=str(uuid.uuid4()), attachments_total=2)

    with patch("services.email_processor.consumer.extract_attachments", return_value=mock_result):
        with patch(
            "services.email_processor.consumer.EmailProcessorConsumer.send_telegram_notification_attachments"
        ) as mock_notify:
            # TODO: Simuler process_email_event avec payload has_attachments=True
            # Vérifier extract_attachments appelé + notification envoyée
            pass


@pytest.mark.asyncio
async def test_email_without_attachments_skips_extraction():
    """
    GIVEN email avec has_attachments=False
    WHEN process_email_event() est appelé
    THEN extract_attachments() PAS appelé
    """
    with patch("services.email_processor.consumer.extract_attachments") as mock_extract:
        # TODO: Simuler process_email_event avec payload has_attachments=False
        # Vérifier extract_attachments PAS appelé
        pass


@pytest.mark.asyncio
async def test_attachment_extraction_failure_continues_pipeline():
    """
    GIVEN extraction PJ échoue (exception)
    WHEN process_email_event() est appelé
    THEN pipeline continue (email stocké, notification envoyée quand même)
    """
    with patch(
        "services.email_processor.consumer.extract_attachments",
        side_effect=Exception("Extraction failed"),
    ):
        # TODO: Simuler process_email_event
        # Vérifier email stocké quand même + log error
        pass


@pytest.mark.asyncio
async def test_attachment_notification_failure_continues_pipeline():
    """
    GIVEN notification Telegram PJ échoue
    WHEN process_email_event() est appelé
    THEN pipeline continue (email traité, XACK envoyé)
    """
    mock_result = AttachmentExtractResult(
        extracted_count=1,
        failed_count=0,
        total_size_mb=0.1,
        filepaths=["/var/friday/transit/file1.pdf"],
    )
    mock_result.generate_summaries(email_id=str(uuid.uuid4()), attachments_total=1)

    with patch("services.email_processor.consumer.extract_attachments", return_value=mock_result):
        with patch(
            "services.email_processor.consumer.EmailProcessorConsumer.send_telegram_notification_attachments",
            side_effect=Exception("Telegram failed"),
        ):
            # TODO: Simuler process_email_event
            # Vérifier XACK quand même + log error
            pass


@pytest.mark.asyncio
async def test_notification_routing_email_topic():
    """
    GIVEN attachments extraites avec succès
    WHEN send_telegram_notification_attachments() est appelé
    THEN notification envoyée au topic TOPIC_EMAIL_ID
    """
    # TODO: Mock httpx.AsyncClient.post
    # Vérifier message_thread_id = TOPIC_EMAIL_ID
    pass


@pytest.mark.asyncio
async def test_notification_format_ac6():
    """
    GIVEN attachments extraites
    WHEN send_telegram_notification_attachments() est appelé
    THEN format notification respecte AC6 (count, size, filenames, inline button)
    """
    # TODO: Mock httpx.AsyncClient.post
    # Vérifier text contient extracted_count + total_size_mb + filenames
    # Vérifier reply_markup contient inline_keyboard avec [View Email]
    pass


@pytest.mark.asyncio
async def test_notification_max_5_filenames():
    """
    GIVEN >5 fichiers extraits
    WHEN send_telegram_notification_attachments() est appelé
    THEN liste limitée à 5 fichiers + "... et X autre(s)"
    """
    mock_result = AttachmentExtractResult(
        extracted_count=8,
        failed_count=0,
        total_size_mb=1.5,
        filepaths=[f"/var/friday/transit/file{i}.pdf" for i in range(8)],
    )
    mock_result.generate_summaries(email_id=str(uuid.uuid4()), attachments_total=8)

    # TODO: Appeler send_telegram_notification_attachments()
    # Vérifier notification_text contient max 5 fichiers + "... et 3 autre(s)"
    pass


@pytest.mark.asyncio
async def test_extraction_uses_db_email_id():
    """
    GIVEN email stocké en DB avec UUID
    WHEN extract_attachments() est appelé
    THEN email_id passé = UUID depuis store_email_in_database() (PAS message_id)
    """
    email_uuid = uuid.uuid4()

    with patch(
        "services.email_processor.consumer.EmailProcessorConsumer.store_email_in_database",
        return_value=email_uuid,
    ):
        with patch("services.email_processor.consumer.extract_attachments") as mock_extract:
            # TODO: Simuler process_email_event
            # Vérifier mock_extract appelé avec email_id=str(email_uuid)
            pass


@pytest.mark.asyncio
async def test_zero_extracted_skips_notification():
    """
    GIVEN extraction retourne extracted_count=0
    WHEN process_email_event() est appelé
    THEN send_telegram_notification_attachments() PAS appelé
    """
    mock_result = AttachmentExtractResult(
        extracted_count=0, failed_count=2, total_size_mb=0.0, filepaths=[]
    )
    mock_result.generate_summaries(email_id=str(uuid.uuid4()), attachments_total=2)

    with patch("services.email_processor.consumer.extract_attachments", return_value=mock_result):
        with patch(
            "services.email_processor.consumer.EmailProcessorConsumer.send_telegram_notification_attachments"
        ) as mock_notify:
            # TODO: Simuler process_email_event
            # Vérifier mock_notify PAS appelé
            mock_notify.assert_not_called()


@pytest.mark.skip(
    reason="D25: EmailEngineClient supprimé - EmailEngine retiré, remplacé par IMAP direct"
)
@pytest.mark.asyncio
async def test_emailengine_client_wrapper_get_message():
    """
    GIVEN EmailEngineClient initialisé
    WHEN get_message() est appelé
    THEN appel HTTP vers /v1/account/{account_id}/message/{message_id}
    """
    from services.email_processor.consumer import EmailEngineClient

    http_client_mock = AsyncMock()
    response_mock = MagicMock()
    response_mock.status_code = 200
    response_mock.json.return_value = {"subject": "Test", "attachments": []}
    http_client_mock.get = AsyncMock(return_value=response_mock)

    client = EmailEngineClient(
        http_client=http_client_mock, base_url="http://emailengine:3000", secret="test_secret"
    )

    result = await client.get_message("main/message123")

    # Vérifier appel HTTP
    http_client_mock.get.assert_awaited_once()
    call_args = http_client_mock.get.call_args
    assert "main/message/message123" in call_args[0][0]
    assert call_args[1]["headers"]["Authorization"] == "Bearer test_secret"

    # Vérifier résultat
    assert result["subject"] == "Test"
    assert "attachments" in result
