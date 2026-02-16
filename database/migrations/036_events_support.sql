-- Migration 036: Support EVENT entity_type
-- Date: 2026-02-15
-- Story: 7.1 Detection Evenements
-- Description: Support complet pour entités EVENT (agenda, calendrier)
-- AC2: Contraintes, index, commentaires pour entity_type='EVENT'

BEGIN;

-- ============================================================================
-- CONTRAINTES EVENT
-- ============================================================================

-- AC2: Contrainte CHECK pour EVENT entity_type
-- Garantit que les entités EVENT ont les propriétés obligatoires
ALTER TABLE knowledge.entities
ADD CONSTRAINT check_event_properties
CHECK (
  entity_type != 'EVENT' OR (
    -- Propriétés obligatoires pour EVENT
    properties ? 'start_datetime' AND
    properties ? 'status' AND
    -- Valeurs valides pour status
    (properties->>'status') IN ('proposed', 'confirmed', 'cancelled')
  )
);

COMMENT ON CONSTRAINT check_event_properties ON knowledge.entities IS
'Contrainte EVENT: start_datetime + status (proposed|confirmed|cancelled) obligatoires';

-- ============================================================================
-- INDEX OPTIMISATIONS
-- ============================================================================

-- AC2: Index sur start_datetime pour requêtes temporelles événements
-- Permet recherche rapide: "événements à venir", "événements du jour", etc.
CREATE INDEX idx_entities_event_date
ON knowledge.entities ((properties->>'start_datetime')::timestamptz)
WHERE entity_type = 'EVENT';

COMMENT ON INDEX knowledge.idx_entities_event_date IS
'Index temporel événements - Optimise recherches par date (upcoming, today, week)';

-- Index composé pour recherches filtrées par casquette
-- Permet: "événements médecin à venir", "réunions enseignant cette semaine"
CREATE INDEX idx_entities_event_casquette_date
ON knowledge.entities (
  (properties->>'casquette'),
  ((properties->>'start_datetime')::timestamptz)
)
WHERE entity_type = 'EVENT';

COMMENT ON INDEX knowledge.idx_entities_event_casquette_date IS
'Index casquette + date - Optimise filtrage multi-casquettes (medecin|enseignant|chercheur)';

-- Index sur status pour filtrage événements proposés/confirmés
-- Permet: "événements en attente validation", "événements confirmés"
CREATE INDEX idx_entities_event_status
ON knowledge.entities ((properties->>'status'))
WHERE entity_type = 'EVENT';

COMMENT ON INDEX knowledge.idx_entities_event_status IS
'Index status événements - Optimise filtrage proposed|confirmed|cancelled';

-- ============================================================================
-- COMMENTAIRES DOCUMENTATION
-- ============================================================================

-- Documentation structure JSONB properties pour EVENT
COMMENT ON TABLE knowledge.entities IS
'Entités extraites (NER: personnes, orgas, lieux, concepts).
Types supportés: PERSON, ORG, LOC, PRODUCT, EVENT, CONCEPT.

EVENT properties (JSONB):
{
  "start_datetime": "2026-02-15T14:30:00" (ISO 8601, OBLIGATOIRE),
  "end_datetime": "2026-02-15T15:00:00" (ISO 8601, optionnel),
  "location": "Cabinet Dr Dupont" (string, optionnel),
  "participants": ["Dr Dupont", "Dr Martin"] (array, optionnel),
  "event_type": "medical" (string: medical|meeting|deadline|conference|personal),
  "casquette": "medecin" (OBLIGATOIRE: medecin|enseignant|chercheur),
  "email_id": "uuid-email-source" (UUID, source email),
  "confidence": 0.92 (float 0.0-1.0, confiance extraction),
  "status": "proposed" (OBLIGATOIRE: proposed|confirmed|cancelled),
  "calendar_id": null (UUID Google Calendar ID, Story 7.2)
}';

-- ============================================================================
-- RELATIONS TYPES EVENT
-- ============================================================================

-- Documentation types relations EVENT supportées
COMMENT ON TABLE knowledge.entity_relations IS
'Relations entre entités (graphe de connaissances).

Relations EVENT supportées:
- EVENT → MENTIONED_IN → EMAIL (source_entity_id=event, target_entity_id=email)
- EVENT → HAS_PARTICIPANT → PERSON (participants événement)
- EVENT → LOCATED_AT → LOCATION (lieu événement)
- EVENT → BELONGS_TO → CASQUETTE (classification multi-casquettes)';

COMMIT;
