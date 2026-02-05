-- Migration 004: Ingestion emails
-- Date: 2026-02-05
-- Description: Table emails (zone d'entrée données brutes)

BEGIN;

CREATE TABLE ingestion.emails (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    message_id VARCHAR(255) UNIQUE NOT NULL,
    thread_id VARCHAR(255),
    sender VARCHAR(500) NOT NULL,
    recipients TEXT[] NOT NULL,
    cc TEXT[],
    bcc TEXT[],
    subject TEXT NOT NULL,
    body_text TEXT,
    body_html TEXT,
    category VARCHAR(50),
    priority VARCHAR(20) CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    confidence FLOAT,
    has_attachments BOOLEAN DEFAULT false,
    attachment_count INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    received_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_emails_message_id ON ingestion.emails(message_id);
CREATE INDEX idx_emails_sender ON ingestion.emails(sender);
CREATE INDEX idx_emails_category ON ingestion.emails(category);
CREATE INDEX idx_emails_received_at ON ingestion.emails(received_at DESC);
CREATE INDEX idx_emails_processed_at ON ingestion.emails(processed_at) WHERE processed_at IS NOT NULL;

COMMENT ON TABLE ingestion.emails IS 'Emails bruts (4 comptes IMAP via EmailEngine)';
COMMENT ON COLUMN ingestion.emails.category IS 'Catégorie IA (medical, finance, thesis, personal, etc.)';
COMMENT ON COLUMN ingestion.emails.confidence IS 'Confidence score classification (0.0-1.0)';

-- Table attachments
CREATE TABLE ingestion.email_attachments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email_id UUID NOT NULL REFERENCES ingestion.emails(id) ON DELETE CASCADE,
    filename VARCHAR(500) NOT NULL,
    content_type VARCHAR(100),
    size_bytes BIGINT,
    storage_path TEXT NOT NULL,
    checksum VARCHAR(64),
    ocr_text TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_attachments_email_id ON ingestion.email_attachments(email_id);
CREATE INDEX idx_attachments_content_type ON ingestion.email_attachments(content_type);

COMMENT ON TABLE ingestion.email_attachments IS 'Pièces jointes emails (stockage VPS)';

COMMIT;
