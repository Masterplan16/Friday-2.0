-- Friday 2.0 - Migration 025: Table ingestion.emails
-- Story 2.1 - Task 3 (Consumer pipeline)
-- Table des emails reçus (anonymisés RGPD)

BEGIN;

-- Vérifier que nous sommes bien connectés
DO $$
BEGIN
    RAISE NOTICE 'Migration 025: Creating ingestion.emails table';
END $$;

-- ------------------------------------------------------------------------
-- Créer table ingestion.emails (emails anonymisés)
-- ------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ingestion.emails (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT public.uuid_generate_v4(),

    -- EmailEngine identifiers
    account_id TEXT NOT NULL,  -- Référence vers ingestion.email_accounts
    message_id TEXT NOT NULL,  -- EmailEngine message ID (unique par account)

    -- Email metadata (anonymisé Presidio)
    from_anon TEXT NOT NULL,  -- Expéditeur anonymisé [EMAIL_1], [PERSON_1]
    to_anon TEXT,  -- Destinataires anonymisés
    subject_anon TEXT NOT NULL,  -- Sujet anonymisé
    body_anon TEXT NOT NULL,  -- Corps email anonymisé (texte brut)

    -- Classification LLM (Story 2.2)
    category TEXT DEFAULT 'inbox',  -- Day 1 stub: "inbox", Story 2.2: médical/faculté/recherche/perso
    confidence REAL DEFAULT 0.5 CHECK (confidence BETWEEN 0.0 AND 1.0),  -- Confiance classification

    -- Metadata
    has_attachments BOOLEAN NOT NULL DEFAULT false,
    attachment_count INTEGER DEFAULT 0 CHECK (attachment_count >= 0),
    priority TEXT DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),

    -- Timestamps
    received_at TIMESTAMPTZ NOT NULL,  -- Date réception email (header Date)
    processed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- Date traitement pipeline
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Constraint unique: un email par account + message_id
    CONSTRAINT unique_account_message UNIQUE (account_id, message_id)
);

-- ------------------------------------------------------------------------
-- Table ingestion.emails_raw (email original chiffré pgcrypto)
-- ------------------------------------------------------------------------
-- RGPD: Email original (avec PII) stocké chiffré, jamais envoyé au LLM

CREATE TABLE IF NOT EXISTS ingestion.emails_raw (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT public.uuid_generate_v4(),

    -- Référence vers ingestion.emails (email anonymisé)
    email_id UUID NOT NULL REFERENCES ingestion.emails(id) ON DELETE CASCADE,

    -- Email original chiffré (pgcrypto)
    from_encrypted BYTEA NOT NULL,
    to_encrypted BYTEA,
    subject_encrypted BYTEA NOT NULL,
    body_encrypted BYTEA NOT NULL,

    -- Headers complets (chiffrés)
    headers_encrypted BYTEA,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Constraint unique: un seul raw par email
    CONSTRAINT unique_email_raw UNIQUE (email_id)
);

-- ------------------------------------------------------------------------
-- Indexes pour queries rapides
-- ------------------------------------------------------------------------

-- Index principal: retrouver emails récents par compte
CREATE INDEX IF NOT EXISTS idx_emails_account_received
    ON ingestion.emails(account_id, received_at DESC);

-- Index: retrouver emails par catégorie
CREATE INDEX IF NOT EXISTS idx_emails_category
    ON ingestion.emails(category, received_at DESC);

-- Index: retrouver emails non traités (si processed_at NULL)
CREATE INDEX IF NOT EXISTS idx_emails_processed
    ON ingestion.emails(processed_at DESC NULLS FIRST);

-- Index: retrouver emails avec pièces jointes
CREATE INDEX IF NOT EXISTS idx_emails_attachments
    ON ingestion.emails(has_attachments, received_at DESC)
    WHERE has_attachments = true;

-- Index: recherche full-text sur subject anonymisé (optionnel, ajouté si besoin)
-- CREATE INDEX IF NOT EXISTS idx_emails_subject_fulltext
--     ON ingestion.emails USING gin(to_tsvector('french', subject_anon));

-- Index emails_raw: retrouver raw email depuis email_id
CREATE INDEX IF NOT EXISTS idx_emails_raw_email_id
    ON ingestion.emails_raw(email_id);

-- ------------------------------------------------------------------------
-- Foreign key constraint vers email_accounts
-- ------------------------------------------------------------------------

