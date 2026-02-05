-- Migration 002: Core users table
-- Date: 2026-02-05
-- Description: Table utilisateurs (Antonio Day 1, extension famille envisageable)

BEGIN;

CREATE TABLE core.users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(50) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    telegram_id BIGINT UNIQUE NOT NULL,
    telegram_username VARCHAR(100),
    role VARCHAR(20) NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user', 'readonly')),
    active BOOLEAN NOT NULL DEFAULT true,
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index
CREATE INDEX idx_users_telegram_id ON core.users(telegram_id);
CREATE INDEX idx_users_active ON core.users(active) WHERE active = true;

-- Commentaires
COMMENT ON TABLE core.users IS 'Utilisateurs Friday 2.0 (Antonio Day 1)';
COMMENT ON COLUMN core.users.telegram_id IS 'ID Telegram unique (canal unique de communication)';
COMMENT ON COLUMN core.users.preferences IS 'Préférences utilisateur (JSON: langue, timezone, notifications)';

-- Fonction update timestamp
CREATE OR REPLACE FUNCTION core.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_updated_at
    BEFORE UPDATE ON core.users
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at();

COMMIT;
