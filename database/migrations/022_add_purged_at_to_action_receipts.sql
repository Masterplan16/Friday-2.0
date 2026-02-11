-- Migration 022: Add purged_at column to core.action_receipts
-- Story 1.15 - AC1: Purge mappings Presidio > 30 jours (RGPD compliance)
-- Created: 2026-02-10

BEGIN;

-- Add purged_at column for audit trail
ALTER TABLE core.action_receipts
ADD COLUMN IF NOT EXISTS purged_at TIMESTAMPTZ;

-- Create index for efficient queries on purged receipts
CREATE INDEX IF NOT EXISTS idx_action_receipts_purged
    ON core.action_receipts(purged_at NULLS FIRST, created_at DESC);

-- Add comment explaining RGPD compliance
COMMENT ON COLUMN core.action_receipts.purged_at IS
'Timestamp de purge du mapping Presidio (RGPD - 30 jours retention). NULL = mapping non encore purgé ou jamais existé.';

-- Verify column exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'core'
          AND table_name = 'action_receipts'
          AND column_name = 'purged_at'
    ) THEN
        RAISE EXCEPTION 'Migration 022 failed: purged_at column not created';
    END IF;
END $$;

COMMIT;
