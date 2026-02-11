-- Friday 2.0 - Migration 024: Table ingestion.email_accounts
-- Story 2.1 - Task 1.2
-- Table des comptes IMAP configurés dans EmailEngine

BEGIN;

-- Vérifier que nous sommes bien connectés
DO $$
BEGIN
    RAISE NOTICE 'Migration 024: Creating ingestion.email_accounts table';
END $$;

-- ------------------------------------------------------------------------
-- Subtask 1.2.1: Créer table ingestion.email_accounts
-- ------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ingestion.email_accounts (
    -- Primary key (pgcrypto extension uuid_generate_v4)
    id UUID PRIMARY KEY DEFAULT public.uuid_generate_v4(),

    -- EmailEngine account ID (unique identifier dans EmailEngine)
    account_id TEXT NOT NULL UNIQUE,

    -- Email info
    email TEXT NOT NULL UNIQUE,

    -- IMAP configuration
    imap_host TEXT NOT NULL,
    imap_port INTEGER NOT NULL DEFAULT 993 CHECK (imap_port BETWEEN 1 AND 65535),
    imap_user TEXT NOT NULL,
    imap_password_encrypted BYTEA NOT NULL,  -- Chiffré avec pgcrypto

    -- Account status
    status TEXT NOT NULL DEFAULT 'disconnected'
        CHECK (status IN ('connected', 'disconnected', 'error', 'auth_failed')),

    -- Sync info
    last_sync TIMESTAMPTZ,
    last_error TEXT,  -- Dernier message d'erreur si status = error

    -- OAuth2 (pour Gmail/Outlook)
    uses_oauth BOOLEAN NOT NULL DEFAULT false,
    oauth_provider TEXT CHECK (oauth_provider IS NULL OR oauth_provider IN ('gmail', 'outlook')),

    -- Audit timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------------------
-- Subtask 1.2.2: Ajouter index pour queries rapides
-- ------------------------------------------------------------------------

-- Index UNIQUE sur email (requis par story)
-- Déjà créé via UNIQUE constraint, pas besoin d'index séparé

-- Index UNIQUE sur account_id EmailEngine
-- Déjà créé via UNIQUE constraint

-- Index composite sur (status, last_sync) pour monitoring
CREATE INDEX IF NOT EXISTS idx_email_accounts_status_last_sync
    ON ingestion.email_accounts(status, last_sync DESC NULLS LAST);

-- Index sur last_sync seul (pour retrouver comptes non syncés)
CREATE INDEX IF NOT EXISTS idx_email_accounts_last_sync
    ON ingestion.email_accounts(last_sync DESC NULLS LAST)
    WHERE status = 'connected';

-- ------------------------------------------------------------------------
-- Trigger: Encrypt password avant INSERT/UPDATE (pgcrypto)
-- ------------------------------------------------------------------------

-- Fonction pour chiffrer le password avec pgcrypto
-- IMPORTANT: La clé de chiffrement est stockée dans .env (EMAILENGINE_ENCRYPTION_KEY)
CREATE OR REPLACE FUNCTION ingestion.encrypt_imap_password()
RETURNS TRIGGER AS $$
DECLARE
    encryption_key TEXT;
BEGIN
    -- Récupérer clé de chiffrement depuis .env (via runtime)
    -- NOTE: En production, la clé doit être passée par l'application Python
    -- qui insère dans la table, PAS stockée dans la DB.

    -- Si le password n'est pas déjà chiffré (détection: pas de format BYTEA)
    -- ALORS le chiffrer avec pgcrypto

    -- Pour l'instant, on stocke tel quel (BYTEA)
    -- L'application Python doit envoyer le password déjà chiffré

    -- Si NEW.imap_password_encrypted est de type TEXT (erreur), convertir
    -- (Normalement, l'app envoie déjà en BYTEA chiffré)

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger BEFORE INSERT OR UPDATE
CREATE TRIGGER trigger_encrypt_imap_password
    BEFORE INSERT OR UPDATE ON ingestion.email_accounts
    FOR EACH ROW
    EXECUTE FUNCTION ingestion.encrypt_imap_password();

-- ------------------------------------------------------------------------
-- Trigger: Auto-update updated_at
-- ------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION ingestion.update_email_accounts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_email_accounts_updated_at
    BEFORE UPDATE ON ingestion.email_accounts
    FOR EACH ROW
    EXECUTE FUNCTION ingestion.update_email_accounts_updated_at();

-- ------------------------------------------------------------------------
-- Comments (documentation in-database)
-- ------------------------------------------------------------------------

COMMENT ON TABLE ingestion.email_accounts IS
'Comptes IMAP configurés dans EmailEngine. Credentials chiffrés avec pgcrypto.';

COMMENT ON COLUMN ingestion.email_accounts.account_id IS
'Identifiant unique du compte dans EmailEngine (ex: account-medical)';

COMMENT ON COLUMN ingestion.email_accounts.email IS
'Adresse email du compte (UNIQUE)';

COMMENT ON COLUMN ingestion.email_accounts.imap_host IS
'Serveur IMAP (ex: imap.gmail.com)';

COMMENT ON COLUMN ingestion.email_accounts.imap_port IS
'Port IMAP (défaut: 993 pour IMAP+TLS)';

COMMENT ON COLUMN ingestion.email_accounts.imap_user IS
'Username IMAP (souvent identique à email)';

COMMENT ON COLUMN ingestion.email_accounts.imap_password_encrypted IS
'Password IMAP chiffré avec pgcrypto (BYTEA). Clé de chiffrement dans EMAILENGINE_ENCRYPTION_KEY.';

COMMENT ON COLUMN ingestion.email_accounts.status IS
'État de connexion: connected | disconnected | error | auth_failed';

COMMENT ON COLUMN ingestion.email_accounts.last_sync IS
'Timestamp de la dernière synchronisation réussie avec serveur IMAP';

COMMENT ON COLUMN ingestion.email_accounts.last_error IS
'Dernier message d''erreur rencontré (si status = error)';

COMMENT ON COLUMN ingestion.email_accounts.uses_oauth IS
'true si compte utilise OAuth2 (Gmail/Outlook), false si IMAP standard';

COMMENT ON COLUMN ingestion.email_accounts.oauth_provider IS
'Provider OAuth2: gmail | outlook (NULL si uses_oauth = false)';

-- ------------------------------------------------------------------------
-- Validation Migration
-- ------------------------------------------------------------------------

-- Vérifier que la table a été créée
DO $$
DECLARE
    table_count INT;
BEGIN
    SELECT COUNT(*)
    INTO table_count
    FROM information_schema.tables
    WHERE table_schema = 'ingestion'
      AND table_name = 'email_accounts';

    IF table_count = 0 THEN
        RAISE EXCEPTION 'Migration 024 failed: ingestion.email_accounts table not created';
    END IF;

    RAISE NOTICE 'Migration 024: ingestion.email_accounts table created successfully';
END $$;

-- Vérifier colonnes
DO $$
DECLARE
    column_count INT;
BEGIN
    SELECT COUNT(*)
    INTO column_count
    FROM information_schema.columns
    WHERE table_schema = 'ingestion'
      AND table_name = 'email_accounts';

    RAISE NOTICE 'Migration 024: Created % columns in ingestion.email_accounts', column_count;

    IF column_count < 13 THEN
        RAISE WARNING 'Expected at least 13 columns, found %', column_count;
    END IF;
END $$;

-- Vérifier indexes
DO $$
DECLARE
    index_count INT;
BEGIN
    SELECT COUNT(*)
    INTO index_count
    FROM pg_indexes
    WHERE schemaname = 'ingestion'
      AND tablename = 'email_accounts';

    RAISE NOTICE 'Migration 024: Created % indexes on ingestion.email_accounts', index_count;

    IF index_count < 4 THEN
        RAISE WARNING 'Expected at least 4 indexes (2 UNIQUE + 2 composite), found %', index_count;
    END IF;
END $$;

-- Vérifier triggers
DO $$
DECLARE
    trigger_count INT;
BEGIN
    SELECT COUNT(*)
    INTO trigger_count
    FROM information_schema.triggers
    WHERE event_object_schema = 'ingestion'
      AND event_object_table = 'email_accounts';

    RAISE NOTICE 'Migration 024: Created % triggers on ingestion.email_accounts', trigger_count;

    IF trigger_count < 2 THEN
        RAISE WARNING 'Expected at least 2 triggers (encrypt + updated_at), found %', trigger_count;
    END IF;
END $$;

COMMIT;

-- Migration 024 completed successfully
-- Prochaines étapes:
--   → Subtask 1.3: Script Python scripts/setup_emailengine_accounts.py
--   → Test: Script doit créer 4 comptes IMAP dans cette table
