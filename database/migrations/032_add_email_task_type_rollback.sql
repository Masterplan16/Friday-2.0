-- Migration 032 ROLLBACK: Retirer type email_task de core.tasks
-- Story 2.7: Email Task Extraction
-- Date: 2026-02-11
-- Author: Friday 2.0 Dev Team
--
-- ATTENTION: Ce rollback supprime TOUTES les tâches de type email_task
-- et retire la colonne due_date si elle a été créée par cette migration.
--
-- Usage:
--   psql -U friday -d friday -f 032_add_email_task_type_rollback.sql
--
-- Prérequis:
--   - Backup PostgreSQL récent recommandé
--   - Vérifier qu'aucune tâche email_task critique n'est en attente

BEGIN;

-- =============================================================================
-- ÉTAPE 1: Supprimer toutes les tâches email_task (M2 fix: cleanup avant rollback)
-- =============================================================================

DO $$
DECLARE
    deleted_count INT;
BEGIN
    DELETE FROM core.tasks WHERE type = 'email_task';
    GET DIAGNOSTICS deleted_count = ROW_COUNT;

    IF deleted_count > 0 THEN
        RAISE NOTICE '% tâches email_task supprimées', deleted_count;
    ELSE
        RAISE NOTICE 'Aucune tâche email_task à supprimer';
    END IF;
END $$;

-- =============================================================================
-- ÉTAPE 2: Supprimer index partiel idx_tasks_email_task
-- =============================================================================

DROP INDEX IF EXISTS core.idx_tasks_email_task;
RAISE NOTICE 'Index idx_tasks_email_task supprimé';

-- =============================================================================
-- ÉTAPE 3: Restaurer CHECK constraint sans email_task
-- =============================================================================

-- Drop constraint actuel
ALTER TABLE core.tasks DROP CONSTRAINT IF EXISTS tasks_type_check;

-- Restaurer constraint original (Story 1.2 + Story 4.6)
ALTER TABLE core.tasks
    ADD CONSTRAINT tasks_type_check
    CHECK (type IN ('manual', 'reminder'));

COMMENT ON CONSTRAINT tasks_type_check ON core.tasks IS
    'Types de tâches supportés:
     - manual: Tâche créée manuellement via Telegram (default)
     - reminder: Tâche créée depuis conversation avec agent (Story 4.6)
     NOTE: email_task retiré par rollback migration 032';

RAISE NOTICE 'CHECK constraint tasks_type_check restauré (sans email_task)';

-- =============================================================================
-- ÉTAPE 4: Supprimer colonne due_date SI créée par migration 032
-- =============================================================================

-- NOTE: Ne supprimer due_date QUE si elle a été ajoutée par migration 032
-- Si Story 4.7 a déjà ajouté due_date avant, NE PAS la supprimer

DO $$
BEGIN
    -- Vérifier si colonne existe
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'core'
          AND table_name = 'tasks'
          AND column_name = 'due_date'
    ) THEN
        -- ATTENTION: Cette étape est optionnelle
        -- Décommenter seulement si certain que due_date n'est pas utilisée ailleurs

        -- ALTER TABLE core.tasks DROP COLUMN due_date;
        -- RAISE NOTICE 'Colonne core.tasks.due_date supprimée';

        RAISE WARNING 'Colonne due_date existe - rollback MANUEL requis si ajoutée par 032 uniquement';
        RAISE NOTICE 'Pour supprimer: ALTER TABLE core.tasks DROP COLUMN due_date;';
    ELSE
        RAISE NOTICE 'Colonne due_date n''existe pas (rien à supprimer)';
    END IF;
END $$;

-- =============================================================================
-- ÉTAPE 5: Restaurer commentaires colonnes
-- =============================================================================

COMMENT ON COLUMN core.tasks.type IS
    'Type de tâche:
     - manual: Créée manuellement via Telegram
     - reminder: Créée depuis conversation agent (Story 4.6)
     NOTE: email_task retiré par rollback migration 032';

COMMENT ON COLUMN core.tasks.payload IS
    'Métadonnées JSON spécifiques au type de tâche.

     Pour type=reminder:
     {
       "conversation_id": "uuid",
       "reminder_text": "...",
       "recurrence": "daily|weekly|monthly"
     }

     NOTE: Payload email_task retiré par rollback migration 032';

RAISE NOTICE 'Migration 032 rollback completed successfully';

COMMIT;

-- =============================================================================
-- POST-ROLLBACK VERIFICATION
-- =============================================================================

-- Vérifier aucune tâche email_task restante
DO $$
DECLARE
    remaining_count INT;
BEGIN
    SELECT COUNT(*) INTO remaining_count
    FROM core.tasks
    WHERE type = 'email_task';

    IF remaining_count > 0 THEN
        RAISE WARNING '% tâches email_task restantes après rollback', remaining_count;
    ELSE
        RAISE NOTICE 'Vérification OK: Aucune tâche email_task restante';
    END IF;
END $$;
