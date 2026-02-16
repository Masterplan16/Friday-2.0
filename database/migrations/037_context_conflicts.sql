-- Migration 037: Multi-Casquettes Context & Calendar Conflicts
-- Story 7.3: Multi-casquettes & Conflits Calendrier
-- Date: 2026-02-16
-- Description:
--   - Créer table core.user_context (singleton) pour gérer le contexte casquette actuel
--   - Créer table knowledge.calendar_conflicts pour tracker les conflits d'agenda
--   - Index pour optimiser les requêtes de conflits non résolus
--   - Trigger pour mettre à jour automatiquement last_updated_at

BEGIN;

-- ============================================================================
-- Table: core.user_context (Singleton - AC1)
-- ============================================================================
-- Stocke le contexte casquette actuel de l'utilisateur unique
-- Singleton garanti par contrainte CHECK (id = 1)
-- ============================================================================

CREATE TABLE IF NOT EXISTS core.user_context (
    id INT PRIMARY KEY DEFAULT 1,
    current_casquette TEXT CHECK (current_casquette IN ('medecin', 'enseignant', 'chercheur')),
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT NOT NULL DEFAULT 'system' CHECK (updated_by IN ('system', 'manual')),

    -- Contrainte singleton: seulement 1 ligne possible
    CONSTRAINT singleton_user_context CHECK (id = 1)
);

-- Commentaires documentation
COMMENT ON TABLE core.user_context IS 'Contexte casquette actuel du Mainteneur (singleton)';
COMMENT ON COLUMN core.user_context.id IS 'ID fixe à 1 (singleton)';
COMMENT ON COLUMN core.user_context.current_casquette IS 'Casquette active: medecin, enseignant, chercheur, ou NULL (auto-detect)';
COMMENT ON COLUMN core.user_context.last_updated_at IS 'Timestamp dernière mise à jour contexte';
COMMENT ON COLUMN core.user_context.updated_by IS 'Source du changement: system (auto-detect) ou manual (commande Telegram)';

-- Seed initial: Contexte NULL (auto-detect)
INSERT INTO core.user_context (id, current_casquette, updated_by)
VALUES (1, NULL, 'system')
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- Trigger: Mise à jour automatique last_updated_at (AC1)
-- ============================================================================

CREATE OR REPLACE FUNCTION core.update_user_context_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_user_context_timestamp
    BEFORE UPDATE ON core.user_context
    FOR EACH ROW
    EXECUTE FUNCTION core.update_user_context_timestamp();

COMMENT ON FUNCTION core.update_user_context_timestamp() IS 'Met à jour automatiquement last_updated_at sur modification user_context';

-- ============================================================================
-- Table: knowledge.calendar_conflicts (AC4, AC7)
-- ============================================================================
-- Historique des conflits calendrier détectés entre événements
-- Conflit = 2 événements qui se chevauchent temporellement avec casquettes différentes
-- ============================================================================

CREATE TABLE IF NOT EXISTS knowledge.calendar_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event1_id UUID NOT NULL REFERENCES knowledge.entities(id) ON DELETE CASCADE,
    event2_id UUID NOT NULL REFERENCES knowledge.entities(id) ON DELETE CASCADE,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    overlap_minutes INT NOT NULL CHECK (overlap_minutes > 0),
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at TIMESTAMPTZ,
    resolution_action TEXT CHECK (resolution_action IN ('cancel', 'move', 'ignore')),

    -- Contrainte: event1 et event2 doivent être différents
    CONSTRAINT check_different_events CHECK (event1_id != event2_id)
);

-- Commentaires documentation
COMMENT ON TABLE knowledge.calendar_conflicts IS 'Historique conflits calendrier (chevauchement événements casquettes différentes)';
COMMENT ON COLUMN knowledge.calendar_conflicts.event1_id IS 'Référence premier événement en conflit';
COMMENT ON COLUMN knowledge.calendar_conflicts.event2_id IS 'Référence second événement en conflit';
COMMENT ON COLUMN knowledge.calendar_conflicts.detected_at IS 'Timestamp détection conflit';
COMMENT ON COLUMN knowledge.calendar_conflicts.overlap_minutes IS 'Durée chevauchement en minutes';
COMMENT ON COLUMN knowledge.calendar_conflicts.resolved IS 'Conflit résolu (TRUE) ou actif (FALSE)';
COMMENT ON COLUMN knowledge.calendar_conflicts.resolved_at IS 'Timestamp résolution conflit';
COMMENT ON COLUMN knowledge.calendar_conflicts.resolution_action IS 'Action prise: cancel (annulation), move (déplacement), ignore (ignorer)';

-- ============================================================================
-- Index: Optimisation requêtes conflits non résolus (AC7)
-- ============================================================================

-- Index partiel: seulement les conflits non résolus (plus fréquemment consultés)
CREATE INDEX IF NOT EXISTS idx_conflicts_unresolved
    ON knowledge.calendar_conflicts(detected_at DESC)
    WHERE resolved = FALSE;

-- Index pour recherche par événement (utile pour détection doublons)
CREATE INDEX IF NOT EXISTS idx_conflicts_event1
    ON knowledge.calendar_conflicts(event1_id);

CREATE INDEX IF NOT EXISTS idx_conflicts_event2
    ON knowledge.calendar_conflicts(event2_id);

-- Index composite pour déduplication conflits (même paire événements)
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflicts_unique_pair
    ON knowledge.calendar_conflicts(
        LEAST(event1_id, event2_id),
        GREATEST(event1_id, event2_id)
    )
    WHERE resolved = FALSE;

COMMENT ON INDEX idx_conflicts_unresolved IS 'Optimise requêtes conflits non résolus (commande /conflits)';
COMMENT ON INDEX idx_conflicts_event1 IS 'Optimise recherche conflits par event1_id';
COMMENT ON INDEX idx_conflicts_event2 IS 'Optimise recherche conflits par event2_id';
COMMENT ON INDEX idx_conflicts_unique_pair IS 'Prévient doublons conflits (même paire événements non résolus)';

-- ============================================================================
-- Validation: Vérifier que les tables sont créées correctement
-- ============================================================================

DO $$
BEGIN
    -- Vérifier core.user_context existe et a 1 ligne
    IF NOT EXISTS (SELECT 1 FROM core.user_context WHERE id = 1) THEN
        RAISE EXCEPTION 'Table core.user_context mal initialisée (seed manquant)';
    END IF;

    -- Vérifier knowledge.calendar_conflicts existe
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'knowledge'
        AND table_name = 'calendar_conflicts'
    ) THEN
        RAISE EXCEPTION 'Table knowledge.calendar_conflicts non créée';
    END IF;

    RAISE NOTICE 'Migration 037 appliquée avec succès';
END $$;

COMMIT;
