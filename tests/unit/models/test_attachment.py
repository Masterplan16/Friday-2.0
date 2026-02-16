"""
Tests unitaires pour models attachment.

Valide :
- Attachment schema validation
- AttachmentExtractResult schema
- Validators Pydantic (filename, size_bytes, mime_type, filepath)
- ActionResult compatibility
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from agents.src.models.attachment import (
    MAX_ATTACHMENT_SIZE_BYTES,
    MAX_FILENAME_LENGTH,
    Attachment,
    AttachmentExtractResult,
)
from pydantic import ValidationError


class TestAttachmentSchema:
    """Tests schema Attachment."""

    def test_attachment_valid_data(self):
        """Attachment valide avec toutes données correctes."""
        attachment = Attachment(
            id=uuid4(),
            email_id=uuid4(),
            filename="facture_2026.pdf",
            filepath="/var/friday/transit/attachments/2026-02-11/test.pdf",
            size_bytes=150000,
            mime_type="application/pdf",
            status="pending",
            extracted_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        assert attachment.filename == "facture_2026.pdf"
        assert attachment.size_bytes == 150000
        assert attachment.mime_type == "application/pdf"
        assert attachment.status == "pending"

    def test_attachment_filename_empty_fails(self):
        """Filename vide rejété."""
        with pytest.raises(ValidationError) as exc_info:
            Attachment(
                id=uuid4(),
                email_id=uuid4(),
                filename="",  # Vide
                filepath="/var/friday/transit/test.pdf",
                size_bytes=150000,
                mime_type="application/pdf",
                status="pending",
                extracted_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        assert "Filename cannot be empty" in str(exc_info.value)

    def test_attachment_filename_too_long_fails(self):
        """Filename >200 chars rejété."""
        long_filename = "a" * 250 + ".pdf"

        with pytest.raises(ValidationError) as exc_info:
            Attachment(
                id=uuid4(),
                email_id=uuid4(),
                filename=long_filename,
                filepath="/var/friday/transit/test.pdf",
                size_bytes=150000,
                mime_type="application/pdf",
                status="pending",
                extracted_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        # Pydantic v2 message: "String should have at most 200 characters"
        assert "at most 200 characters" in str(exc_info.value)

    def test_attachment_filename_whitespace_trimmed(self):
        """Filename avec espaces début/fin trimmed."""
        attachment = Attachment(
            id=uuid4(),
            email_id=uuid4(),
            filename="  facture.pdf  ",  # Espaces
            filepath="/var/friday/transit/test.pdf",
            size_bytes=150000,
            mime_type="application/pdf",
            status="pending",
            extracted_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        assert attachment.filename == "facture.pdf"  # Trimmed

    def test_attachment_size_bytes_zero_fails(self):
        """size_bytes = 0 rejété (doit être >0)."""
        with pytest.raises(ValidationError) as exc_info:
            Attachment(
                id=uuid4(),
                email_id=uuid4(),
                filename="test.pdf",
                filepath="/var/friday/transit/test.pdf",
                size_bytes=0,  # Invalid
                mime_type="application/pdf",
                status="pending",
                extracted_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        assert "greater than 0" in str(exc_info.value)

    def test_attachment_size_bytes_over_25mb_fails(self):
        """size_bytes >25 Mo rejété."""
        with pytest.raises(ValidationError) as exc_info:
            Attachment(
                id=uuid4(),
                email_id=uuid4(),
                filename="test.pdf",
                filepath="/var/friday/transit/test.pdf",
                size_bytes=MAX_ATTACHMENT_SIZE_BYTES + 1,  # 25 Mo + 1 byte
                mime_type="application/pdf",
                status="pending",
                extracted_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        assert "less than or equal to" in str(exc_info.value)

    def test_attachment_mime_type_invalid_format_fails(self):
        """MIME type sans '/' rejété."""
        with pytest.raises(ValidationError) as exc_info:
            Attachment(
                id=uuid4(),
                email_id=uuid4(),
                filename="test.pdf",
                filepath="/var/friday/transit/test.pdf",
                size_bytes=150000,
                mime_type="invalidmimetype",  # Pas de '/'
                status="pending",
                extracted_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        assert "Invalid MIME type format" in str(exc_info.value)

    def test_attachment_mime_type_normalized_lowercase(self):
        """MIME type normalisé lowercase."""
        attachment = Attachment(
            id=uuid4(),
            email_id=uuid4(),
            filename="test.pdf",
            filepath="/var/friday/transit/test.pdf",
            size_bytes=150000,
            mime_type="APPLICATION/PDF",  # Uppercase
            status="pending",
            extracted_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        assert attachment.mime_type == "application/pdf"  # Lowercase

    def test_attachment_filepath_empty_fails(self):
        """Filepath vide rejété."""
        with pytest.raises(ValidationError) as exc_info:
            Attachment(
                id=uuid4(),
                email_id=uuid4(),
                filename="test.pdf",
                filepath="",  # Vide
                size_bytes=150000,
                mime_type="application/pdf",
                status="pending",
                extracted_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        assert "Filepath cannot be empty" in str(exc_info.value)

    def test_attachment_filepath_must_be_absolute(self):
        """Filepath doit être chemin absolu Unix (/...)."""
        with pytest.raises(ValidationError) as exc_info:
            Attachment(
                id=uuid4(),
                email_id=uuid4(),
                filename="test.pdf",
                filepath="relative/path/test.pdf",  # Relatif
                size_bytes=150000,
                mime_type="application/pdf",
                status="pending",
                extracted_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        assert "must be absolute Unix path" in str(exc_info.value)

    def test_attachment_status_valid_values(self):
        """Status accepte pending/processed/archived/error uniquement."""
        valid_statuses = ["pending", "processed", "archived", "error"]

        for status in valid_statuses:
            attachment = Attachment(
                id=uuid4(),
                email_id=uuid4(),
                filename="test.pdf",
                filepath="/var/friday/transit/test.pdf",
                size_bytes=150000,
                mime_type="application/pdf",
                status=status,
                extracted_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            assert attachment.status == status

    def test_attachment_status_invalid_fails(self):
        """Status invalide rejété."""
        with pytest.raises(ValidationError):
            Attachment(
                id=uuid4(),
                email_id=uuid4(),
                filename="test.pdf",
                filepath="/var/friday/transit/test.pdf",
                size_bytes=150000,
                mime_type="application/pdf",
                status="invalid_status",  # Invalid
                extracted_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )


class TestAttachmentExtractResult:
    """Tests schema AttachmentExtractResult."""

    def test_extract_result_valid_data(self):
        """AttachmentExtractResult valide."""
        result = AttachmentExtractResult(
            extracted_count=2,
            failed_count=1,
            total_size_mb=0.38,
            filepaths=[
                "/var/friday/transit/attachments/2026-02-11/test1.pdf",
                "/var/friday/transit/attachments/2026-02-11/test2.jpg",
            ],
        )

        assert result.extracted_count == 2
        assert result.failed_count == 1
        assert result.total_size_mb == 0.38
        assert len(result.filepaths) == 2

    def test_extract_result_negative_counts_fails(self):
        """extracted_count/failed_count négatifs rejetés."""
        with pytest.raises(ValidationError):
            AttachmentExtractResult(
                extracted_count=-1, failed_count=0, total_size_mb=0.0, filepaths=[]  # Négatif
            )

        with pytest.raises(ValidationError):
            AttachmentExtractResult(
                extracted_count=0, failed_count=-5, total_size_mb=0.0, filepaths=[]  # Négatif
            )

    def test_extract_result_filepaths_must_be_absolute(self):
        """Filepaths doivent être absolus Unix."""
        with pytest.raises(ValidationError) as exc_info:
            AttachmentExtractResult(
                extracted_count=1,
                failed_count=0,
                total_size_mb=0.15,
                filepaths=["relative/path/file.pdf"],  # Relatif
            )

        assert "must be absolute Unix path" in str(exc_info.value)

    def test_extract_result_action_result_compatibility(self):
        """AttachmentExtractResult compatible avec ActionResult (Trust Layer)."""
        result = AttachmentExtractResult(
            extracted_count=2,
            failed_count=1,
            total_size_mb=0.38,
            filepaths=[
                "/var/friday/transit/attachments/2026-02-11/test1.pdf",
                "/var/friday/transit/attachments/2026-02-11/test2.jpg",
            ],
        )

        # ActionResult fields présents
        assert hasattr(result, "input_summary")
        assert hasattr(result, "output_summary")
        assert hasattr(result, "confidence")
        assert hasattr(result, "reasoning")

        # Confidence = 1.0 (extraction déterministe)
        assert result.confidence == 1.0

    def test_extract_result_generate_summaries(self):
        """generate_summaries() crée input_summary/output_summary/reasoning."""
        result = AttachmentExtractResult(
            extracted_count=2,
            failed_count=1,
            total_size_mb=0.38,
            filepaths=[
                "/var/friday/transit/attachments/2026-02-11/test1.pdf",
                "/var/friday/transit/attachments/2026-02-11/test2.jpg",
            ],
        )

        result.generate_summaries(email_id="abc123", attachments_total=3)

        assert "abc123" in result.input_summary
        assert "3 pièce(s)" in result.input_summary
        assert "2 extraite(s)" in result.output_summary
        assert "1 ignorée(s)" in result.output_summary
        assert "2 PJ extraites" in result.reasoning
        assert "0.38 Mo" in result.reasoning
        assert "1 PJ ignorées" in result.reasoning

    def test_extract_result_generate_summaries_no_failed(self):
        """generate_summaries() avec failed_count=0."""
        result = AttachmentExtractResult(
            extracted_count=3,
            failed_count=0,
            total_size_mb=1.2,
            filepaths=[
                "/var/friday/transit/test1.pdf",
                "/var/friday/transit/test2.pdf",
                "/var/friday/transit/test3.pdf",
            ],
        )

        result.generate_summaries(email_id="xyz789", attachments_total=3)

        assert "xyz789" in result.input_summary
        assert "0 ignorée(s)" in result.output_summary
        assert "3 PJ extraites" in result.reasoning
        assert "1.20 Mo" in result.reasoning
        assert "ignorées" not in result.reasoning  # Pas de failed

    def test_extract_result_generate_summaries_all_failed(self):
        """generate_summaries() avec extracted_count=0 (toutes failed)."""
        result = AttachmentExtractResult(
            extracted_count=0, failed_count=2, total_size_mb=0.0, filepaths=[]
        )

        result.generate_summaries(email_id="def456", attachments_total=2)

        assert "def456" in result.input_summary
        assert "0 extraite(s)" in result.output_summary
        assert "2 ignorée(s)" in result.output_summary
        assert "2 PJ ignorées" in result.reasoning
