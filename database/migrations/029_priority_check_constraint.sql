-- Migration 029: Add CHECK constraint for priority column
-- Story 2.3 Code Review Fix H3
-- Date: 2026-02-11
-- Description: Ajouter CHECK constraint pour valider les valeurs de priority (urgent/high/normal)
--              dans ingestion.emails. Fix anti-pattern valeurs non validées au niveau DB.

BEGIN;

-- Ajouter CHECK constraint sur colonne priority
ALTER TABLE ingestion.emails
ADD CONSTRAINT check_priority_values
CHECK (priority IN ('urgent', 'high', 'normal'));

-- Commentaire
COMMENT ON CONSTRAINT check_priority_values ON ingestion.emails IS
'Valide que priority est soit urgent, high, ou normal (Story 2.3 VIP/urgence)';

COMMIT;
