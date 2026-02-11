-- Migration 032: Writing Examples for Few-Shot Learning
-- Story 2.5 - Table core.writing_examples pour apprentissage style rédactionnel
-- Stocke les exemples de brouillons emails approuvés pour few-shot learning

BEGIN;

-- =====================================================================
-- Table: core.writing_examples
-- =====================================================================
-- Stocke les exemples de style rédactionnel du Mainteneur pour
-- few-shot learning lors de la génération de brouillons emails.
--
-- Les brouillons approuvés et envoyés sont stockés automatiquement
-- pour améliorer progressivement la qualité des brouillons futurs.

CREATE TABLE IF NOT EXISTS core.writing_examples (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email_type VARCHAR(50) NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_by VARCHAR(100) NOT NULL DEFAULT 'Mainteneur',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Contrainte: email_type limité aux 4 catégories valides
    CONSTRAINT check_writing_examples_email_type
        CHECK (email_type IN ('professional', 'personal', 'medical', 'academic'))
);

-- =====================================================================
-- Indexes
-- =====================================================================

-- Index composite pour queries optimisées:
-- SELECT * FROM core.writing_examples
-- WHERE email_type = 'professional' AND sent_by = 'Mainteneur'
-- ORDER BY created_at DESC LIMIT 5;
CREATE INDEX IF NOT EXISTS idx_writing_examples_email_type_sent_by
ON core.writing_examples (email_type, sent_by, created_at DESC);

-- =====================================================================
-- Trigger: update_updated_at
-- =====================================================================
-- Met à jour automatiquement la colonne updated_at lors d'un UPDATE.

CREATE OR REPLACE FUNCTION core.update_writing_examples_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_writing_examples_updated_at
BEFORE UPDATE ON core.writing_examples
FOR EACH ROW
EXECUTE FUNCTION core.update_writing_examples_updated_at();

-- =====================================================================
-- Commentaires
-- =====================================================================

COMMENT ON TABLE core.writing_examples IS
'Exemples de style rédactionnel pour few-shot learning dans génération brouillons emails';

COMMENT ON COLUMN core.writing_examples.id IS
'Identifiant unique UUID';

COMMENT ON COLUMN core.writing_examples.email_type IS
'Type d''email: professional, personal, medical, academic';

COMMENT ON COLUMN core.writing_examples.subject IS
'Sujet de l''email exemple';

COMMENT ON COLUMN core.writing_examples.body IS
'Corps de l''email exemple (texte complet)';

COMMENT ON COLUMN core.writing_examples.sent_by IS
'Auteur de l''email (toujours Mainteneur pour few-shot learning)';

COMMENT ON COLUMN core.writing_examples.created_at IS
'Date de création de l''exemple (horodatage envoi email)';

COMMENT ON COLUMN core.writing_examples.updated_at IS
'Date de dernière modification (mis à jour automatiquement)';

COMMENT ON CONSTRAINT check_writing_examples_email_type ON core.writing_examples IS
'Contrainte: email_type doit être professional, personal, medical ou academic';

-- =====================================================================
-- Documentation Schema JSONB pour core.user_settings.preferences
-- =====================================================================
-- Cette migration documente le schema attendu pour writing_style
-- dans core.user_settings.preferences (créé dans migration 015).
--
-- Schema JSONB writing_style:
-- {
--   "writing_style": {
--     "tone": "formal",           // Values: "formal" | "informal"
--     "tutoiement": false,        // Values: true | false
--     "verbosity": "concise"      // Values: "concise" | "detailed"
--   }
-- }
--
-- Utilisation:
-- - Day 1: Valeurs par défaut (formal, no tutoiement, concise)
-- - Futur: Configurable via commandes Telegram /settings
--
-- Exemple INSERT:
-- INSERT INTO core.user_settings (user_id, username, preferences)
-- VALUES (
--     123456789,
--     '@mainteneur',
--     '{"writing_style": {"tone": "formal", "tutoiement": false, "verbosity": "concise"}}'::jsonb
-- );
--
-- Exemple UPDATE:
-- UPDATE core.user_settings
-- SET preferences = preferences || '{"writing_style": {"tone": "informal"}}'::jsonb
-- WHERE user_id = 123456789;
--
-- Exemple SELECT:
-- SELECT preferences->'writing_style'->>'tone' AS tone
-- FROM core.user_settings
-- WHERE user_id = 123456789;

COMMIT;
