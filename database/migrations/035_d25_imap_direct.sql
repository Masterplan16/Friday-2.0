-- Friday 2.0 - Migration 035: D25 IMAP Direct (remplace EmailEngine)
-- Decision D25 (2026-02-13): EmailEngine retiré, IMAP direct via aioimaplib
--
-- Changes:
--   1. Ajouter colonnes SMTP + IDLE à ingestion.email_accounts
--   2. Mettre à jour commentaires (retirer references EmailEngine)
--   3. Renommer EMAILENGINE_ENCRYPTION_KEY -> PGP_ENCRYPTION_KEY dans commentaires

BEGIN;

DO $$
BEGIN
    RAISE NOTICE 'Migration 035: D25 IMAP Direct - Adding SMTP + IDLE columns';
END $$;

-- ========================================================================
-- 1. Ajouter colonnes SMTP pour envoi direct (D25)
-- ========================================================================

ALTER TABLE ingestion.email_accounts
    ADD COLUMN IF NOT EXISTS smtp_host TEXT,
    ADD COLUMN IF NOT EXISTS smtp_port INTEGER DEFAULT 587
        CHECK (smtp_port IS NULL OR smtp_port BETWEEN 1 AND 65535),
    ADD COLUMN IF NOT EXISTS use_idle BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS auth_method TEXT NOT NULL DEFAULT 'app_password'
        CHECK (auth_method IN ('app_password', 'oauth2'));

-- ========================================================================
-- 2. Mettre à jour commentaires (retirer references EmailEngine)
-- ========================================================================

COMMENT ON TABLE ingestion.email_accounts IS
'Comptes IMAP/SMTP configures. D25: IMAP direct (aioimaplib) remplace EmailEngine. Credentials chiffres avec pgcrypto.';

COMMENT ON COLUMN ingestion.email_accounts.account_id IS
'Identifiant unique du compte IMAP (ex: account_medical)';

COMMENT ON COLUMN ingestion.email_accounts.imap_password_encrypted IS
'Password IMAP chiffre avec pgcrypto (BYTEA). Cle de chiffrement dans PGP_ENCRYPTION_KEY.';

COMMENT ON COLUMN ingestion.email_accounts.smtp_host IS
'Serveur SMTP pour envoi (ex: smtp.gmail.com). NULL si envoi non configure.';

COMMENT ON COLUMN ingestion.email_accounts.smtp_port IS
'Port SMTP (defaut: 587 pour STARTTLS)';

COMMENT ON COLUMN ingestion.email_accounts.use_idle IS
'true = IMAP IDLE (push, 2-5s latence). false = polling (60s intervalle, pour ProtonMail Bridge)';

COMMENT ON COLUMN ingestion.email_accounts.auth_method IS
'Methode auth: app_password (Day 1) ou oauth2 (futur Gmail XOAUTH2)';

-- ========================================================================
-- 3. Validation
-- ========================================================================

DO $$
DECLARE
    col_count INT;
BEGIN
    SELECT COUNT(*)
    INTO col_count
    FROM information_schema.columns
    WHERE table_schema = 'ingestion'
      AND table_name = 'email_accounts'
      AND column_name IN ('smtp_host', 'smtp_port', 'use_idle', 'auth_method');

    IF col_count < 4 THEN
        RAISE EXCEPTION 'Migration 035 failed: expected 4 new columns, found %', col_count;
    END IF;

    RAISE NOTICE 'Migration 035: D25 IMAP Direct columns added successfully (% new columns)', col_count;
END $$;

COMMIT;
