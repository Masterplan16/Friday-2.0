-- Migration 008: Knowledge embeddings avec pgvector
-- Date: 2026-02-09
-- Description: Stockage embeddings directement dans PostgreSQL via pgvector (D19)
-- Remplace: Qdrant externe (Decision D19 - pgvector Day 1, Qdrant si >300k vecteurs)

BEGIN;

-- Extension pgvector pour recherche sémantique
CREATE EXTENSION IF NOT EXISTS vector;

-- Table embeddings : stocke vecteurs directement dans PostgreSQL
CREATE TABLE IF NOT EXISTS knowledge.embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_type VARCHAR(50) NOT NULL,
    source_id UUID NOT NULL,
    content_hash VARCHAR(64),
    chunk_index INTEGER DEFAULT 0,
    total_chunks INTEGER DEFAULT 1,
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index HNSW pour recherche sémantique (cosine distance)
-- Note: build peut prendre du temps sur gros volumes, prévoir maintenance window
CREATE INDEX IF NOT EXISTS idx_embeddings_vector ON knowledge.embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Index métadonnées pour filtrage
CREATE INDEX IF NOT EXISTS idx_embeddings_source ON knowledge.embeddings(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_hash ON knowledge.embeddings(content_hash);

COMMENT ON TABLE knowledge.embeddings IS 'Embeddings vectoriels pgvector (D19 - remplace Qdrant)';
COMMENT ON COLUMN knowledge.embeddings.embedding IS 'Vecteur 1024 dims (configurable selon modèle embeddings)';
COMMENT ON COLUMN knowledge.embeddings.source_type IS 'Types: email, document, audio_note, thesis_section, etc.';

COMMIT;
