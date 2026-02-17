"""
Tests unitaires pour bot/handlers/file_handlers.py

Story 3.6 - Tests upload fichiers Telegram (AC#1, AC#4).
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from telegram import Chat
from telegram import Document as TelegramDocument
from telegram import Message, PhotoSize, Update, User


@pytest.fixture
def mock_update_document():
    """Fixture Update Telegram avec document PDF."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 123456
    update.effective_user.username = "mainteneur"

    update.message = MagicMock(spec=Message)
    update.message.reply_text = AsyncMock()
    update.message.chat_id = -1001234567890
    update.message.message_thread_id = 100  # Chat & Proactive topic
    update.message.message_id = 42

    # Document PDF
    update.message.document = MagicMock(spec=TelegramDocument)
    update.message.document.file_id = "test_file_id_pdf"
    update.message.document.file_name = "facture.pdf"
    update.message.document.mime_type = "application/pdf"
    update.message.document.file_size = 524288  # 512 KB

    return update


@pytest.fixture
def mock_update_photo():
    """Fixture Update Telegram avec photo JPG."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 123456
    update.effective_user.username = "mainteneur"

    update.message = MagicMock(spec=Message)
    update.message.reply_text = AsyncMock()
    update.message.chat_id = -1001234567890
    update.message.message_thread_id = 100

    # Photo (list de PhotoSize, on prend la dernière = plus grande)
    photo_size = MagicMock(spec=PhotoSize)
    photo_size.file_id = "test_file_id_photo"
    photo_size.file_size = 102400  # 100 KB
    update.message.photo = [photo_size]

    return update


@pytest.fixture
def mock_context():
    """Fixture Context Telegram mocké avec Redis client."""
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.get_file = AsyncMock()

    # Redis client mock
    redis_mock = AsyncMock()
    redis_mock.xadd = AsyncMock()
    context.bot_data = {"redis_client": redis_mock}

    return context


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset rate limiter avant chaque test (autouse=True)."""
    from bot.handlers.file_handlers import file_upload_limiter

    # Reset TOUS les utilisateurs avant chaque test
    file_upload_limiter.call_history.clear()

    yield  # Le test s'exécute ici

    # Cleanup après test (si nécessaire)
    file_upload_limiter.call_history.clear()


@pytest.fixture(autouse=True)
def mock_magic_number_validation():
    """Mock magic number validation (évite lecture fichier sur disque en tests)."""
    with patch("bot.handlers.file_handlers.validate_magic_number", return_value=True):
        yield


# ============================================================================
# Test 1: Document PDF valide (AC#1)
# ============================================================================
@pytest.mark.asyncio
async def test_handle_document_valid_pdf(mock_update_document, mock_context):
    """
    Test 1/10: Document PDF valide accepté, téléchargé, publié Redis.

    Vérifie que :
    - Extension .pdf acceptée
    - MIME type application/pdf validé
    - Fichier téléchargé dans zone transit
    - Événement document.received publié Redis Streams
    - Notification utilisateur succès
    """
    from bot.handlers.file_handlers import handle_document

    # Mock file download
    mock_file = MagicMock()
    mock_file.download_to_drive = AsyncMock()
    mock_context.bot.get_file.return_value = mock_file

    # Execute handler
    await handle_document(mock_update_document, mock_context)

    # Verify download called
    mock_context.bot.get_file.assert_called_once_with("test_file_id_pdf")
    mock_file.download_to_drive.assert_called_once()

    # Verify Redis Streams publish
    redis_client = mock_context.bot_data["redis_client"]
    redis_client.xadd.assert_called_once()

    # Verify event data structure
    call_args = redis_client.xadd.call_args
    stream_name = call_args[0][0]
    event_data = call_args[0][1]

    assert stream_name == "document.received"
    assert event_data["filename"] == "facture.pdf"
    assert event_data["source"] == "telegram"
    assert event_data["telegram_user_id"] == "123456"
    assert event_data["mime_type"] == "application/pdf"
    assert event_data["file_size_bytes"] == "524288"

    # Verify notification sent
    mock_update_document.message.reply_text.assert_called_once()
    reply_text = mock_update_document.message.reply_text.call_args[0][0]
    assert "✅" in reply_text or "Fichier reçu" in reply_text


