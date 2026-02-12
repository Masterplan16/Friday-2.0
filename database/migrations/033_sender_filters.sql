-- Migration 033: Sender Filters Table
-- Story: 2.8 - Filtrage Sender Intelligent & Economie Tokens
-- Date: 2026-02-12
-- Description: Table core.sender_filters pour VIP/whitelist/blacklist.
--              Permet filtrage pre-classification LLM -> economie tokens Claude.
--              Semantique: VIP = prioritaire, whitelist = analyser, blacklist = skip analyse.

BEGIN;

-- =====================================================================
-- Table core.sender_filters
-- =====================================================================
-- Stocke regles filtrage sender/domain pour economiser tokens Claude.
-- Workflow: check_sender_filter() AVANT classify_email()
-- - vip -> notification immediate + analyse prioritaire
-- - blacklist -> skip analyse, stocker metadonnees seulement
-- - whitelist -> analyser normalement (proceed to classify)
-- - non liste -> analyser normalement (proceed to classify)

CREATE TABLE IF NOT EXISTS core.sender_filters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sender_email TEXT,  -- Email exact (ex: newsletter@example.com). NULL si filtrage par domaine uniquement.
    sender_domain TEXT,  -- Domaine (ex: example.com). NULL si filtrage par email uniquement.
    filter_type TEXT NOT NULL CHECK (filter_type IN ('vip', 'whitelist', 'blacklist')),
    category TEXT,  -- Categorie pre-assignee (optionnel). Valeurs: pro/finance/universite/recherche/perso/urgent/spam/inconnu
    confidence FLOAT,  -- Confidence score (1.0 blacklist, 0.95 whitelist/vip, NULL si non applicable)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL,  -- 'system' (extract_domains.py) ou 'user' (commandes Telegram)
    notes TEXT,  -- Notes explicatives optionnelles (ex: "Newsletter marketing recurrente")

    -- Contrainte: au moins sender_email OU sender_domain doit etre present
    CONSTRAINT check_sender_or_domain CHECK (
        sender_email IS NOT NULL OR sender_domain IS NOT NULL
    )
);

-- =====================================================================
-- Indexes
-- =====================================================================
-- Indexes performants pour lookup rapide (<50ms target)

-- Index UNIQUE sur sender_email (lookup exact email prioritaire)
CREATE UNIQUE INDEX IF NOT EXISTS idx_sender_filters_email
    ON core.sender_filters(sender_email)
    WHERE sender_email IS NOT NULL;

-- Index sur sender_domain (non-unique, plusieurs emails peuvent avoir meme domaine)
CREATE INDEX IF NOT EXISTS idx_sender_filters_domain
    ON core.sender_filters(sender_domain)
    WHERE sender_domain IS NOT NULL;

-- Index sur filter_type (pour requetes par type)
CREATE INDEX IF NOT EXISTS idx_sender_filters_type
    ON core.sender_filters(filter_type);

-- Index UNIQUE partiel sur sender_domain (pour ON CONFLICT dans extract_email_domains.py)
-- Empeche doublons de domain-only filters (quand sender_email IS NULL)
CREATE UNIQUE INDEX IF NOT EXISTS idx_sender_filters_domain_only
    ON core.sender_filters(sender_domain)
    WHERE sender_email IS NULL AND sender_domain IS NOT NULL;

-- Index partiel VIP pour queries rapides
CREATE INDEX IF NOT EXISTS idx_sender_filters_vip
    ON core.sender_filters(filter_type)
    WHERE filter_type = 'vip';

-- =====================================================================
-- Trigger updated_at automatique
-- =====================================================================

CREATE TRIGGER trg_sender_filters_updated_at
    BEFORE UPDATE ON core.sender_filters
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at_column();

-- =====================================================================
-- Documentation
-- =====================================================================

COMMENT ON TABLE core.sender_filters IS
'Regles filtrage sender/domain. VIP = prioritaire, whitelist = analyser normalement, blacklist = skip analyse (economie tokens).';

COMMENT ON COLUMN core.sender_filters.sender_email IS
'Email exact (ex: newsletter@example.com). NULL si filtrage par domaine uniquement. Lookup prioritaire.';

COMMENT ON COLUMN core.sender_filters.sender_domain IS
'Domaine (ex: example.com). NULL si filtrage par email uniquement. Fallback si email absent.';

COMMENT ON COLUMN core.sender_filters.filter_type IS
'Type filtrage: vip (prioritaire + notification immediate), whitelist (analyser normalement), blacklist (skip analyse, stocker metadonnees).';

COMMENT ON COLUMN core.sender_filters.category IS
'Categorie pre-assignee (optionnel). Valeurs: pro/finance/universite/recherche/perso/urgent/spam/inconnu.';

COMMENT ON COLUMN core.sender_filters.confidence IS
'Confidence score: 1.0 (blacklist), 0.95 (whitelist/vip), NULL si non applicable.';

COMMENT ON COLUMN core.sender_filters.created_by IS
'Origine regle: "system" (extract_email_domains.py auto), "user" (commandes Telegram /vip /blacklist /whitelist).';

COMMENT ON COLUMN core.sender_filters.notes IS
'Notes explicatives optionnelles (ex: "Newsletter marketing recurrente", "VIP hopital CHU").';

COMMIT;
