-- Rollback Migration 037: Multi-Casquettes Context & Calendar Conflicts
-- Story 7.3: Multi-casquettes & Conflits Calendrier
-- Date: 2026-02-16
-- Description: Rollback complet de la migration 037
--   - Supprime table knowledge.calendar_conflicts (et ses index automatiquement)
--   - Supprime table core.user_context (et son trigger/fonction automatiquement)

BEGIN;

-- ============================================================================
-- Rollback: Suppression tables et dépendances
-- ============================================================================

-- Supprimer table calendar_conflicts (supprime aussi les index automatiquement)
DROP TABLE IF EXISTS knowledge.calendar_conflicts CASCADE;

-- Supprimer trigger et fonction user_context
DROP TRIGGER IF EXISTS trigger_update_user_context_timestamp ON core.user_context;
DROP FUNCTION IF EXISTS core.update_user_context_timestamp() CASCADE;

-- Supprimer table user_context
DROP TABLE IF EXISTS core.user_context CASCADE;

-- ============================================================================
-- Validation: Vérifier que le rollback est complet
-- ============================================================================

DO $$
BEGIN
    -- Vérifier que calendar_conflicts n'existe plus
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'knowledge'
        AND table_name = 'calendar_conflicts'
    ) THEN
        RAISE EXCEPTION 'Rollback échoué: table knowledge.calendar_conflicts existe encore';
    END IF;

    -- Vérifier que user_context n'existe plus
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'core'
        AND table_name = 'user_context'
    ) THEN
        RAISE EXCEPTION 'Rollback échoué: table core.user_context existe encore';
    END IF;

    -- Vérifier que la fonction n'existe plus
    IF EXISTS (
        SELECT 1 FROM pg_proc
        WHERE proname = 'update_user_context_timestamp'
    ) THEN
        RAISE EXCEPTION 'Rollback échoué: fonction update_user_context_timestamp existe encore';
    END IF;

    RAISE NOTICE 'Rollback migration 037 effectué avec succès';
END $$;

COMMIT;
