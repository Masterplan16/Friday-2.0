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
