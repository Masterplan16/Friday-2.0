"""
Tests intégration upload fichiers Telegram (Story 3.6 Task 7.2).

Tests pipeline complet :
- Telegram upload → zone transit VPS
- Redis Streams event publié
- Consumer traite événement

Environment :
- Redis Streams réel
- Filesystem tmpdir (zone transit simulée)
- Mocks : Telegram Bot API, PostgreSQL

Ces tests vérifient AC#1 : Upload automatique avec validation.
"""

import asyncio
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.asyncio import Redis

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def redis_client():
    """Fixture Redis client réel pour tests intégration."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = await Redis.from_url(redis_url, decode_responses=False)

    # Cleanup avant test
    stream_name = "document.received"
    try:
        await client.delete(stream_name)
    except Exception:
        pass

    yield client

    # Cleanup après test
    try:
        await client.delete(stream_name)
    except Exception:
        pass

    await client.close()


@pytest.fixture
def transit_dir():
    """Fixture zone transit temporaire."""
    with tempfile.TemporaryDirectory() as tmpdir:
        transit_path = Path(tmpdir) / "telegram_uploads"
        transit_path.mkdir(parents=True, exist_ok=True)
        yield transit_path


@pytest.fixture
def mock_telegram_update():
    """Fixture Update Telegram mocké avec document PDF."""
    from telegram import Update, Message, User, Document as TelegramDocument

    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 123456
    update.effective_user.username = "mainteneur"

    update.message = MagicMock(spec=Message)
    update.message.reply_text = AsyncMock()
    update.message.chat_id = -1001234567890
    update.message.message_thread_id = 100  # Topic Email & Communications

    # Document PDF
    update.message.document = MagicMock(spec=TelegramDocument)
    update.message.document.file_id = "test_file_id_pdf"
    update.message.document.file_name = "facture_test.pdf"
    update.message.document.mime_type = "application/pdf"
    update.message.document.file_size = 512 * 1024  # 512 KB

    return update


@pytest.fixture
def mock_telegram_context():
    """Fixture Context Telegram mocké."""
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.get_file = AsyncMock()
    return context


# ============================================================================
# Test 1/5: Upload PDF → Redis Streams event publié
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_pdf_to_redis_streams(
    redis_client, transit_dir, mock_telegram_update, mock_telegram_context
):
    """
    Test 1/5: Upload PDF → event Redis Streams publié avec metadata complète.

    Vérifie que :
    - Fichier téléchargé dans zone transit
    - Event `document.received` publié dans Redis
    - Metadata complète (filename, file_path, source, user_id, mime_type, size)
    - Notification utilisateur envoyée
    """
    from bot.handlers.file_handlers import handle_document

    # Mock file download
    test_file = transit_dir / "facture_test.pdf"
    test_file.write_bytes(b"%PDF-1.4\ntest content")

    mock_file = MagicMock()
    mock_file.download_to_drive = AsyncMock(side_effect=lambda path: test_file.write_bytes(b"%PDF-1.4\ntest"))
    mock_telegram_context.bot.get_file.return_value = mock_file

    # Ajouter Redis client au context
    mock_telegram_context.bot_data = {"redis_client": redis_client}

    # Mock TRANSIT_DIR pour utiliser tmpdir
    with patch("bot.handlers.file_handlers.TRANSIT_DIR", transit_dir):
        # Execute handler
        await handle_document(mock_telegram_update, mock_telegram_context)

        # Verify Redis event publié
        messages = await redis_client.xread({"document.received": "0-0"}, count=1)
        assert len(messages) == 1
        assert messages[0][0] == b"document.received"

        event_id, event_data = messages[0][1][0]

        # Verify event data
        assert event_data[b"filename"] == b"facture_test.pdf"
        assert event_data[b"source"] == b"telegram"
        assert event_data[b"telegram_user_id"] == b"123456"
        assert event_data[b"mime_type"] == b"application/pdf"
        assert event_data[b"file_size_bytes"] == b"524288"

        # Verify file_path présent
        assert b"file_path" in event_data
        file_path = event_data[b"file_path"].decode("utf-8")
        assert "facture_test.pdf" in file_path

        # Verify notification envoyée
        mock_telegram_update.message.reply_text.assert_called_once()


# ============================================================================
# Test 2/5: Upload JPG photo → Redis event publié
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_photo_jpg_to_redis_streams(redis_client, transit_dir):
    """
    Test 2/5: Upload photo JPG → event Redis avec MIME image/jpeg.

    Vérifie que :
    - Photo extraite (largest size)
    - Extension .jpg ajoutée automatiquement
    - Event publié avec mime_type=image/jpeg
    """
    from bot.handlers.file_handlers import handle_photo
    from telegram import Update, Message, User, PhotoSize

    # Mock Update avec photo
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 123456

    update.message = MagicMock(spec=Message)
    update.message.reply_text = AsyncMock()
    update.message.chat_id = -1001234567890
    update.message.message_thread_id = 100

    photo_size = MagicMock(spec=PhotoSize)
    photo_size.file_id = "test_photo_id"
    photo_size.file_size = 100 * 1024  # 100 KB
    update.message.photo = [photo_size]

    # Mock context
    context = MagicMock()
    context.bot = MagicMock()

    test_file = transit_dir / "photo_test.jpg"
    test_file.write_bytes(b"\xff\xd8\xff\xe0")  # JPEG magic number

    mock_file = MagicMock()
    mock_file.download_to_drive = AsyncMock(side_effect=lambda path: test_file.write_bytes(b"\xff\xd8\xff\xe0"))
    context.bot.get_file.return_value = mock_file

    context.bot_data = {"redis_client": redis_client}

    # Execute handler
    with patch("bot.handlers.file_handlers.TRANSIT_DIR", transit_dir):
        await handle_photo(update, context)

        # Verify Redis event
        messages = await redis_client.xread({"document.received": "0-0"}, count=1)
        assert len(messages) == 1

        event_data = messages[0][1][0][1]
        assert event_data[b"mime_type"] == b"image/jpeg"
        assert b".jpg" in event_data[b"filename"]


# ============================================================================
# Test 3/5: Upload batch 5 fichiers → 5 events Redis
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_batch_5_files(redis_client, transit_dir, mock_telegram_context):
    """
    Test 3/5: Upload 5 fichiers simultanés → 5 events Redis distincts.

    Vérifie que :
    - Rate limiter permet 5 fichiers (< limite 20/min)
    - 5 events Redis publiés avec IDs uniques
    - Aucun event perdu
    """
    from bot.handlers.file_handlers import handle_document, file_upload_limiter
    from telegram import Update, Message, User, Document as TelegramDocument

    # Reset rate limiter
    file_upload_limiter.call_history.clear()

    mock_telegram_context.bot_data = {"redis_client": redis_client}

    # Mock file download
    test_file = transit_dir / "test.pdf"
    test_file.write_bytes(b"%PDF-1.4\ntest")

    mock_file = MagicMock()
    mock_file.download_to_drive = AsyncMock()
    mock_telegram_context.bot.get_file.return_value = mock_file

    # Upload 5 fichiers
    filenames = []
    with patch("bot.handlers.file_handlers.TRANSIT_DIR", transit_dir):
        for i in range(5):
            filename = f"fichier_{i+1}.pdf"
            filenames.append(filename)

            # Create update
            update = MagicMock(spec=Update)
            update.effective_user = MagicMock(spec=User)
            update.effective_user.id = 123456

            update.message = MagicMock(spec=Message)
            update.message.reply_text = AsyncMock()
            update.message.chat_id = -1001234567890
            update.message.message_thread_id = 100

            update.message.document = MagicMock(spec=TelegramDocument)
            update.message.document.file_id = f"file_id_{i}"
            update.message.document.file_name = filename
            update.message.document.mime_type = "application/pdf"
            update.message.document.file_size = 100 * 1024

            await handle_document(update, mock_telegram_context)

        # Verify 5 events dans Redis
        messages = await redis_client.xread({"document.received": "0-0"}, count=10)
        assert len(messages) == 1
        assert len(messages[0][1]) == 5  # 5 events

        # Verify tous les filenames présents
        event_filenames = [msg[1][b"filename"].decode("utf-8") for msg in messages[0][1]]
        for filename in filenames:
            assert filename in event_filenames


# ============================================================================
# Test 4/5: Échec téléchargement → retry 3× → succès
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_failure_retry_success(
    redis_client, transit_dir, mock_telegram_update, mock_telegram_context
):
    """
    Test 4/5: Téléchargement échoue 2×, réussit au 3ème essai.

    Vérifie que :
    - Retry backoff exponentiel (1s, 2s)
    - 3ème tentative réussit
    - Event Redis publié après succès
    """
    from bot.handlers.file_handlers import handle_document

    test_file = transit_dir / "facture_test.pdf"
    test_file.write_bytes(b"%PDF-1.4\ntest")

    # Mock download : 2 échecs puis succès
    call_count = 0

    async def mock_download_side_effect(path):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Exception("Network timeout")
        # 3ème tentative : succès
        test_file.write_bytes(b"%PDF-1.4\ntest")

    mock_file = MagicMock()
    mock_file.download_to_drive = AsyncMock(side_effect=mock_download_side_effect)
    mock_telegram_context.bot.get_file.return_value = mock_file

    mock_telegram_context.bot_data = {"redis_client": redis_client}

    # Execute handler avec retry
    with patch("bot.handlers.file_handlers.TRANSIT_DIR", transit_dir):
        await handle_document(mock_telegram_update, mock_telegram_context)

        # Verify 3 tentatives
        assert call_count == 3

        # Verify event Redis publié après succès
        messages = await redis_client.xread({"document.received": "0-0"}, count=1)
        assert len(messages) == 1


# ============================================================================
# Test 5/5: MIME type invalide → rejeté, aucun event Redis
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_invalid_mime_type(redis_client, mock_telegram_update, mock_telegram_context):
    """
    Test 5/5: Fichier .exe rejeté → aucun event Redis.

    Vérifie que :
    - Extension .exe détectée et rejetée
    - Aucun téléchargement effectué
    - Aucun event Redis publié
    - Notification erreur envoyée
    """
    from bot.handlers.file_handlers import handle_document

    # Change extension to .exe
    mock_telegram_update.message.document.file_name = "virus.exe"
    mock_telegram_update.message.document.mime_type = "application/x-msdownload"

    mock_telegram_context.bot_data = {"redis_client": redis_client}

    # Execute handler
    await handle_document(mock_telegram_update, mock_telegram_context)

    # Verify aucun download
    mock_telegram_context.bot.get_file.assert_not_called()

    # Verify aucun event Redis
    messages = await redis_client.xread({"document.received": "0-0"}, count=1)
    assert len(messages) == 0 or len(messages[0][1]) == 0

    # Verify notification erreur
    mock_telegram_update.message.reply_text.assert_called_once()
    reply_text = mock_telegram_update.message.reply_text.call_args[0][0]
    assert "❌" in reply_text or "non supporté" in reply_text.lower()
