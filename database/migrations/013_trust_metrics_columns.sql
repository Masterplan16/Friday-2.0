-- Migration 013: Trust Metrics Additional Columns
-- Story 1.7 - Ajouter colonnes manquantes pour nightly.py (Bugs #4 et #5)

BEGIN;

-- =====================================================================
-- Bug #4: Ajouter colonne recommended_trust_level
-- =====================================================================

ALTER TABLE core.trust_metrics
ADD COLUMN IF NOT EXISTS recommended_trust_level VARCHAR(20) CHECK (recommended_trust_level IN ('auto', 'propose', 'blocked'));

COMMENT ON COLUMN core.trust_metrics.recommended_trust_level IS 'Trust level recommandé par le système (rétrogradation automatique si accuracy < 90%)';

-- =====================================================================
-- Bug #5: Ajouter colonne avg_confidence
-- =====================================================================

ALTER TABLE core.trust_metrics
ADD COLUMN IF NOT EXISTS avg_confidence FLOAT DEFAULT NULL;

COMMENT ON COLUMN core.trust_metrics.avg_confidence IS 'Confidence moyenne des actions sur la période (0.0-1.0)';

-- =====================================================================
-- Commentaire
-- =====================================================================

COMMENT ON TABLE core.trust_metrics IS 'Métriques d''accuracy hebdomadaire par module/action pour auto-rétrogradation (Story 1.7 columns added)';

COMMIT;
