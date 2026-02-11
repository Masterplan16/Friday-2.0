-- Migration 030: Ingestion Attachments
-- Story: 2.4 - Extraction Pièces Jointes
-- Date: 2026-02-11
-- Description: Table ingestion.attachments pour métadonnées PJ emails + colonne has_attachments dans emails

BEGIN;

-- =====================================================================
-- Table ingestion.attachments
-- =====================================================================
-- Stocke métadonnées des pièces jointes extraites des emails.
-- Zone transit VPS: /var/friday/transit/attachments/YYYY-MM-DD/
-- Cleanup quotidien: fichiers >24h ET status='archived' supprimés

CREATE TABLE IF NOT EXISTS ingestion.attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_id UUID NOT NULL REFERENCES ingestion.emails(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,  -- Nom original (sanitisé)
    filepath TEXT NOT NULL,  -- Chemin complet zone transit
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 26214400),  -- Max 25 Mo (25*1024*1024 bytes)
    mime_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processed', 'archived', 'error')),
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index pour requêtes fréquentes
CREATE INDEX IF NOT EXISTS idx_attachments_email_id ON ingestion.attachments(email_id);
CREATE INDEX IF NOT EXISTS idx_attachments_status ON ingestion.attachments(status);
CREATE INDEX IF NOT EXISTS idx_attachments_processed_at ON ingestion.attachments(processed_at) WHERE status = 'archived';

-- Trigger updated_at automatique
CREATE TRIGGER trg_attachments_updated_at
    BEFORE UPDATE ON ingestion.attachments
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at_column();

COMMENT ON TABLE ingestion.attachments IS 'Métadonnées pièces jointes emails extraites via EmailEngine. Zone transit VPS éphémère (cleanup 24h).';
COMMENT ON COLUMN ingestion.attachments.filename IS 'Nom original sanitisé (max 200 chars, caractères dangereux supprimés)';
COMMENT ON COLUMN ingestion.attachments.filepath IS 'Chemin complet zone transit: /var/friday/transit/attachments/YYYY-MM-DD/{email_id}_{index}_{filename}';
COMMENT ON COLUMN ingestion.attachments.size_bytes IS 'Taille fichier bytes (max 25 Mo = 26214400 bytes)';
COMMENT ON COLUMN ingestion.attachments.status IS 'pending: extrait, processed: traité par Archiviste, archived: copié PC, error: échec traitement';

-- =====================================================================
-- Colonne has_attachments dans ingestion.emails
-- =====================================================================
-- Permet filtre rapide emails avec PJ sans JOIN coûteux

ALTER TABLE ingestion.emails
ADD COLUMN IF NOT EXISTS has_attachments BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_emails_has_attachments ON ingestion.emails(has_attachments) WHERE has_attachments = TRUE;

COMMENT ON COLUMN ingestion.emails.has_attachments IS 'TRUE si email contient >=1 pièce jointe extraite. Mis à jour par extract_attachments().';

COMMIT;