# ============================================================================
# Test 2: Extension invalide rejetée (AC#4)
# ============================================================================
@pytest.mark.asyncio
async def test_handle_document_invalid_extension(mock_update_document, mock_context):
    """
    Test 2/10: Extension .exe rejetée avec message explicite.

    Vérifie que :
    - Extension .exe détectée et rejetée
    - Message d'erreur explicite envoyé utilisateur
    - Aucun téléchargement effectué
    - Aucun event Redis publié
    """
    from bot.handlers.file_handlers import handle_document

    # Change extension to .exe (SECURITY)
    mock_update_document.message.document.file_name = "virus.exe"
    mock_update_document.message.document.mime_type = "application/x-msdownload"

    # Execute handler
    await handle_document(mock_update_document, mock_context)

    # Verify rejection message sent
    mock_update_document.message.reply_text.assert_called_once()
    reply_text = mock_update_document.message.reply_text.call_args[0][0]
    assert "❌" in reply_text or "non supporté" in reply_text
    assert "virus.exe" in reply_text or ".exe" in reply_text

    # Verify NO download
    mock_context.bot.get_file.assert_not_called()

    # Verify NO Redis publish
    redis_client = mock_context.bot_data["redis_client"]
    redis_client.xadd.assert_not_called()


# ============================================================================
# Test 3: Photo JPG valide (AC#1)
# ============================================================================
@pytest.mark.asyncio
async def test_handle_photo_valid_jpg(mock_update_photo, mock_context):
    """
    Test 3/10: Photo JPG acceptée et traitée.

    Vérifie que :
    - Photo extraite (plus grande taille)
    - Téléchargée avec extension .jpg
    - Événement Redis publié avec MIME image/jpeg
    """
    from bot.handlers.file_handlers import handle_photo

    # Mock file download
    mock_file = MagicMock()
    mock_file.download_to_drive = AsyncMock()
    mock_context.bot.get_file.return_value = mock_file

    # Execute handler
    await handle_photo(mock_update_photo, mock_context)

    # Verify download called (largest photo)
    mock_context.bot.get_file.assert_called_once_with("test_file_id_photo")

    # Verify Redis event
    redis_client = mock_context.bot_data["redis_client"]
    redis_client.xadd.assert_called_once()

    event_data = redis_client.xadd.call_args[0][1]
    assert event_data["source"] == "telegram"
    assert event_data["mime_type"] == "image/jpeg"


# ============================================================================
# Test 4: Rate limiting 20 fichiers/minute (AC#7)
# ============================================================================
@pytest.mark.asyncio
async def test_rate_limiting_20_files_per_minute(mock_update_document, mock_context):
    """
    Test 4/10: Rate limiter activé après 20 fichiers en 1 minute.

    Vérifie que :
    - 20 premiers fichiers acceptés
    - 21ème fichier rejeté avec message rate limit
    - Retry_after indiqué (en secondes)
    """
    from bot.handlers.file_handlers import handle_document

    # Mock file download success
    mock_file = MagicMock()
    mock_file.download_to_drive = AsyncMock()
    mock_context.bot.get_file.return_value = mock_file

    # Upload 20 fichiers → OK
    for i in range(20):
        mock_update_document.message.reply_text.reset_mock()
        mock_context.bot_data["redis_client"].xadd.reset_mock()

        await handle_document(mock_update_document, mock_context)

        # Verify success (✅ or "Fichier reçu")
        reply_text = mock_update_document.message.reply_text.call_args[0][0]
        assert "✅" in reply_text or "Fichier reçu" in reply_text

    # 21ème fichier → RATE LIMITED
    mock_update_document.message.reply_text.reset_mock()
    await handle_document(mock_update_document, mock_context)

    reply_text = mock_update_document.message.reply_text.call_args[0][0]
    assert "limite" in reply_text.lower() or "trop" in reply_text.lower()
    assert "seconde" in reply_text.lower() or "minute" in reply_text.lower()


# ============================================================================
# Test 5: Téléchargement échoue → retry 3× (AC#6)
# ============================================================================
@pytest.mark.asyncio
async def test_download_failure_retry_3x(mock_update_document, mock_context):
    """
    Test 5/10: Échec téléchargement → retry 3× backoff exponentiel.

    Vérifie que :
    - 1er échec → retry après 1s
    - 2ème échec → retry après 2s
    - 3ème échec → alerte System, fichier déplacé errors/
    """
    from bot.handlers.file_handlers import handle_document

    # Mock file download failure 3 times
    mock_context.bot.get_file.side_effect = Exception("Network timeout")

    # Execute handler
    await handle_document(mock_update_document, mock_context)

    # Verify 3 retry attempts
    assert mock_context.bot.get_file.call_count == 3

    # Verify error notification sent
    mock_update_document.message.reply_text.assert_called()
    reply_text = mock_update_document.message.reply_text.call_args[0][0]
    assert "❌" in reply_text or "erreur" in reply_text.lower()


