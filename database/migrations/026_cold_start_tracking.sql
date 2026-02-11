-- Migration 026: Cold Start Tracking Table
-- Story 2.2: Classification Email LLM
-- Date: 2026-02-11
-- Description: Table pour tracker le cold start mode des modules (email.classify, etc.)
--              Permet de forcer trust=propose pour les premiers 10-20 emails traités.

BEGIN;

-- Table cold_start_tracking
CREATE TABLE IF NOT EXISTS core.cold_start_tracking (
    module VARCHAR(50) NOT NULL,
    action_type VARCHAR(100) NOT NULL,
    phase VARCHAR(20) NOT NULL CHECK (phase IN ('cold_start', 'calibrated', 'production')),
    emails_processed INT NOT NULL DEFAULT 0 CHECK (emails_processed >= 0),
    accuracy DOUBLE PRECISION CHECK (accuracy IS NULL OR (accuracy >= 0.0 AND accuracy <= 1.0)),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (module, action_type)
);

-- Index pour requêtes rapides par module/action
CREATE INDEX IF NOT EXISTS idx_cold_start_module_action
ON core.cold_start_tracking(module, action_type);

-- Index pour filtrer par phase
CREATE INDEX IF NOT EXISTS idx_cold_start_phase
ON core.cold_start_tracking(phase);

-- Commentaire table
COMMENT ON TABLE core.cold_start_tracking IS
'Tracking du cold start mode pour calibrage initial des modules IA. '
'Phase cold_start = validation manuelle forcée, '
'calibrated = seuil 10 emails atteint, '
'production = accuracy ≥90% validée.';

-- Commentaires colonnes
COMMENT ON COLUMN core.cold_start_tracking.module IS 'Module fonctionnel (email, archiviste, finance, etc.)';
COMMENT ON COLUMN core.cold_start_tracking.action_type IS 'Type d''action (classify, extract, summarize, etc.)';
COMMENT ON COLUMN core.cold_start_tracking.phase IS 'Phase du cold start: cold_start, calibrated, production';
COMMENT ON COLUMN core.cold_start_tracking.emails_processed IS 'Nombre d''emails traités depuis le cold start';
COMMENT ON COLUMN core.cold_start_tracking.accuracy IS 'Accuracy calculée (NULL si <10 emails)';

-- Trigger pour updated_at
CREATE OR REPLACE FUNCTION core.update_cold_start_tracking_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_cold_start_tracking_updated_at
BEFORE UPDATE ON core.cold_start_tracking
FOR EACH ROW
EXECUTE FUNCTION core.update_cold_start_tracking_updated_at();

-- Seed initial pour email.classify (Story 2.2)
INSERT INTO core.cold_start_tracking
    (module, action_type, phase, emails_processed, accuracy)
VALUES
    ('email', 'classify', 'cold_start', 0, NULL)
ON CONFLICT (module, action_type) DO NOTHING;

COMMIT;
