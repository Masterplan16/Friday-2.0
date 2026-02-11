-- Migration 032: Ajouter type email_task dans core.tasks
-- Story 2.7: Extraction tâches depuis emails
-- Date: 2026-02-11
-- Author: Friday 2.0 Dev Team
--
-- Contexte:
--   AC2: Création tâches dans core.tasks avec référence email
--   Nouveau type distinct de "reminder" (Story 4.6) pour tracker
--   les tâches automatiquement extraites des emails
--
-- Modifications:
--   1. Ajouter 'email_task' au CHECK constraint de tasks.type
--   2. Ajouter commentaire sur nouveau type
--   3. Vérifier que colonne due_date existe (Story 4.7)
--
-- Dépendances:
--   - Story 1.2: core.tasks table créée (migration 003)
--   - Story 4.7: colonne due_date ajoutée (si existe)
--
-- Tests:
--   - Insertion tâche email_task doit réussir
--   - Insertion autre type invalide doit échouer
--   - Référence email_id dans payload doit être valide JSON

BEGIN;

-- =============================================================================
-- ÉTAPE 1: Vérifier que table core.tasks existe
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'core' AND table_name = 'tasks'
    ) THEN
        RAISE EXCEPTION 'Table core.tasks does not exist. Run migration 003 first.';
    END IF;
END $$;

-- =============================================================================
-- ÉTAPE 2: Ajouter 'email_task' au CHECK constraint type
-- =============================================================================

-- Drop ancien constraint si existe
ALTER TABLE core.tasks DROP CONSTRAINT IF EXISTS tasks_type_check;

-- Ajouter nouveau constraint avec email_task
-- NOTE: Inclut 'reminder' (Story 4.6) et 'email_task' (Story 2.7)
ALTER TABLE core.tasks
    ADD CONSTRAINT tasks_type_check
    CHECK (type IN ('manual', 'reminder', 'email_task'));

COMMENT ON CONSTRAINT tasks_type_check ON core.tasks IS
    'Types de tâches supportés:
     - manual: Tâche créée manuellement via Telegram (default)
     - reminder: Tâche créée depuis conversation avec agent (Story 4.6)
     - email_task: Tâche extraite automatiquement depuis email (Story 2.7)';

-- =============================================================================
-- ÉTAPE 3: Vérifier/Ajouter colonne due_date si n'existe pas
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'core'
          AND table_name = 'tasks'
          AND column_name = 'due_date'
    ) THEN
        -- Ajouter colonne due_date si pas déjà créée par Story 4.7
        ALTER TABLE core.tasks ADD COLUMN due_date TIMESTAMPTZ;

        COMMENT ON COLUMN core.tasks.due_date IS
            'Date d''échéance de la tâche (optionnelle).
             Extraite automatiquement depuis email pour type=email_task.
             Convertit dates relatives (demain, jeudi prochain) en dates absolues.';

        RAISE NOTICE 'Column core.tasks.due_date created (Story 2.7)';
    ELSE
        RAISE NOTICE 'Column core.tasks.due_date already exists (Story 4.7)';
    END IF;
END $$;

-- =============================================================================
-- ÉTAPE 4: Ajouter commentaires type email_task
-- =============================================================================

COMMENT ON COLUMN core.tasks.type IS
    'Type de tâche:
     - manual: Créée manuellement via Telegram
     - reminder: Créée depuis conversation agent (Story 4.6)
     - email_task: Extraite automatiquement depuis email (Story 2.7)';

COMMENT ON COLUMN core.tasks.payload IS
    'Métadonnées JSON spécifiques au type de tâche.

     Pour type=email_task:
     {
       "email_id": "uuid",                 -- UUID email source (ingestion.emails_raw.id)
       "email_subject": "Re: [ANONYMIZED]", -- Sujet anonymisé via Presidio
       "confidence": 0.85,                 -- Confidence détection (0.0-1.0)
       "context": "Tâche détectée car...", -- Contexte extraction
       "priority_keywords": ["urgent"]     -- Mots-clés ayant justifié priorité
     }';

-- =============================================================================
-- ÉTAPE 5: Ajouter index partiel pour email_task (performance)
-- =============================================================================

-- Index pour retrouver rapidement les tâches extraites depuis emails
CREATE INDEX IF NOT EXISTS idx_tasks_email_task
    ON core.tasks(type, status)
    WHERE type = 'email_task';

COMMENT ON INDEX core.idx_tasks_email_task IS
    'Index partiel pour tâches extraites depuis emails.
     Optimise requêtes: SELECT * FROM core.tasks WHERE type = ''email_task'' AND status = ''pending''';

-- =============================================================================
-- ÉTAPE 6: Exemple d'insertion (validation)
-- =============================================================================

DO $$
DECLARE
    test_task_id UUID;
BEGIN
    -- Test insertion tâche email_task
    INSERT INTO core.tasks (
        name,
        type,
        status,
        priority,
        due_date,
        payload
    ) VALUES (
        'Test tâche email_task - Migration 032',
        'email_task',
        'pending',
        2, -- normal priority
        NOW() + INTERVAL '2 days',
        jsonb_build_object(
            'email_id', gen_random_uuid()::text,
            'email_subject', 'Test email anonymized',
            'confidence', 0.85,
            'context', 'Test insertion migration 032',
            'priority_keywords', jsonb_build_array('test')
        )
    ) RETURNING id INTO test_task_id;

    RAISE NOTICE 'Test task created successfully: %', test_task_id;

    -- Cleanup test
    DELETE FROM core.tasks WHERE id = test_task_id;

    RAISE NOTICE 'Migration 032 completed successfully';
END $$;

COMMIT;