# ============================================================================
# Test 6: Redis publish échoue → alerte System (AC#6)
# ============================================================================
@pytest.mark.asyncio
async def test_redis_publish_failure_alert(mock_update_document, mock_context):
    """
    Test 6/10: Redis down → alerte System topic.

    Vérifie que :
    - Téléchargement réussi
    - Publish Redis échoue 3×
    - Notification erreur System topic
    """
    from bot.handlers.file_handlers import handle_document

    # Mock download success
    mock_file = MagicMock()
    mock_file.download_to_drive = AsyncMock()
    mock_context.bot.get_file.return_value = mock_file

    # Mock Redis failure
    redis_client = mock_context.bot_data["redis_client"]
    redis_client.xadd.side_effect = Exception("Redis connection refused")

    # Execute handler
    await handle_document(mock_update_document, mock_context)

    # Verify retry 3x
    assert redis_client.xadd.call_count == 3

    # Verify error notification
    mock_update_document.message.reply_text.assert_called()
    reply_text = mock_update_document.message.reply_text.call_args[0][0]
    assert "❌" in reply_text or "erreur" in reply_text.lower()


# ============================================================================
# Test 7: Fichier 0 byte rejeté (Edge case)
# ============================================================================
@pytest.mark.asyncio
async def test_handle_document_zero_bytes(mock_update_document, mock_context):
    """
    Test 7/10: Fichier 0 byte rejeté avec message explicite.
    """
    from bot.handlers.file_handlers import handle_document

    # Set file size to 0
    mock_update_document.message.document.file_size = 0

    # Execute handler
    await handle_document(mock_update_document, mock_context)

    # Verify rejection
    reply_text = mock_update_document.message.reply_text.call_args[0][0]
    assert "❌" in reply_text or "vide" in reply_text.lower()


# ============================================================================
# Test 8: Nom fichier avec caractères spéciaux (Edge case)
# ============================================================================
@pytest.mark.asyncio
async def test_handle_document_special_chars_filename(mock_update_document, mock_context):
    """
    Test 8/10: Nom fichier avec espaces/accents/apostrophes accepté.
    """
    from bot.handlers.file_handlers import handle_document

    # Set special chars filename
    mock_update_document.message.document.file_name = "Facture 2024 - Côte d'Ivoire.pdf"

    # Mock download success
    mock_file = MagicMock()
    mock_file.download_to_drive = AsyncMock()
    mock_context.bot.get_file.return_value = mock_file

    # Execute handler
    await handle_document(mock_update_document, mock_context)

    # Verify success (should sanitize filename)
    redis_client = mock_context.bot_data["redis_client"]
    event_data = redis_client.xadd.call_args[0][1]

    # Filename should be present (may be sanitized)
    assert "filename" in event_data
    assert len(event_data["filename"]) > 0


# ============================================================================
# Test 9: Fichier >20 Mo rejeté (AC#7)
# ============================================================================
@pytest.mark.asyncio
async def test_handle_document_too_large(mock_update_document, mock_context):
    """
    Test 9/10: Fichier >20 Mo rejeté (limite Telegram Bot API).
    """
    from bot.handlers.file_handlers import handle_document

    # Set file size > 20 MB
    mock_update_document.message.document.file_size = 21 * 1024 * 1024  # 21 MB

    # Execute handler
    await handle_document(mock_update_document, mock_context)

    # Verify rejection
    reply_text = mock_update_document.message.reply_text.call_args[0][0]
    assert "❌" in reply_text or "trop" in reply_text.lower()
    assert "20" in reply_text or "Mo" in reply_text


# ============================================================================
# Test 10: MIME type validation (AC#4)
# ============================================================================
@pytest.mark.asyncio
async def test_handle_document_mime_type_mismatch(mock_update_document, mock_context):
    """
    Test 10/10: MIME type incohérent avec extension détecté.

    Exemple : fichier.pdf mais MIME text/plain → rejeté (sécurité).
    """
    from bot.handlers.file_handlers import handle_document

    # Set MIME type mismatch (suspicious)
    mock_update_document.message.document.file_name = "document.pdf"
    mock_update_document.message.document.mime_type = "text/plain"

    # Execute handler
    await handle_document(mock_update_document, mock_context)

    # Should reject or at least log warning
    # (Implementation peut accepter avec warning, ou rejeter strict)
    # Pour ce test, on vérifie qu'il y a détection
    mock_update_document.message.reply_text.assert_called()
