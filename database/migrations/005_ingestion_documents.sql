-- Migration 005: Ingestion documents
-- Date: 2026-02-05
-- Description: Documents scannés, factures, contrats, etc.

BEGIN;

CREATE TABLE ingestion.documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename VARCHAR(500) NOT NULL,
    original_filename VARCHAR(500),
    path TEXT NOT NULL,
    storage_location VARCHAR(20) NOT NULL DEFAULT 'vps' CHECK (storage_location IN ('vps', 'pc', 'cloud')),
    doc_type VARCHAR(50),
    category VARCHAR(100),
    subcategory VARCHAR(100),
    ocr_text TEXT,
    ocr_confidence FLOAT,
    file_size_bytes BIGINT,
    mime_type VARCHAR(100),
    checksum VARCHAR(64) UNIQUE,
    page_count INTEGER,
    metadata JSONB DEFAULT '{}',
    warranty_expiry DATE,
    document_date DATE,
    amount DECIMAL(15, 2),
    currency VARCHAR(3) DEFAULT 'EUR',
    indexed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_documents_category ON ingestion.documents(category);
CREATE INDEX idx_documents_doc_type ON ingestion.documents(doc_type);
CREATE INDEX idx_documents_checksum ON ingestion.documents(checksum);
CREATE INDEX idx_documents_created_at ON ingestion.documents(created_at DESC);
CREATE INDEX idx_documents_warranty_expiry ON ingestion.documents(warranty_expiry) WHERE warranty_expiry IS NOT NULL;
CREATE INDEX idx_documents_document_date ON ingestion.documents(document_date) WHERE document_date IS NOT NULL;

CREATE TRIGGER documents_updated_at
    BEFORE UPDATE ON ingestion.documents
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at();

COMMENT ON TABLE ingestion.documents IS 'Documents bruts (scans, factures, contrats)';
COMMENT ON COLUMN ingestion.documents.doc_type IS 'Type: facture, contrat, manuel, certificat, etc.';
COMMENT ON COLUMN ingestion.documents.warranty_expiry IS 'Date expiration garantie (tracking)';

COMMIT;
