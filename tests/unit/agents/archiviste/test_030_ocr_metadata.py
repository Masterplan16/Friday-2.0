"""
Tests migration 030_ocr_metadata.sql (Story 3.1 - Task 5.4).

Verifie :
- Creation table ingestion.document_metadata
- Index sur filename, created_at, doc_type, emitter
- Trigger updated_at automatique
- Structure colonnes et contraintes
"""
import pytest
from pathlib import Path


MIGRATION_PATH = Path("database/migrations/030_ocr_metadata.sql")


def test_migration_file_exists():
    """Verifier que le fichier migration existe."""
    assert MIGRATION_PATH.exists(), f"Migration file not found: {MIGRATION_PATH}"


def test_migration_uses_begin_commit():
    """Verifier que la migration est transactionnelle (BEGIN/COMMIT)."""
    content = MIGRATION_PATH.read_text()
    assert "BEGIN;" in content, "Migration missing BEGIN"
    assert "COMMIT;" in content, "Migration missing COMMIT"


def test_migration_creates_table_in_ingestion_schema():
    """Verifier que la table est dans le schema ingestion (pas public)."""
    content = MIGRATION_PATH.read_text()
    assert "ingestion.document_metadata" in content
    assert "CREATE TABLE" in content


def test_migration_has_uuid_primary_key():
    """Verifier que la PK est UUID (standard Friday 2.0)."""
    content = MIGRATION_PATH.read_text()
    assert "UUID PRIMARY KEY" in content
    assert "gen_random_uuid()" in content


def test_migration_has_required_columns():
    """Verifier les colonnes requises pour OCR metadata."""
    content = MIGRATION_PATH.read_text()
    required_columns = [
        "filename TEXT",
        "file_path TEXT",
        "ocr_text TEXT",
        "extracted_date TIMESTAMPTZ",
        "doc_type TEXT",
        "emitter TEXT",
        "amount NUMERIC",
        "confidence FLOAT",
        "page_count INTEGER",
        "processing_duration FLOAT",
        "created_at TIMESTAMPTZ",
        "updated_at TIMESTAMPTZ",
    ]
    for col in required_columns:
        assert col in content, f"Missing column: {col}"


def test_migration_has_confidence_check_constraint():
    """Verifier la contrainte CHECK sur confidence (0.0-1.0)."""
    content = MIGRATION_PATH.read_text()
    assert "confidence >= 0.0" in content
    assert "confidence <= 1.0" in content


def test_migration_has_indexes():
    """Verifier les index pour recherches rapides (Task 5.3)."""
    content = MIGRATION_PATH.read_text()
    expected_indexes = [
        "idx_document_metadata_filename",
        "idx_document_metadata_created_at",
        "idx_document_metadata_doc_type",
        "idx_document_metadata_emitter",
    ]
    for idx in expected_indexes:
        assert idx in content, f"Missing index: {idx}"


def test_migration_has_updated_at_trigger():
    """Verifier le trigger updated_at automatique."""
    content = MIGRATION_PATH.read_text()
    assert "update_document_metadata_updated_at" in content
    assert "BEFORE UPDATE" in content
    assert "FOR EACH ROW" in content


def test_migration_has_comments():
    """Verifier les commentaires SQL sur table et colonnes."""
    content = MIGRATION_PATH.read_text()
    assert "COMMENT ON TABLE" in content
    assert "COMMENT ON COLUMN" in content


def test_migration_uses_if_not_exists():
    """Verifier IF NOT EXISTS pour idempotence."""
    content = MIGRATION_PATH.read_text()
    assert "IF NOT EXISTS" in content


def test_migration_ocr_text_not_null():
    """Verifier que ocr_text est NOT NULL (toujours anonymise)."""
    content = MIGRATION_PATH.read_text()
    assert "ocr_text TEXT NOT NULL" in content
