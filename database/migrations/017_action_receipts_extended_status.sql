-- Migration 017: Extend action_receipts for Story 1.10
-- Adds 'expired', 'error', 'executed' to valid status values
-- Adds 'validated_by' column for audit trail (AC5)
-- Adds 'duration_ms' column missing from migration 011

BEGIN;

-- Drop existing constraint and recreate with additional values
ALTER TABLE core.action_receipts
    DROP CONSTRAINT IF EXISTS valid_status;

ALTER TABLE core.action_receipts
    ADD CONSTRAINT valid_status CHECK (
        status IN ('auto', 'pending', 'approved', 'rejected', 'corrected', 'expired', 'error', 'executed')
    );

-- AC5 fix: Colonne validated_by pour audit trail (qui a approuve/rejete)
ALTER TABLE core.action_receipts
    ADD COLUMN IF NOT EXISTS validated_by BIGINT;

COMMENT ON COLUMN core.action_receipts.validated_by IS
    'Telegram user_id du validateur (Story 1.10, AC5: audit trail)';

-- Fix: Colonne duration_ms manquante depuis migration 011
ALTER TABLE core.action_receipts
    ADD COLUMN IF NOT EXISTS duration_ms INTEGER;

COMMENT ON COLUMN core.action_receipts.duration_ms IS
    'Duree totale d''execution de l''action en millisecondes';

COMMENT ON CONSTRAINT valid_status ON core.action_receipts IS
    'Story 1.10: Added expired, error, executed statuses + validated_by + duration_ms';

COMMIT;
