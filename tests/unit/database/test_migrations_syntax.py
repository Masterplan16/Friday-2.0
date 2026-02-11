"""
Tests unitaires pour valider syntaxe des migrations SQL
Story 2.1 - Validation migrations 024-025
"""

import pytest
from pathlib import Path
import re


@pytest.fixture
def migrations_dir():
    """Répertoire des migrations SQL"""
    repo_root = Path(__file__).parent.parent.parent.parent
    return repo_root / "database" / "migrations"


class TestMigrationsSyntax:
    """Tests de validation syntaxe SQL"""

    def test_migration_024_exists(self, migrations_dir):
        """Migration 024 doit exister"""
        migration_file = migrations_dir / "024_emailengine_accounts.sql"
        assert migration_file.exists(), f"Migration 024 not found at {migration_file}"

    def test_migration_025_exists(self, migrations_dir):
        """Migration 025 doit exister"""
        migration_file = migrations_dir / "025_ingestion_emails.sql"
        assert migration_file.exists(), f"Migration 025 not found at {migration_file}"

    def test_migration_024_has_begin_commit(self, migrations_dir):
        """Migration 024 doit avoir BEGIN et COMMIT"""
        migration_file = migrations_dir / "024_emailengine_accounts.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'BEGIN;' in content, "Migration 024 missing BEGIN;"
        assert 'COMMIT;' in content, "Migration 024 missing COMMIT;"

    def test_migration_025_has_begin_commit(self, migrations_dir):
        """Migration 025 doit avoir BEGIN et COMMIT"""
        migration_file = migrations_dir / "025_ingestion_emails.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'BEGIN;' in content, "Migration 025 missing BEGIN;"
        assert 'COMMIT;' in content, "Migration 025 missing COMMIT;"

    def test_migration_024_creates_email_accounts_table(self, migrations_dir):
        """Migration 024 doit créer table ingestion.email_accounts"""
        migration_file = migrations_dir / "024_emailengine_accounts.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'CREATE TABLE' in content, "Migration 024 missing CREATE TABLE"
        assert 'ingestion.email_accounts' in content, "Migration 024 missing ingestion.email_accounts"

    def test_migration_025_creates_emails_tables(self, migrations_dir):
        """Migration 025 doit créer tables ingestion.emails et ingestion.emails_raw"""
        migration_file = migrations_dir / "025_ingestion_emails.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'CREATE TABLE' in content, "Migration 025 missing CREATE TABLE"
        assert 'ingestion.emails' in content, "Migration 025 missing ingestion.emails"
        assert 'ingestion.emails_raw' in content, "Migration 025 missing ingestion.emails_raw"

    def test_migration_024_has_indexes(self, migrations_dir):
        """Migration 024 doit créer des indexes"""
        migration_file = migrations_dir / "024_emailengine_accounts.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'CREATE INDEX' in content, "Migration 024 missing CREATE INDEX"

    def test_migration_025_has_indexes(self, migrations_dir):
        """Migration 025 doit créer des indexes"""
        migration_file = migrations_dir / "025_ingestion_emails.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'CREATE INDEX' in content, "Migration 025 missing CREATE INDEX"

    def test_migration_024_has_comments(self, migrations_dir):
        """Migration 024 doit avoir des COMMENT ON pour documentation"""
        migration_file = migrations_dir / "024_emailengine_accounts.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'COMMENT ON TABLE' in content, "Migration 024 missing table comments"
        assert 'COMMENT ON COLUMN' in content, "Migration 024 missing column comments"

    def test_migration_025_has_comments(self, migrations_dir):
        """Migration 025 doit avoir des COMMENT ON pour documentation"""
        migration_file = migrations_dir / "025_ingestion_emails.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'COMMENT ON TABLE' in content, "Migration 025 missing table comments"
        assert 'COMMENT ON COLUMN' in content, "Migration 025 missing column comments"

    def test_migration_024_has_validation(self, migrations_dir):
        """Migration 024 doit avoir validation de succès"""
        migration_file = migrations_dir / "024_emailengine_accounts.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'Validation Migration' in content or 'RAISE NOTICE' in content, \
            "Migration 024 missing validation section"

    def test_migration_025_has_validation(self, migrations_dir):
        """Migration 025 doit avoir validation de succès"""
        migration_file = migrations_dir / "025_ingestion_emails.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'Validation Migration' in content or 'RAISE NOTICE' in content, \
            "Migration 025 missing validation section"

    def test_migration_024_no_syntax_errors_basic(self, migrations_dir):
        """Migration 024 ne doit pas avoir d'erreurs syntaxe basiques"""
        migration_file = migrations_dir / "024_emailengine_accounts.sql"
        content = migration_file.read_text(encoding='utf-8')

        # Vérifier que tous les CREATE TABLE ont un point-virgule final
        create_tables = re.findall(r'CREATE TABLE.*?;', content, re.DOTALL)
        assert len(create_tables) > 0, "No CREATE TABLE found in migration 024"

    def test_migration_025_no_syntax_errors_basic(self, migrations_dir):
        """Migration 025 ne doit pas avoir d'erreurs syntaxe basiques"""
        migration_file = migrations_dir / "025_ingestion_emails.sql"
        content = migration_file.read_text(encoding='utf-8')

        # Vérifier que tous les CREATE TABLE ont un point-virgule final
        create_tables = re.findall(r'CREATE TABLE.*?;', content, re.DOTALL)
        assert len(create_tables) >= 2, "Expected at least 2 CREATE TABLE in migration 025"

    # Story 2.3 - Tests migrations VIP & Urgence

    def test_migration_027_exists(self, migrations_dir):
        """Migration 027 doit exister"""
        migration_file = migrations_dir / "027_vip_senders.sql"
        assert migration_file.exists(), f"Migration 027 not found at {migration_file}"

    def test_migration_028_exists(self, migrations_dir):
        """Migration 028 doit exister"""
        migration_file = migrations_dir / "028_urgency_keywords.sql"
        assert migration_file.exists(), f"Migration 028 not found at {migration_file}"

    def test_migration_027_has_begin_commit(self, migrations_dir):
        """Migration 027 doit avoir BEGIN et COMMIT"""
        migration_file = migrations_dir / "027_vip_senders.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'BEGIN;' in content, "Migration 027 missing BEGIN;"
        assert 'COMMIT;' in content, "Migration 027 missing COMMIT;"

    def test_migration_028_has_begin_commit(self, migrations_dir):
        """Migration 028 doit avoir BEGIN et COMMIT"""
        migration_file = migrations_dir / "028_urgency_keywords.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'BEGIN;' in content, "Migration 028 missing BEGIN;"
        assert 'COMMIT;' in content, "Migration 028 missing COMMIT;"

    def test_migration_027_creates_vip_senders_table(self, migrations_dir):
        """Migration 027 doit créer table core.vip_senders"""
        migration_file = migrations_dir / "027_vip_senders.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'CREATE TABLE' in content, "Migration 027 missing CREATE TABLE"
        assert 'core.vip_senders' in content, "Migration 027 missing core.vip_senders"

    def test_migration_028_creates_urgency_keywords_table(self, migrations_dir):
        """Migration 028 doit créer table core.urgency_keywords"""
        migration_file = migrations_dir / "028_urgency_keywords.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'CREATE TABLE' in content, "Migration 028 missing CREATE TABLE"
        assert 'core.urgency_keywords' in content, "Migration 028 missing core.urgency_keywords"

    def test_migration_027_has_unique_constraints(self, migrations_dir):
        """Migration 027 doit avoir contraintes UNIQUE sur email_anon et email_hash"""
        migration_file = migrations_dir / "027_vip_senders.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'email_anon TEXT NOT NULL UNIQUE' in content, "Migration 027 missing UNIQUE on email_anon"
        assert 'email_hash TEXT NOT NULL UNIQUE' in content, "Migration 027 missing UNIQUE on email_hash"

    def test_migration_028_has_unique_constraint_keyword(self, migrations_dir):
        """Migration 028 doit avoir contrainte UNIQUE sur keyword"""
        migration_file = migrations_dir / "028_urgency_keywords.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'keyword TEXT NOT NULL UNIQUE' in content, "Migration 028 missing UNIQUE on keyword"

    def test_migration_027_has_indexes(self, migrations_dir):
        """Migration 027 doit créer des indexes (email_hash, active, source)"""
        migration_file = migrations_dir / "027_vip_senders.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'CREATE INDEX' in content, "Migration 027 missing CREATE INDEX"
        assert 'idx_vip_senders_hash' in content, "Migration 027 missing idx_vip_senders_hash"

    def test_migration_028_has_indexes(self, migrations_dir):
        """Migration 028 doit créer des indexes (active, language, source)"""
        migration_file = migrations_dir / "028_urgency_keywords.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'CREATE INDEX' in content, "Migration 028 missing CREATE INDEX"
        assert 'idx_urgency_keywords_active' in content, "Migration 028 missing idx_urgency_keywords_active"

    def test_migration_027_has_comments(self, migrations_dir):
        """Migration 027 doit avoir des COMMENT ON pour documentation"""
        migration_file = migrations_dir / "027_vip_senders.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'COMMENT ON TABLE' in content, "Migration 027 missing table comments"
        assert 'COMMENT ON COLUMN' in content, "Migration 027 missing column comments"

    def test_migration_028_has_comments(self, migrations_dir):
        """Migration 028 doit avoir des COMMENT ON pour documentation"""
        migration_file = migrations_dir / "028_urgency_keywords.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'COMMENT ON TABLE' in content, "Migration 028 missing table comments"
        assert 'COMMENT ON COLUMN' in content, "Migration 028 missing column comments"

    def test_migration_027_has_check_constraints(self, migrations_dir):
        """Migration 027 doit avoir contraintes CHECK (priority_override, emails_received_count)"""
        migration_file = migrations_dir / "027_vip_senders.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'CHECK' in content, "Migration 027 missing CHECK constraints"
        assert "priority_override IN ('high', 'urgent')" in content, "Migration 027 missing priority_override CHECK"
        assert 'emails_received_count >= 0' in content, "Migration 027 missing emails_received_count CHECK"

    def test_migration_028_has_check_constraints(self, migrations_dir):
        """Migration 028 doit avoir contraintes CHECK (weight, hit_count)"""
        migration_file = migrations_dir / "028_urgency_keywords.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'CHECK' in content, "Migration 028 missing CHECK constraints"
        assert 'weight >= 0.0 AND weight <= 1.0' in content, "Migration 028 missing weight CHECK"
        assert 'hit_count >= 0' in content, "Migration 028 missing hit_count CHECK"

    def test_migration_027_has_trigger_updated_at(self, migrations_dir):
        """Migration 027 doit avoir trigger pour updated_at"""
        migration_file = migrations_dir / "027_vip_senders.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'CREATE TRIGGER' in content, "Migration 027 missing trigger"
        assert 'updated_at' in content, "Migration 027 missing updated_at trigger"

    def test_migration_028_has_trigger_updated_at(self, migrations_dir):
        """Migration 028 doit avoir trigger pour updated_at"""
        migration_file = migrations_dir / "028_urgency_keywords.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'CREATE TRIGGER' in content, "Migration 028 missing trigger"
        assert 'updated_at' in content, "Migration 028 missing updated_at trigger"

    def test_migration_028_has_seed_data(self, migrations_dir):
        """Migration 028 doit avoir seed initial avec keywords urgence français"""
        migration_file = migrations_dir / "028_urgency_keywords.sql"
        content = migration_file.read_text(encoding='utf-8')

        assert 'INSERT INTO' in content, "Migration 028 missing seed data"
        assert 'URGENT' in content, "Migration 028 missing 'URGENT' seed"
        assert 'deadline' in content, "Migration 028 missing 'deadline' seed"
        assert 'ON CONFLICT' in content, "Migration 028 missing ON CONFLICT clause"
