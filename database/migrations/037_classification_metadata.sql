-- Migration 037: Classification Metadata (Story 3.2 - Task 7)
-- Ajoute colonnes de classification à ingestion.document_metadata

BEGIN;

-- Ajouter colonnes de classification (Task 7.2)
ALTER TABLE ingestion.document_metadata
    ADD COLUMN IF NOT EXISTS final_path TEXT,
    ADD COLUMN IF NOT EXISTS classification_category TEXT,
    ADD COLUMN IF NOT EXISTS classification_subcategory TEXT,
    ADD COLUMN IF NOT EXISTS classification_confidence FLOAT
        CHECK (classification_confidence >= 0.0 AND classification_confidence <= 1.0);

-- Validation catégorie (Task 7.2)
ALTER TABLE ingestion.document_metadata
    ADD CONSTRAINT check_classification_category
    CHECK (classification_category IS NULL OR classification_category IN ('pro', 'finance', 'universite', 'recherche', 'perso'));

-- Validation périmètre finance (AC6 - Anti-contamination)
ALTER TABLE ingestion.document_metadata
    ADD CONSTRAINT check_finance_subcategory
    CHECK (
        classification_category != 'finance' OR
        classification_subcategory IN ('selarl', 'scm', 'sci_ravas', 'sci_malbosc', 'personal')
    );

-- Index pour requêtes rapides (Task 7.3)
CREATE INDEX IF NOT EXISTS idx_document_metadata_classification_category
    ON ingestion.document_metadata(classification_category);

CREATE INDEX IF NOT EXISTS idx_document_metadata_classification_subcategory
    ON ingestion.document_metadata(classification_subcategory);

CREATE INDEX IF NOT EXISTS idx_document_metadata_final_path
    ON ingestion.document_metadata(final_path);

-- Commentaires
COMMENT ON COLUMN ingestion.document_metadata.final_path IS 'Chemin final du document dans l''arborescence';
COMMENT ON COLUMN ingestion.document_metadata.classification_category IS 'Catégorie principale (pro, finance, universite, recherche, perso)';
COMMENT ON COLUMN ingestion.document_metadata.classification_subcategory IS 'Sous-catégorie (obligatoire pour finance)';
COMMENT ON COLUMN ingestion.document_metadata.classification_confidence IS 'Score confidence classification Claude';

COMMIT;
