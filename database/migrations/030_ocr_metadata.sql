-- Migration 030: OCR Metadata
-- Date: 2026-02-16
-- Description: Table métadonnées OCR pour Surya (Story 3.1 - Archiviste)
-- AC: Stockage texte OCR + confidence + métadonnées par document

BEGIN;

-- Table ocr_metadata : métadonnées OCR par document
CREATE TABLE IF NOT EXISTS ingestion.ocr_metadata (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL,
    ocr_text TEXT NOT NULL,
    confidence FLOAT CHECK (confidence >= 0 AND confidence <= 1),
    page_number INTEGER,
    language_detected VARCHAR(10),
    processing_time_ms INTEGER,
    model_version VARCHAR(50) DEFAULT 'surya-v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index document_id pour retrouver OCR par document
CREATE INDEX IF NOT EXISTS idx_ocr_metadata_document
    ON ingestion.ocr_metadata(document_id);

-- Index confidence pour filtrage qualité
CREATE INDEX IF NOT EXISTS idx_ocr_metadata_confidence
    ON ingestion.ocr_metadata(confidence);

-- Index page_number pour PDFs multi-pages
CREATE INDEX IF NOT EXISTS idx_ocr_metadata_page
    ON ingestion.ocr_metadata(document_id, page_number);

-- Trigger updated_at automatique
CREATE TRIGGER update_ocr_metadata_updated_at
    BEFORE UPDATE ON ingestion.ocr_metadata
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at();

-- Commentaires documentation
COMMENT ON TABLE ingestion.ocr_metadata IS 'Métadonnées OCR extraites par Surya (Story 3.1 - Archiviste)';
COMMENT ON COLUMN ingestion.ocr_metadata.id IS 'UUID primary key unique';
COMMENT ON COLUMN ingestion.ocr_metadata.document_id IS 'Foreign key vers ingestion.documents (ou ingestion.emails_attachments)';
COMMENT ON COLUMN ingestion.ocr_metadata.ocr_text IS 'Texte extrait via OCR Surya (NOT NULL - fail-explicit si OCR crash)';
COMMENT ON COLUMN ingestion.ocr_metadata.confidence IS 'Score confiance OCR 0-1 (CHECK constraint)';
COMMENT ON COLUMN ingestion.ocr_metadata.page_number IS 'Numéro page (NULL pour images, 1+ pour PDFs multi-pages)';
COMMENT ON COLUMN ingestion.ocr_metadata.language_detected IS 'Code langue ISO 639-1 (ex: fr, en)';
COMMENT ON COLUMN ingestion.ocr_metadata.processing_time_ms IS 'Temps traitement OCR en millisecondes';
COMMENT ON COLUMN ingestion.ocr_metadata.model_version IS 'Version modèle Surya utilisé (tracking)';

COMMIT;
