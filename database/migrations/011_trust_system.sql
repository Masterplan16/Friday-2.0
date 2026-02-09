-- Migration 011: Trust System (Observability & Trust Layer)
-- Story 1.5 - Tables pour receipts, correction rules, et trust metrics

BEGIN;

-- =====================================================================
-- Table: core.action_receipts
-- Description: Reçus de chaque action exécutée par les modules Friday
-- =====================================================================

CREATE TABLE IF NOT EXISTS core.action_receipts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identification
    module VARCHAR(50) NOT NULL,           -- Ex: "email", "archiviste", "finance"
    action_type VARCHAR(100) NOT NULL,     -- Ex: "classify", "rename", "detect_anomaly"

    -- Trust
    trust_level VARCHAR(20) NOT NULL,      -- "auto", "propose", "blocked"
    status VARCHAR(20) NOT NULL,           -- "auto" (executed), "pending" (awaiting approval), "approved", "rejected", "corrected"

    -- Input/Output
    input_summary TEXT NOT NULL,           -- Résumé de l'entrée (ex: "Email de dr.martin@...")
    output_summary TEXT,                   -- Résumé de la sortie (ex: "→ medical (0.92)")

    -- Qualité
    confidence FLOAT NOT NULL,             -- 0.0-1.0, confidence MIN de tous les steps
    reasoning TEXT,                        -- Explication du raisonnement

    -- Détails techniques
    payload JSONB,                         -- Données techniques optionnelles (steps, keywords, etc.)

    -- Feedback
    correction TEXT,                       -- Correction d'Antonio si action erronée
    feedback_comment TEXT,                 -- Commentaire additionnel d'Antonio

    -- Métadonnées
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Index
    CONSTRAINT valid_trust_level CHECK (trust_level IN ('auto', 'propose', 'blocked')),
    CONSTRAINT valid_status CHECK (status IN ('auto', 'pending', 'approved', 'rejected', 'corrected'))
);

-- Index pour requêtes fréquentes
CREATE INDEX IF NOT EXISTS idx_action_receipts_module_action ON core.action_receipts(module, action_type);
CREATE INDEX IF NOT EXISTS idx_action_receipts_status ON core.action_receipts(status);
CREATE INDEX IF NOT EXISTS idx_action_receipts_created_at ON core.action_receipts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_receipts_correction ON core.action_receipts(correction) WHERE correction IS NOT NULL;

-- Trigger pour updated_at automatique (réutilise core.update_updated_at() de migration 002)
CREATE TRIGGER action_receipts_updated_at
BEFORE UPDATE ON core.action_receipts
FOR EACH ROW
EXECUTE FUNCTION core.update_updated_at();

-- =====================================================================
-- Table: core.correction_rules
-- Description: Règles de correction explicites détectées depuis le feedback loop
-- =====================================================================

CREATE TABLE IF NOT EXISTS core.correction_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identification
    module VARCHAR(50) NOT NULL,
    action_type VARCHAR(100) NOT NULL,

    -- Règle
    rule_name VARCHAR(255) NOT NULL,      -- Ex: "URSSAF_to_finance"
    conditions JSONB NOT NULL,             -- Conditions de déclenchement (keywords, patterns, etc.)
    output JSONB NOT NULL,                 -- Output à appliquer si conditions match

    -- Scope
    scope VARCHAR(20) NOT NULL DEFAULT 'specific',  -- "global", "module", "specific"
    priority INTEGER NOT NULL DEFAULT 100,          -- Priority (plus bas = plus prioritaire)

    -- Métadonnées
    active BOOLEAN NOT NULL DEFAULT true,
    source_receipts UUID[],                -- Receipts ayant conduit à cette règle
    hit_count INTEGER NOT NULL DEFAULT 0,  -- Nombre de fois où la règle a matché

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100),               -- "antonio" ou "auto-detected"

    -- Index
    CONSTRAINT valid_scope CHECK (scope IN ('global', 'module', 'specific'))
);

CREATE INDEX IF NOT EXISTS idx_correction_rules_module_action ON core.correction_rules(module, action_type) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_correction_rules_priority ON core.correction_rules(priority);

-- =====================================================================
-- Table: core.trust_metrics
-- Description: Métriques d'accuracy hebdomadaire par module/action
-- =====================================================================

CREATE TABLE IF NOT EXISTS core.trust_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identification
    module VARCHAR(50) NOT NULL,
    action_type VARCHAR(100) NOT NULL,

    -- Période
    week_start DATE NOT NULL,              -- Lundi de la semaine
    week_end DATE NOT NULL,                -- Dimanche de la semaine

    -- Métriques
    total_actions INTEGER NOT NULL,        -- Nombre total d'actions exécutées
    corrected_actions INTEGER NOT NULL,    -- Nombre d'actions corrigées par Antonio
    accuracy FLOAT NOT NULL,               -- 1 - (corrected / total)

    -- Trust level actuel
    current_trust_level VARCHAR(20) NOT NULL,
    previous_trust_level VARCHAR(20),
    trust_changed BOOLEAN NOT NULL DEFAULT false,

    -- Métadonnées
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Contraintes
    CONSTRAINT valid_trust_level_current CHECK (current_trust_level IN ('auto', 'propose', 'blocked')),
    CONSTRAINT valid_trust_level_previous CHECK (previous_trust_level IS NULL OR previous_trust_level IN ('auto', 'propose', 'blocked')),
    CONSTRAINT unique_week_module_action UNIQUE (module, action_type, week_start)
);

CREATE INDEX IF NOT EXISTS idx_trust_metrics_module_action ON core.trust_metrics(module, action_type);
CREATE INDEX IF NOT EXISTS idx_trust_metrics_week_start ON core.trust_metrics(week_start DESC);
CREATE INDEX IF NOT EXISTS idx_trust_metrics_trust_changed ON core.trust_metrics(trust_changed) WHERE trust_changed = true;

-- =====================================================================
-- Commentaires
-- =====================================================================

COMMENT ON TABLE core.action_receipts IS 'Reçus de chaque action exécutée par les modules Friday (Trust Layer)';
COMMENT ON TABLE core.correction_rules IS 'Règles de correction explicites détectées depuis le feedback loop';
COMMENT ON TABLE core.trust_metrics IS 'Métriques d''accuracy hebdomadaire par module/action pour auto-rétrogradation';

COMMENT ON COLUMN core.action_receipts.confidence IS 'Confidence MIN de tous les steps (0.0-1.0)';
COMMENT ON COLUMN core.action_receipts.payload IS 'JSONB: steps détaillés, keywords, metadata technique';
COMMENT ON COLUMN core.correction_rules.conditions IS 'JSONB: {keywords: [...], min_match: 1, sender_pattern: ".*@urssaf.fr"}';
COMMENT ON COLUMN core.correction_rules.output IS 'JSONB: {category: "finance", priority: "high", confidence_boost: 0.1}';
COMMENT ON COLUMN core.trust_metrics.accuracy IS 'Formule: 1 - (corrected_actions / total_actions)';

COMMIT;
