-- Migration 018: Add missing columns to core.trust_metrics
-- Story 1.11 - Fixes BUG-1.11.1, BUG-1.11.2
-- Colonnes referancees par nightly.py (Story 1.8) mais absentes du schema original (migration 011)

BEGIN;

-- BUG-1.11.1: avg_confidence calculee par nightly.py mais absente du schema
ALTER TABLE core.trust_metrics
    ADD COLUMN IF NOT EXISTS avg_confidence FLOAT;

COMMENT ON COLUMN core.trust_metrics.avg_confidence IS
    'Confidence moyenne des actions de la semaine (Story 1.11, BUG-1.11.1)';

-- BUG-1.11.2: last_trust_change_at reference par nightly.py et trust_commands.py
-- pour anti-oscillation (14 jours min entre retrogradation et promotion)
ALTER TABLE core.trust_metrics
    ADD COLUMN IF NOT EXISTS last_trust_change_at TIMESTAMPTZ;

COMMENT ON COLUMN core.trust_metrics.last_trust_change_at IS
    'Timestamp derniere transition trust level pour anti-oscillation (Story 1.11, BUG-1.11.2)';

-- Colonne recommended_trust_level ecrite par nightly.py mais absente du schema
ALTER TABLE core.trust_metrics
    ADD COLUMN IF NOT EXISTS recommended_trust_level VARCHAR(20);

ALTER TABLE core.trust_metrics
    ADD CONSTRAINT IF NOT EXISTS valid_recommended_trust_level
    CHECK (recommended_trust_level IS NULL OR recommended_trust_level IN ('auto', 'propose', 'blocked'));

COMMENT ON COLUMN core.trust_metrics.recommended_trust_level IS
    'Trust level recommande apres analyse accuracy (retrogradation auto si <90%)';

COMMIT;
