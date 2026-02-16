-- ============================================================
-- Migration 038: Add document_id FK to knowledge.embeddings
-- ============================================================
-- Story: 3.3 - Task 3
-- Date: 2026-02-16
-- Description: Ajoute colonne document_id dans knowledge.embeddings
--              avec foreign key vers ingestion.document_metadata
--              + index B-tree pour jointures rapides
-- ============================================================

BEGIN;

-- 1. Ajouter colonne document_id (nullable temporairement pour migration)
ALTER TABLE knowledge.embeddings
ADD COLUMN IF NOT EXISTS document_id UUID;

-- 2. Créer index UNIQUE sur document_id (requis pour ON CONFLICT dans pipeline)
CREATE UNIQUE INDEX IF NOT EXISTS idx_embeddings_document_id
ON knowledge.embeddings (document_id)
WHERE document_id IS NOT NULL;

-- 3. Ajouter foreign key vers ingestion.document_metadata
-- Note: Colonne reste nullable car embeddings peuvent exister pour nodes non-documents
ALTER TABLE knowledge.embeddings
ADD CONSTRAINT fk_embeddings_document_id
FOREIGN KEY (document_id)
REFERENCES ingestion.document_metadata (document_id)
ON DELETE CASCADE;

-- 4. Optimiser paramètres HNSW pour performance (Task 3.2)
-- m=16 : Nombre de connexions par nœud (default 16 = bon balance)
-- ef_construction=64 : Qualité build (higher = meilleur recall mais build plus lent)
-- Note: Ces paramètres sont définis lors de CREATE INDEX, pas modifiables après
-- Si besoin de changer : DROP INDEX + CREATE INDEX avec nouveaux params

-- Index HNSW existant (migration 008) = idx_embeddings_vector
COMMENT ON INDEX knowledge.idx_embeddings_vector IS
'HNSW index pour recherche semantique rapide. Params: m=16, ef_construction=64 (pgvector 0.8.0)';

-- 5. Configuration PostgreSQL recommandée (Task 3.5)
-- maintenance_work_mem = 2GB pour build HNSW rapide
-- Note: Ce paramètre doit être configuré dans postgresql.conf ou via ALTER SYSTEM
-- ALTER SYSTEM SET maintenance_work_mem = '2GB';
-- SELECT pg_reload_conf();

COMMENT ON COLUMN knowledge.embeddings.document_id IS
'FK vers ingestion.document_metadata. NULL si embedding pour node non-document.';

COMMIT;

-- ============================================================
-- Rollback (si nécessaire)
-- ============================================================
-- BEGIN;
-- ALTER TABLE knowledge.embeddings DROP CONSTRAINT IF EXISTS fk_embeddings_document_id;
-- DROP INDEX IF EXISTS idx_embeddings_document_id;
-- ALTER TABLE knowledge.embeddings DROP COLUMN IF EXISTS document_id;
-- COMMIT;
