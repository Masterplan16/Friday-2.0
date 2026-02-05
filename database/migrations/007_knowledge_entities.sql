-- Migration 007: Knowledge entities
-- Date: 2026-02-05
-- Description: Entités extraites (personnes, organisations, lieux, concepts)

BEGIN;

CREATE TABLE knowledge.entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(500) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    aliases TEXT[] DEFAULT '{}',
    description TEXT,
    properties JSONB DEFAULT '{}',
    confidence FLOAT,
    source_type VARCHAR(50),
    source_id UUID,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mention_count INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_entities_name ON knowledge.entities(name);
CREATE INDEX idx_entities_type ON knowledge.entities(entity_type);
CREATE INDEX idx_entities_aliases ON knowledge.entities USING GIN(aliases);
CREATE INDEX idx_entities_last_seen ON knowledge.entities(last_seen_at DESC);

CREATE TRIGGER entities_updated_at
    BEFORE UPDATE ON knowledge.entities
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at();

COMMENT ON TABLE knowledge.entities IS 'Entités extraites (NER: personnes, orgas, lieux, concepts)';
COMMENT ON COLUMN knowledge.entities.entity_type IS 'Types: PERSON, ORG, LOC, PRODUCT, EVENT, CONCEPT, etc.';

-- Table relations entre entités
CREATE TABLE knowledge.entity_relations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_entity_id UUID NOT NULL REFERENCES knowledge.entities(id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES knowledge.entities(id) ON DELETE CASCADE,
    relation_type VARCHAR(100) NOT NULL,
    confidence FLOAT,
    properties JSONB DEFAULT '{}',
    source_type VARCHAR(50),
    source_id UUID,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mention_count INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT entity_relations_unique UNIQUE (source_entity_id, target_entity_id, relation_type)
);

CREATE INDEX idx_relations_source ON knowledge.entity_relations(source_entity_id);
CREATE INDEX idx_relations_target ON knowledge.entity_relations(target_entity_id);
CREATE INDEX idx_relations_type ON knowledge.entity_relations(relation_type);

CREATE TRIGGER relations_updated_at
    BEFORE UPDATE ON knowledge.entity_relations
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at();

COMMENT ON TABLE knowledge.entity_relations IS 'Relations entre entités (graphe de connaissances)';

COMMIT;
