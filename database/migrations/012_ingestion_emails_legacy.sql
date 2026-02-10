-- Migration 012: Table emails_legacy pour import bulk 110k emails existants
-- Date: 2026-02-05
-- Description: Création de la table ingestion.emails_legacy pour stocker les 110 000 emails
--              existants des 4 comptes IMAP d'owner avant migration vers ingestion.emails
-- Prérequis: Migration 004 (ingestion.emails) doit être appliquée
-- Usage: Cette table est utilisée par scripts/migrate_emails.py pour la migration one-shot

BEGIN;

-- Table temporaire pour stocker les emails bruts avant classification
CREATE TABLE IF NOT EXISTS ingestion.emails_legacy (
    message_id TEXT PRIMARY KEY,
    account TEXT NOT NULL,  -- Compte source (ex: "mainteneur@example.com")
    sender TEXT,
    recipients TEXT[],  -- Array des destinataires
    subject TEXT,
    body_text TEXT,  -- Contenu texte brut
    body_html TEXT,  -- Contenu HTML (optionnel)
    received_at TIMESTAMPTZ NOT NULL,
    has_attachments BOOLEAN DEFAULT false,
    attachment_count INTEGER DEFAULT 0,
    imported_at TIMESTAMPTZ DEFAULT NOW(),

    -- Métadonnées bulk import
    import_batch_id UUID,  -- ID du batch d'import (pour tracking)
    import_source TEXT DEFAULT 'emailengine_bulk_export'  -- Source de l'import
);

-- Index pour recherche et tri
CREATE INDEX IF NOT EXISTS idx_emails_legacy_received ON ingestion.emails_legacy(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_legacy_account ON ingestion.emails_legacy(account);
CREATE INDEX IF NOT EXISTS idx_emails_legacy_import_batch ON ingestion.emails_legacy(import_batch_id);
CREATE INDEX IF NOT EXISTS idx_emails_legacy_has_attachments ON ingestion.emails_legacy(has_attachments) WHERE has_attachments = true;

-- Commentaires
COMMENT ON TABLE ingestion.emails_legacy IS 'Table temporaire pour stocker les 110k emails existants avant migration vers ingestion.emails. Cette table est peuplée via EmailEngine bulk export puis migrée par scripts/migrate_emails.py.';
COMMENT ON COLUMN ingestion.emails_legacy.message_id IS 'Message-ID unique de l''email (RFC 5322)';
COMMENT ON COLUMN ingestion.emails_legacy.account IS 'Compte IMAP source (ex: mainteneur@cabinet.fr, mainteneur@univ.fr)';
COMMENT ON COLUMN ingestion.emails_legacy.import_batch_id IS 'UUID du batch d''import pour traçabilité (optionnel)';

-- Statistiques initiales
-- Après import bulk, exécuter: ANALYZE ingestion.emails_legacy;

COMMIT;
