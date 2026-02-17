-- Migration 030: OCR Metadata Storage (Story 3.1 - Task 5)
-- Table pour stocker résultats OCR + métadonnées extraites

BEGIN;

-- Table metadata documents OCR (Task 5.1)
CREATE TABLE IF NOT EXISTS ingestion.document_metadata (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename TEXT NOT NULL,
    file_path TEXT,
    ocr_text TEXT NOT NULL,  -- Texte OCR anonymisé (AC6)
    extracted_date TIMESTAMPTZ,  -- Date du document (extraction Claude)
    doc_type TEXT,  -- Type: Facture, Courrier, Garantie, etc.
    emitter TEXT,  -- Émetteur/Expéditeur
    amount NUMERIC(10, 2) DEFAULT 0.0,  -- Montant en EUR
    confidence FLOAT CHECK (confidence >= 0.0 AND confidence <= 1.0),  -- Score confidence global
    page_count INTEGER DEFAULT 1,
    processing_duration FLOAT,  -- Durée traitement total (secondes)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index pour recherches rapides (Task 5.3)
CREATE INDEX IF NOT EXISTS idx_document_metadata_filename
    ON ingestion.document_metadata(filename);

CREATE INDEX IF NOT EXISTS idx_document_metadata_created_at
    ON ingestion.document_metadata(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_metadata_doc_type
    ON ingestion.document_metadata(doc_type);

CREATE INDEX IF NOT EXISTS idx_document_metadata_emitter
    ON ingestion.document_metadata(emitter);

-- Trigger updated_at automatique
CREATE OR REPLACE FUNCTION ingestion.update_document_metadata_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_document_metadata_updated_at
    BEFORE UPDATE ON ingestion.document_metadata
    FOR EACH ROW
    EXECUTE FUNCTION ingestion.update_document_metadata_updated_at();

-- Commentaires
COMMENT ON TABLE ingestion.document_metadata IS 'Métadonnées documents OCR (Story 3.1)';
COMMENT ON COLUMN ingestion.document_metadata.ocr_text IS 'Texte OCR anonymisé via Presidio (AC6)';
COMMENT ON COLUMN ingestion.document_metadata.confidence IS 'Score confidence global (min OCR, extraction)';

COMMIT;
