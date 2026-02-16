-- Migration 007: Knowledge graph (nodes and edges)
-- Date: 2026-02-11
-- Description: Graphe de connaissances avec 10 types de nœuds et 14 types de relations
-- Supersedes: 007_knowledge_entities.sql (sauvegardé en 007_knowledge_entities_OLD.sql.bak)

BEGIN;

-- Table des nœuds du graphe (10 types)
CREATE TABLE knowledge.nodes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type VARCHAR(50) NOT NULL,  -- person, email, document, event, task, entity, conversation, transaction, file, reminder
    name TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_from TIMESTAMPTZ,  -- Pour historisation/versioning
    valid_to TIMESTAMPTZ,    -- NULL = version actuelle
    source VARCHAR(50),      -- Module Friday ayant créé le nœud (email, archiviste, finance, etc.)

    -- Contrainte: type doit être l'un des 10 types valides
    CONSTRAINT valid_node_type CHECK (type IN (
        'person', 'email', 'document', 'event', 'task',
        'entity', 'conversation', 'transaction', 'file', 'reminder'
    ))
);

-- Index performants pour requêtes fréquentes
CREATE INDEX idx_nodes_type ON knowledge.nodes(type);
CREATE INDEX idx_nodes_created_at ON knowledge.nodes(created_at DESC);
CREATE INDEX idx_nodes_valid_to ON knowledge.nodes(valid_to) WHERE valid_to IS NULL;  -- Index partiel pour versions actives
CREATE INDEX idx_nodes_source ON knowledge.nodes(source);
CREATE INDEX idx_nodes_metadata ON knowledge.nodes USING GIN(metadata);  -- Pour requêtes JSON

-- Trigger pour mise à jour automatique de updated_at
CREATE TRIGGER nodes_updated_at
    BEFORE UPDATE ON knowledge.nodes
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at();

COMMENT ON TABLE knowledge.nodes IS 'Nœuds du graphe de connaissances (10 types: person, email, document, event, task, entity, conversation, transaction, file, reminder)';
COMMENT ON COLUMN knowledge.nodes.type IS 'Type de nœud (validé par contrainte CHECK)';
COMMENT ON COLUMN knowledge.nodes.metadata IS 'Propriétés spécifiques au type (JSONB flexible)';
COMMENT ON COLUMN knowledge.nodes.valid_from IS 'Début de validité (historisation)';
COMMENT ON COLUMN knowledge.nodes.valid_to IS 'Fin de validité (NULL = version actuelle)';
COMMENT ON COLUMN knowledge.nodes.source IS 'Module Friday ayant créé le nœud';

-- Table des arêtes du graphe (14 types de relations)
CREATE TABLE knowledge.edges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    from_node_id UUID NOT NULL REFERENCES knowledge.nodes(id) ON DELETE CASCADE,
    to_node_id UUID NOT NULL REFERENCES knowledge.nodes(id) ON DELETE CASCADE,
    relation_type VARCHAR(100) NOT NULL,  -- sent_by, received_by, attached_to, mentions, etc.
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,

    -- Contrainte: type de relation doit être l'un des 14 types valides
    CONSTRAINT valid_relation_type CHECK (relation_type IN (
        'sent_by', 'received_by', 'attached_to', 'mentions', 'related_to',
        'assigned_to', 'created_from', 'scheduled', 'references', 'part_of',
        'paid_with', 'belongs_to', 'reminds_about', 'supersedes'
    )),

    -- Éviter doublons de relations identiques
    CONSTRAINT unique_edge UNIQUE (from_node_id, to_node_id, relation_type)
);

-- Index performants pour traversée du graphe
CREATE INDEX idx_edges_from_node ON knowledge.edges(from_node_id);
CREATE INDEX idx_edges_to_node ON knowledge.edges(to_node_id);
CREATE INDEX idx_edges_relation_type ON knowledge.edges(relation_type);
CREATE INDEX idx_edges_created_at ON knowledge.edges(created_at DESC);
CREATE INDEX idx_edges_valid_to ON knowledge.edges(valid_to) WHERE valid_to IS NULL;
CREATE INDEX idx_edges_metadata ON knowledge.edges USING GIN(metadata);

COMMENT ON TABLE knowledge.edges IS 'Relations du graphe de connaissances (14 types de relations sémantiques)';
COMMENT ON COLUMN knowledge.edges.relation_type IS 'Type de relation (validé par contrainte CHECK)';
COMMENT ON COLUMN knowledge.edges.metadata IS 'Propriétés spécifiques à la relation (JSONB flexible)';
COMMENT ON COLUMN knowledge.edges.valid_from IS 'Début de validité de la relation';
COMMENT ON COLUMN knowledge.edges.valid_to IS 'Fin de validité (NULL = relation active)';

COMMIT;
