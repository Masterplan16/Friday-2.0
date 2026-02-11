-- Friday 2.0 - Migration 019: Table backup_metadata
-- Story 1.12 - Task 2.3
-- Table d'audit des backups PostgreSQL chiffrés

BEGIN;

-- Vérifier que nous sommes bien connectés
DO $$
BEGIN
    RAISE NOTICE 'Migration 019: Creating core.backup_metadata table';
END $$;

-- ------------------------------------------------------------------------
-- Subtask 2.3.1: Créer table core.backup_metadata
-- ------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS core.backup_metadata (
    -- Primary key (pgcrypto extension uuid_generate_v4)
    id UUID PRIMARY KEY DEFAULT public.uuid_generate_v4(),

    -- Backup info
    backup_date TIMESTAMPTZ NOT NULL,
    filename TEXT NOT NULL UNIQUE,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    checksum_sha256 TEXT NOT NULL CHECK (length(checksum_sha256) = 64),

    -- Encryption
    encrypted_with_age BOOLEAN NOT NULL DEFAULT true,

    -- Sync status
    synced_to_pc BOOLEAN NOT NULL DEFAULT false,
    pc_arrival_time TIMESTAMPTZ,

    -- Retention policy
    retention_policy TEXT NOT NULL DEFAULT 'keep_7_days'
        CHECK (retention_policy IN ('keep_7_days', 'keep_30_days', 'keep_forever')),

    -- Restore testing (pour AC5 - Task 3.2)
    last_restore_test TIMESTAMPTZ,
    restore_test_status TEXT
        CHECK (restore_test_status IS NULL OR restore_test_status IN ('success', 'failed', 'pending')),

    -- Audit timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------------------
-- Subtask 2.3.2: Ajouter index sur backup_date pour queries rapides
-- ------------------------------------------------------------------------

-- Index principal pour queries par date
CREATE INDEX IF NOT EXISTS idx_backup_metadata_backup_date
    ON core.backup_metadata(backup_date DESC);

-- Index pour retrouver backups non syncés rapidement
CREATE INDEX IF NOT EXISTS idx_backup_metadata_sync_status
    ON core.backup_metadata(synced_to_pc, backup_date DESC)
    WHERE synced_to_pc = false;

-- Index pour policies retention (cleanup job)
CREATE INDEX IF NOT EXISTS idx_backup_metadata_retention
    ON core.backup_metadata(retention_policy, backup_date);

-- Index pour restore tests
CREATE INDEX IF NOT EXISTS idx_backup_metadata_restore_test
    ON core.backup_metadata(last_restore_test DESC NULLS LAST);

-- ------------------------------------------------------------------------
-- Trigger auto-update updated_at
-- ------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.update_backup_metadata_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_backup_metadata_updated_at
    BEFORE UPDATE ON core.backup_metadata
    FOR EACH ROW
    EXECUTE FUNCTION core.update_backup_metadata_updated_at();

-- ------------------------------------------------------------------------
-- Comments (documentation in-database)
-- ------------------------------------------------------------------------

COMMENT ON TABLE core.backup_metadata IS
'Métadonnées des backups PostgreSQL chiffrés avec age. Un enregistrement par backup créé.';

COMMENT ON COLUMN core.backup_metadata.backup_date IS
'Date/heure de création du backup (UTC timezone)';

COMMENT ON COLUMN core.backup_metadata.filename IS
'Nom fichier backup chiffré (ex: friday_backup_2026-02-10_0300.dump.age)';

COMMENT ON COLUMN core.backup_metadata.size_bytes IS
'Taille fichier backup chiffré en bytes';

COMMENT ON COLUMN core.backup_metadata.checksum_sha256 IS
'Checksum SHA256 du fichier backup (avant chiffrement age)';

COMMENT ON COLUMN core.backup_metadata.encrypted_with_age IS
'Indique si backup chiffré avec age (toujours true pour sécurité)';

COMMENT ON COLUMN core.backup_metadata.synced_to_pc IS
'Indique si backup a été synchronisé vers PC Mainteneur via Tailscale rsync';

COMMENT ON COLUMN core.backup_metadata.pc_arrival_time IS
'TIMESTAMPTZ de l''arrivée du backup sur PC (après sync rsync réussi)';

COMMENT ON COLUMN core.backup_metadata.retention_policy IS
'Politique de rétention: keep_7_days (défaut VPS), keep_30_days (PC), keep_forever (archives)';

COMMENT ON COLUMN core.backup_metadata.last_restore_test IS
'Date du dernier test de restore (Task 3.2 - test mensuel)';

COMMENT ON COLUMN core.backup_metadata.restore_test_status IS
'Résultat du dernier test restore: success | failed | pending';

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
    WHERE table_schema = 'core'
      AND table_name = 'backup_metadata';

    IF table_count = 0 THEN
        RAISE EXCEPTION 'Migration 019 failed: core.backup_metadata table not created';
    END IF;

    RAISE NOTICE 'Migration 019: core.backup_metadata table created successfully';
END $$;

-- Vérifier indexes
DO $$
DECLARE
    index_count INT;
BEGIN
    SELECT COUNT(*)
    INTO index_count
    FROM pg_indexes
    WHERE schemaname = 'core'
      AND tablename = 'backup_metadata';

    RAISE NOTICE 'Migration 019: Created % indexes on core.backup_metadata', index_count;

    IF index_count < 4 THEN
        RAISE WARNING 'Expected at least 4 indexes, found %', index_count;
    END IF;
END $$;

COMMIT;

-- Migration 019 completed successfully
-- Prochaines étapes:
--   → Task 2.4: Créer workflow n8n backup-daily.json
--   → Test: bash scripts/backup.sh (devrait logger dans core.backup_metadata)
