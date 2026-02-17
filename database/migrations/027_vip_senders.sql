-- Migration 027: VIP Senders Table
-- Story 2.3: Detection VIP & Urgence
-- Date: 2026-02-11
-- Description: Table pour stocker les expéditeurs VIP avec anonymisation RGPD.
--              Stockage via hash SHA256 pour lookup sans accès PII.
--              Support designation manuelle (/vip add) et apprentissage futur.

BEGIN;

-- Table vip_senders
CREATE TABLE IF NOT EXISTS core.vip_senders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email_anon TEXT NOT NULL UNIQUE,
    email_hash TEXT NOT NULL UNIQUE,
    label TEXT,
    priority_override TEXT CHECK (priority_override IN ('high', 'urgent')),
    designation_source TEXT NOT NULL DEFAULT 'manual' CHECK (designation_source IN ('manual', 'learned')),
    added_by UUID,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    emails_received_count INT DEFAULT 0 CHECK (emails_received_count >= 0),
    last_email_at TIMESTAMPTZ,
    active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index pour lookup rapide via hash (cas d'usage principal)
CREATE INDEX IF NOT EXISTS idx_vip_senders_hash
ON core.vip_senders(email_hash)
WHERE active = TRUE;

-- Index pour liste VIP actifs
CREATE INDEX IF NOT EXISTS idx_vip_senders_active
ON core.vip_senders(active, added_at DESC);

-- Index pour stats par source
CREATE INDEX IF NOT EXISTS idx_vip_senders_source
ON core.vip_senders(designation_source)
WHERE active = TRUE;

-- Commentaire table
COMMENT ON TABLE core.vip_senders IS
'Expéditeurs VIP avec anonymisation RGPD complète. '
'email_anon = version anonymisée Presidio (ex: [EMAIL_123]), '
'email_hash = SHA256 pour lookup sans accès PII, '
'designation_source = manual (/vip add) ou learned (apprentissage futur).';

-- Commentaires colonnes
COMMENT ON COLUMN core.vip_senders.id IS 'Identifiant unique UUID';
COMMENT ON COLUMN core.vip_senders.email_anon IS 'Email anonymisé via Presidio (ex: [EMAIL_123])';
COMMENT ON COLUMN core.vip_senders.email_hash IS 'SHA256(email_original.lower().strip()) pour lookup';
COMMENT ON COLUMN core.vip_senders.label IS 'Label optionnel (ex: "Doyen", "Comptable")';
COMMENT ON COLUMN core.vip_senders.priority_override IS 'Force priorité si défini (high/urgent)';
COMMENT ON COLUMN core.vip_senders.designation_source IS 'Source: manual (/vip add) ou learned (auto)';
COMMENT ON COLUMN core.vip_senders.added_by IS 'User ID Telegram qui a ajouté ce VIP';
COMMENT ON COLUMN core.vip_senders.emails_received_count IS 'Nombre d''emails reçus de ce VIP';
COMMENT ON COLUMN core.vip_senders.last_email_at IS 'Date du dernier email reçu';
COMMENT ON COLUMN core.vip_senders.active IS 'Soft delete (FALSE = VIP retiré)';

-- Trigger pour updated_at
CREATE OR REPLACE FUNCTION core.update_vip_senders_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_vip_senders_updated_at
BEFORE UPDATE ON core.vip_senders
FOR EACH ROW
EXECUTE FUNCTION core.update_vip_senders_updated_at();

COMMIT;
