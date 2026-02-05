-- Migration 008: Knowledge embeddings metadata
-- Date: 2026-02-05
-- Description: Métadonnées pour embeddings Qdrant (mapping IDs)

BEGIN;

CREATE TABLE knowledge.embeddings_metadata (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    qdrant_collection VARCHAR(100) NOT NULL,
    qdrant_point_id UUID NOT NULL,
    source_type VARCHAR(50) NOT NULL,
    source_id UUID NOT NULL,
    content_hash VARCHAR(64),
    chunk_index INTEGER,
    total_chunks INTEGER,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT embeddings_qdrant_unique UNIQUE (qdrant_collection, qdrant_point_id)
);

CREATE INDEX idx_embeddings_source ON knowledge.embeddings_metadata(source_type, source_id);
CREATE INDEX idx_embeddings_collection ON knowledge.embeddings_metadata(qdrant_collection);
CREATE INDEX idx_embeddings_hash ON knowledge.embeddings_metadata(content_hash);

COMMENT ON TABLE knowledge.embeddings_metadata IS 'Métadonnées embeddings Qdrant (mapping PostgreSQL ↔ Qdrant)';
COMMENT ON COLUMN knowledge.embeddings_metadata.source_type IS 'Types: email, document, audio_note, thesis_section, etc.';

COMMIT;
