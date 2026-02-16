-- Migration 039: Batch jobs tracking table
-- Story 3.7: Traitement Batch Dossier
-- Purpose: Track batch processing jobs with filters, status, and audit trail
--
-- AC4: Audit trail batch processing

BEGIN;

-- ============================================================================
-- Table: core.batch_jobs
-- ============================================================================

CREATE TABLE IF NOT EXISTS core.batch_jobs (
    batch_id UUID PRIMARY KEY,
    folder_path TEXT NOT NULL,
    filters JSONB DEFAULT '{}'::jsonb,

    -- Status
    status TEXT NOT NULL DEFAULT 'pending',
    CHECK (status IN ('pending', 'running', 'completed', 'completed_with_errors', 'failed', 'cancelled')),

    -- Counters
    total_files INT DEFAULT 0,
    files_processed INT DEFAULT 0,
    files_success INT DEFAULT 0,
    files_failed INT DEFAULT 0,
    files_skipped INT DEFAULT 0,

    -- Categories breakdown
    categories JSONB DEFAULT '{}'::jsonb,

    -- Failed files tracking
    failed_files JSONB DEFAULT '[]'::jsonb,

    -- Report (final summary)
    report TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_batch_jobs_status ON core.batch_jobs(status);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_created_at ON core.batch_jobs(created_at DESC);

-- Update trigger
CREATE OR REPLACE FUNCTION core.update_batch_jobs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_batch_jobs_updated_at ON core.batch_jobs;
CREATE TRIGGER trigger_update_batch_jobs_updated_at
    BEFORE UPDATE ON core.batch_jobs
    FOR EACH ROW
    EXECUTE FUNCTION core.update_batch_jobs_updated_at();

-- Comments
COMMENT ON TABLE core.batch_jobs IS 'Batch processing jobs tracking (Story 3.7)';
COMMENT ON COLUMN core.batch_jobs.batch_id IS 'Unique batch ID (UUID from application)';
COMMENT ON COLUMN core.batch_jobs.folder_path IS 'Folder being processed';
COMMENT ON COLUMN core.batch_jobs.filters IS 'Applied filters (extensions, date, size)';
COMMENT ON COLUMN core.batch_jobs.status IS 'Current batch status';
COMMENT ON COLUMN core.batch_jobs.categories IS 'Files per category breakdown';
COMMENT ON COLUMN core.batch_jobs.failed_files IS 'List of failed files with errors';
COMMENT ON COLUMN core.batch_jobs.report IS 'Final report summary';

COMMIT;

-- ============================================================================
-- ROLLBACK (manual execution if needed):
-- ============================================================================
-- BEGIN;
-- DROP TRIGGER IF EXISTS trigger_update_batch_jobs_updated_at ON core.batch_jobs;
-- DROP FUNCTION IF EXISTS core.update_batch_jobs_updated_at();
-- DROP TABLE IF EXISTS core.batch_jobs;
-- COMMIT;
