-- Migration 009: Knowledge thesis tracking
-- Date: 2026-02-05
-- Description: Suivi thèses doctorat (Tuteur + Check Thèse modules)

BEGIN;

CREATE TABLE knowledge.thesis_projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    student_name VARCHAR(255) NOT NULL,
    thesis_title TEXT NOT NULL,
    specialty VARCHAR(255),
    university VARCHAR(255),
    director_name VARCHAR(255),
    codirector_name VARCHAR(255),
    start_date DATE,
    expected_defense_date DATE,
    status VARCHAR(50) NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'defended', 'abandoned')),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_thesis_status ON knowledge.thesis_projects(status);
CREATE INDEX idx_thesis_expected_defense ON knowledge.thesis_projects(expected_defense_date) WHERE expected_defense_date IS NOT NULL;

CREATE TRIGGER thesis_updated_at
    BEFORE UPDATE ON knowledge.thesis_projects
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at();

COMMENT ON TABLE knowledge.thesis_projects IS 'Projets thèses suivis (Tuteur Thèse module)';

-- Table versions thèse
CREATE TABLE knowledge.thesis_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thesis_id UUID NOT NULL REFERENCES knowledge.thesis_projects(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    document_id UUID REFERENCES ingestion.documents(id),
    comments TEXT,
    structure_check_status VARCHAR(20),
    methodology_check_status VARCHAR(20),
    statistics_check_status VARCHAR(20),
    reference_check_status VARCHAR(20),
    feedback JSONB DEFAULT '{}',
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    CONSTRAINT thesis_versions_unique UNIQUE (thesis_id, version_number)
);

CREATE INDEX idx_thesis_versions_thesis ON knowledge.thesis_versions(thesis_id);
CREATE INDEX idx_thesis_versions_submitted ON knowledge.thesis_versions(submitted_at DESC);

COMMENT ON TABLE knowledge.thesis_versions IS 'Versions thèses avec feedback (pré-correction méthodologique)';

COMMIT;