-- Ajouter FK constraint vers ingestion.email_accounts
ALTER TABLE ingestion.emails
    ADD CONSTRAINT fk_emails_account
    FOREIGN KEY (account_id)
    REFERENCES ingestion.email_accounts(account_id)
    ON DELETE CASCADE;

-- ------------------------------------------------------------------------
-- Comments (documentation in-database)
-- ------------------------------------------------------------------------

COMMENT ON TABLE ingestion.emails IS
'Emails reçus (anonymisés Presidio). Version safe pour traitement LLM.';

COMMENT ON TABLE ingestion.emails_raw IS
'Emails originaux chiffrés (pgcrypto). Contient PII, JAMAIS envoyé au LLM.';

COMMENT ON COLUMN ingestion.emails.account_id IS
'ID du compte EmailEngine (FK vers ingestion.email_accounts)';

COMMENT ON COLUMN ingestion.emails.message_id IS
'ID unique du message dans EmailEngine';

COMMENT ON COLUMN ingestion.emails.from_anon IS
'Expéditeur anonymisé par Presidio (ex: [EMAIL_1], [PERSON_1])';

COMMENT ON COLUMN ingestion.emails.subject_anon IS
'Sujet anonymisé par Presidio';

COMMENT ON COLUMN ingestion.emails.body_anon IS
'Corps email anonymisé par Presidio (texte brut, pas HTML)';

COMMENT ON COLUMN ingestion.emails.category IS
'Catégorie classification LLM: médical | faculté | recherche | perso | inbox (stub)';

COMMENT ON COLUMN ingestion.emails.confidence IS
'Confiance classification LLM (0.0-1.0)';

COMMENT ON COLUMN ingestion.emails.received_at IS
'Date réception email (timestamp header Date)';

COMMENT ON COLUMN ingestion.emails.processed_at IS
'Date traitement pipeline (anonymisation + classification + stockage)';

COMMENT ON COLUMN ingestion.emails_raw.email_id IS
'Référence vers ingestion.emails (email anonymisé correspondant)';

COMMENT ON COLUMN ingestion.emails_raw.from_encrypted IS
'Expéditeur original chiffré (pgcrypto BYTEA)';

-- ------------------------------------------------------------------------
-- Validation Migration
-- ------------------------------------------------------------------------

-- Vérifier que les tables ont été créées
DO $$
DECLARE
    emails_count INT;
    emails_raw_count INT;
BEGIN
    SELECT COUNT(*)
    INTO emails_count
    FROM information_schema.tables
    WHERE table_schema = 'ingestion'
      AND table_name = 'emails';

    SELECT COUNT(*)
    INTO emails_raw_count
    FROM information_schema.tables
    WHERE table_schema = 'ingestion'
      AND table_name = 'emails_raw';

    IF emails_count = 0 THEN
        RAISE EXCEPTION 'Migration 025 failed: ingestion.emails table not created';
    END IF;

    IF emails_raw_count = 0 THEN
        RAISE EXCEPTION 'Migration 025 failed: ingestion.emails_raw table not created';
    END IF;

    RAISE NOTICE 'Migration 025: ingestion.emails and ingestion.emails_raw tables created successfully';
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
      AND (tablename = 'emails' OR tablename = 'emails_raw');

    RAISE NOTICE 'Migration 025: Created % indexes on ingestion.emails + emails_raw', index_count;

    IF index_count < 5 THEN
        RAISE WARNING 'Expected at least 5 indexes, found %', index_count;
    END IF;
END $$;

-- Vérifier foreign key constraint
DO $$
DECLARE
    fk_count INT;
BEGIN
    SELECT COUNT(*)
    INTO fk_count
    FROM information_schema.table_constraints
    WHERE table_schema = 'ingestion'
      AND table_name = 'emails'
      AND constraint_type = 'FOREIGN KEY';

    RAISE NOTICE 'Migration 025: Created % foreign keys on ingestion.emails', fk_count;

    IF fk_count < 1 THEN
        RAISE WARNING 'Expected at least 1 FK constraint (account_id), found %', fk_count;
    END IF;
END $$;

COMMIT;

-- Migration 025 completed successfully
-- Prochaines étapes:
--   → Task 3: Consumer Python doit insérer dans ingestion.emails
--   → Task 3: Email raw chiffré doit être inséré dans ingestion.emails_raw
