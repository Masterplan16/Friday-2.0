-- Migration 015: User Settings
-- Story 1.9 - Table paramètres utilisateur (onboarding, préférences)

BEGIN;

-- =====================================================================
-- Table: core.user_settings
-- =====================================================================
-- Stocke les paramètres et préférences de chaque utilisateur Telegram.

CREATE TABLE IF NOT EXISTS core.user_settings (
    user_id BIGINT PRIMARY KEY,  -- User ID Telegram (PK naturelle)
    username TEXT,  -- Username Telegram (ex: @antonio)
    full_name TEXT,  -- Nom complet (First + Last Name)
    onboarding_sent BOOLEAN NOT NULL DEFAULT FALSE,
    onboarding_sent_at TIMESTAMPTZ,
    preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index pour recherche par onboarding_sent (pour détection nouveaux users)
CREATE INDEX IF NOT EXISTS idx_user_settings_onboarding
ON core.user_settings(onboarding_sent)
WHERE NOT onboarding_sent;

-- Index GIN pour recherche dans préférences JSONB
CREATE INDEX IF NOT EXISTS idx_user_settings_preferences
ON core.user_settings USING GIN (preferences);

-- Commentaires
COMMENT ON TABLE core.user_settings IS 'Paramètres et préférences utilisateurs Telegram';
COMMENT ON COLUMN core.user_settings.user_id IS 'User ID Telegram (identifiant unique)';
COMMENT ON COLUMN core.user_settings.username IS 'Username Telegram (@username)';
COMMENT ON COLUMN core.user_settings.full_name IS 'Nom complet (First + Last Name)';
COMMENT ON COLUMN core.user_settings.onboarding_sent IS 'Indique si le message d''onboarding a été envoyé (idempotence)';
COMMENT ON COLUMN core.user_settings.onboarding_sent_at IS 'Date d''envoi du message d''onboarding';
COMMENT ON COLUMN core.user_settings.preferences IS 'Préférences utilisateur (JSONB, extensible)';

-- =====================================================================
-- Fonction trigger: update_updated_at
-- =====================================================================
-- Met à jour automatiquement la colonne updated_at lors d'un UPDATE.

CREATE OR REPLACE FUNCTION core.update_user_settings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger sur UPDATE
CREATE TRIGGER trigger_update_user_settings_updated_at
BEFORE UPDATE ON core.user_settings
FOR EACH ROW
EXECUTE FUNCTION core.update_user_settings_updated_at();

-- =====================================================================
-- Données initiales: Antonio (user principal)
-- =====================================================================
-- Note: Le user_id réel d'Antonio sera inséré au premier message reçu.
-- Cette ligne est un placeholder pour documentation.

-- INSERT INTO core.user_settings (user_id, username, full_name, onboarding_sent)
-- VALUES (123456789, '@antonio', 'Antonio Lopez', FALSE)
-- ON CONFLICT (user_id) DO NOTHING;
-- ☝️ Commenté - sera inséré automatiquement au runtime

COMMIT;
