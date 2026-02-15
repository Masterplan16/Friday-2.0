-- Rollback Migration 036: Support EVENT entity_type
-- Date: 2026-02-15
-- Story: 7.1 Detection Evenements
-- Description: Rollback complet migration 036 (contraintes, index, commentaires EVENT)

BEGIN;

-- ============================================================================
-- SUPPRESSION INDEX
-- ============================================================================

-- Supprimer index status événements
DROP INDEX IF EXISTS knowledge.idx_entities_event_status;

-- Supprimer index composé casquette + date
DROP INDEX IF EXISTS knowledge.idx_entities_event_casquette_date;

-- Supprimer index temporel événements
DROP INDEX IF EXISTS knowledge.idx_entities_event_date;

-- ============================================================================
-- SUPPRESSION CONTRAINTES
-- ============================================================================

-- Supprimer contrainte CHECK EVENT properties
ALTER TABLE knowledge.entities
DROP CONSTRAINT IF EXISTS check_event_properties;

-- ============================================================================
-- RESTAURATION COMMENTAIRES ORIGINAUX
-- ============================================================================

-- Restaurer commentaire original table entities (migration 007)
COMMENT ON TABLE knowledge.entities IS
'Entités extraites (NER: personnes, orgas, lieux, concepts)';

-- Restaurer commentaire original table entity_relations (migration 007)
COMMENT ON TABLE knowledge.entity_relations IS
'Relations entre entités (graphe de connaissances)';

COMMIT;
