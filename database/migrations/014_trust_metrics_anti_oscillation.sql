-- Migration 014: Ajout colonne anti-oscillation pour trust metrics
-- Story 1.8 - AC7 : Anti-oscillation 2 semaines
-- Date: 2026-02-10
-- Description: Ajoute colonne last_trust_change_at pour tracker les transitions trust level

BEGIN;

-- Ajouter colonne last_trust_change_at dans core.trust_metrics
ALTER TABLE core.trust_metrics
ADD COLUMN IF NOT EXISTS last_trust_change_at TIMESTAMPTZ DEFAULT NULL;

-- Initialiser last_trust_change_at pour lignes existantes (évite NULL sur modules existants)
-- NULL = pas d'anti-oscillation pour permettre transitions futures
UPDATE core.trust_metrics
SET last_trust_change_at = calculated_at
WHERE last_trust_change_at IS NULL AND calculated_at IS NOT NULL;

-- Commentaire explicatif
COMMENT ON COLUMN core.trust_metrics.last_trust_change_at IS
'Timestamp dernière transition trust level. Utilisé pour anti-oscillation :
- Après rétrogradation → 14 jours min avant promotion
- Après promotion → 7 jours min avant rétrogradation
- Lignes existantes initialisées à calculated_at pour cohérence';

-- Créer index pour optimiser les requêtes anti-oscillation
CREATE INDEX IF NOT EXISTS idx_trust_metrics_last_change
ON core.trust_metrics(module, action_type, last_trust_change_at DESC);

COMMIT;
