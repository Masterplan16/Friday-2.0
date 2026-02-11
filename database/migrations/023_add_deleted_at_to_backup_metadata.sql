-- Migration 023: Add deleted_at column to core.backup_metadata
-- Story 1.15 - AC3: Rotation backups > 30 jours (VPS uniquement) - Soft delete pattern
-- Created: 2026-02-10

BEGIN;

-- Add deleted_at column for soft delete audit trail
ALTER TABLE core.backup_metadata
ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Create index for efficient queries on active/deleted backups
CREATE INDEX IF NOT EXISTS idx_backup_metadata_deleted
    ON core.backup_metadata(deleted_at NULLS FIRST, backup_date DESC);

-- Add comment explaining soft delete pattern
COMMENT ON COLUMN core.backup_metadata.deleted_at IS
'TIMESTAMPTZ de suppression du backup (soft delete pour audit trail). NULL = backup actif. VPS backups (retention_policy=keep_7_days) sont marqués deleted après 30 jours.';

-- Verify column exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'core'
          AND table_name = 'backup_metadata'
          AND column_name = 'deleted_at'
    ) THEN
        RAISE EXCEPTION 'Migration 023 failed: deleted_at column not created';
    END IF;
END $$;

COMMIT;
