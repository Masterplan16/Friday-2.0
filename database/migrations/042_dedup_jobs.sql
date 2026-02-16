-- Migration 042: Dedup jobs tracking table
-- Story 3.8: Scan & Deduplication PC
-- Purpose: Audit trail for dedup scan/deletion jobs
--
-- AC7: Securite & rollback - audit trail complet

BEGIN;

-- ============================================================================
-- Table: core.dedup_jobs
-- ============================================================================

CREATE TABLE IF NOT EXISTS core.dedup_jobs (
    dedup_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Scan stats
    total_scanned INT NOT NULL DEFAULT 0,
    duplicate_groups INT NOT NULL DEFAULT 0,

    -- Deletion stats
    files_deleted INT NOT NULL DEFAULT 0,
    files_skipped INT NOT NULL DEFAULT 0,
    files_errors INT NOT NULL DEFAULT 0,
    space_reclaimed_gb DECIMAL(10,2) NOT NULL DEFAULT 0.00,

    -- Report
    csv_report_path TEXT,

    -- Status
    status TEXT NOT NULL DEFAULT 'scanning',
    CHECK (status IN ('scanning', 'report_ready', 'deleting', 'completed', 'failed', 'cancelled')),

    -- Rate limiting: 1 scan actif max
    -- Enforced at application level (not DB constraint)

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_dedup_jobs_status ON core.dedup_jobs(status);
CREATE INDEX IF NOT EXISTS idx_dedup_jobs_created_at ON core.dedup_jobs(created_at DESC);

-- Update trigger (reuse pattern from migration 039)
CREATE OR REPLACE FUNCTION core.update_dedup_jobs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_dedup_jobs_updated_at ON core.dedup_jobs;
CREATE TRIGGER trigger_update_dedup_jobs_updated_at
    BEFORE UPDATE ON core.dedup_jobs
    FOR EACH ROW
    EXECUTE FUNCTION core.update_dedup_jobs_updated_at();

-- Comments
COMMENT ON TABLE core.dedup_jobs IS 'Dedup scan/deletion audit trail (Story 3.8)';
COMMENT ON COLUMN core.dedup_jobs.dedup_id IS 'Unique dedup job ID';
COMMENT ON COLUMN core.dedup_jobs.scan_date IS 'When scan was performed';
COMMENT ON COLUMN core.dedup_jobs.total_scanned IS 'Total files scanned';
COMMENT ON COLUMN core.dedup_jobs.duplicate_groups IS 'Number of duplicate groups found';
COMMENT ON COLUMN core.dedup_jobs.files_deleted IS 'Files successfully deleted';
COMMENT ON COLUMN core.dedup_jobs.files_skipped IS 'Files skipped (safety checks failed)';
COMMENT ON COLUMN core.dedup_jobs.files_errors IS 'Files with deletion errors';
COMMENT ON COLUMN core.dedup_jobs.space_reclaimed_gb IS 'Space reclaimed in GB';
COMMENT ON COLUMN core.dedup_jobs.csv_report_path IS 'Path to CSV dry-run report';
COMMENT ON COLUMN core.dedup_jobs.status IS 'Job status: scanning, report_ready, deleting, completed, failed, cancelled';

COMMIT;

-- ============================================================================
-- ROLLBACK (manual execution if needed):
-- ============================================================================
-- BEGIN;
-- DROP TRIGGER IF EXISTS trigger_update_dedup_jobs_updated_at ON core.dedup_jobs;
-- DROP FUNCTION IF EXISTS core.update_dedup_jobs_updated_at();
-- DROP TABLE IF EXISTS core.dedup_jobs;
-- COMMIT;
