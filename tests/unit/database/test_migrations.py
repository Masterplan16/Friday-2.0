"""Tests unitaires pour les migrations SQL et apply_migrations.py (Story 1.2).

Tests couvrent:
- AC#1: 12 migrations executables dans l'ordre
- AC#2: core.schema_migrations tracking
- AC#3: Backup pre-migration reel via pg_dump
- AC#4: Rollback transaction par migration
- AC#5: Aucune table/fonction dans schema public
- AC#6: Tables trust layer (action_receipts, correction_rules, trust_metrics)
- AC#7: pgvector + index HNSW sur knowledge.embeddings
- AC#8: Execution sur base vierge
- AC#9: Idempotence (re-run sans crash)
- AC#10: Tests unitaires schema final

Tests unitaires (SQL parsing + script helpers) : marqueur @pytest.mark.unit
Tests integration (vraie DB PostgreSQL) : marqueur @pytest.mark.integration
"""

from __future__ import annotations

import asyncio
import os
import re

# Import du script apply_migrations
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from apply_migrations import (  # noqa: E402
    BackupError,
    ConfigError,
    FridayError,
    MigrationError,
    PipelineError,
    _parse_db_url,
    apply_migration,
    backup_database,
    calculate_checksum,
    ensure_migrations_table,
    get_database_url,
    main,
    show_status,
    strip_transaction_wrapper,
)


# ============================================================================
# Test 3.1 / AC#1+8: Les 12 migrations existent et sont bien formees
# ============================================================================
class TestMigrationFilesExist:
    """Verifie que les 23 migrations existent et sont ordonnees."""

    EXPECTED_MIGRATIONS = [
        "001_init_schemas",
        "002_core_users",
        "003_core_config",
        "004_ingestion_emails",
        "005_ingestion_documents",
        "006_ingestion_media",
        "007_knowledge_entities",
        "007_knowledge_nodes_edges",
        "008_knowledge_embeddings",
        "009_knowledge_thesis",
        "010_knowledge_finance",
        "011_trust_system",
        "012_ingestion_emails_legacy",
        "013_trust_metrics_columns",
        "014_telegram_config",
        "015_user_settings",
        "016_trust_metrics_anti_oscillation",
        "017_action_receipts_extended_status",
        "018_trust_metrics_missing_columns",
        "019_backup_metadata",
        "020_recovery_events",
        "022_add_purged_at_to_action_receipts",
        "023_add_deleted_at_to_backup_metadata",
    ]

    def test_migration_files_exist(self, migration_files: list[Path]) -> None:
        """AC#1: 23 migrations disponibles."""
        assert len(migration_files) == 23, (
            f"Expected 23 migration files, found {len(migration_files)}: "
            f"{[f.name for f in migration_files]}"
        )

    def test_migration_files_ordered(self, migration_files: list[Path]) -> None:
        """Les fichiers sont tries par numero."""
        stems = [f.stem for f in migration_files]
        assert stems == self.EXPECTED_MIGRATIONS

    def test_each_migration_is_non_empty(self, migration_contents: dict[str, str]) -> None:
        """Chaque fichier SQL contient du contenu."""
        for name, content in migration_contents.items():
            assert len(content.strip()) > 0, f"Migration {name} is empty"


# ============================================================================
# Test 3.2 / AC#5: Aucune table dans schema public
# ============================================================================
class TestNoPublicSchema:
    """Verifie que les migrations ne creent rien dans public."""

    def test_no_create_table_in_public(self, migration_contents: dict[str, str]) -> None:
        """Aucun CREATE TABLE sans schema prefix (qui irait dans public)."""
        for name, content in migration_contents.items():
            lines = [
                line.strip() for line in content.split("\n") if not line.strip().startswith("--")
            ]
            sql = "\n".join(lines)

            # Un seul regex: capture le nom complet apres CREATE TABLE [IF NOT EXISTS]
            matches = re.findall(
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\S+)\s*\(",
                sql,
                re.IGNORECASE,
            )
            for table_name in matches:
                assert "." in table_name, (
                    f"Migration {name}: CREATE TABLE {table_name} without schema prefix. "
                    f"All tables must be in core/ingestion/knowledge schemas."
                )

    def test_no_create_function_in_public(self, migration_contents: dict[str, str]) -> None:
        """Aucun CREATE FUNCTION sans schema prefix."""
        for name, content in migration_contents.items():
            lines = [
                line.strip() for line in content.split("\n") if not line.strip().startswith("--")
            ]
            sql = "\n".join(lines)

            matches = re.findall(
                r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(\S+)\s*\(",
                sql,
                re.IGNORECASE,
            )
            for match in matches:
                assert "." in match, (
                    f"Migration {name}: CREATE FUNCTION {match} without schema prefix. "
                    f"All functions must be in core schema."
                )


# ============================================================================
# Test 3.3 / AC#2: core.schema_migrations structure
# ============================================================================
class TestMigrationsTracking:
    """Verifie la structure de tracking des migrations."""

    def test_schema_migrations_created_by_script(self) -> None:
        """apply_migrations.py doit creer core.schema_migrations."""
        script = (PROJECT_ROOT / "scripts" / "apply_migrations.py").read_text()
        assert "core.schema_migrations" in script
        assert "CREATE TABLE IF NOT EXISTS core.schema_migrations" in script

    def test_schema_migrations_has_version_checksum(self) -> None:
        """La table doit avoir version, applied_at, checksum."""
        script = (PROJECT_ROOT / "scripts" / "apply_migrations.py").read_text()
        assert "version VARCHAR" in script
        assert "applied_at TIMESTAMPTZ" in script
        assert "checksum VARCHAR" in script

    def test_script_inserts_tracking_record_per_migration(self) -> None:
        """apply_migration insere un record dans schema_migrations apres chaque migration."""
        script = (PROJECT_ROOT / "scripts" / "apply_migrations.py").read_text()
        assert "INSERT INTO core.schema_migrations" in script
        assert "version" in script
        assert "checksum" in script

    def test_migrations_would_produce_tracking_records(self, migration_files: list[Path]) -> None:
        """Les 23 fichiers de migration produiraient 23 enregistrements dans schema_migrations."""
        assert len(migration_files) == 23, (
            f"Expected 23 migration files to produce 23 tracking records, "
            f"found {len(migration_files)}"
        )


# ============================================================================
# Test 3.4 / AC#7: Extensions activees
# ============================================================================
class TestExtensions:
    """Verifie que les extensions requises sont activees dans les migrations."""

    def test_pgcrypto_extension(self, migration_contents: dict[str, str]) -> None:
        content = migration_contents["001_init_schemas"]
        assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in content

    def test_uuid_ossp_extension(self, migration_contents: dict[str, str]) -> None:
        content = migration_contents["001_init_schemas"]
        assert 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"' in content

    def test_pgvector_extension(self, migration_contents: dict[str, str]) -> None:
        content = migration_contents["008_knowledge_embeddings"]
        assert "CREATE EXTENSION IF NOT EXISTS vector" in content


# ============================================================================
# Test 3.5 / AC#6: Tables trust layer
# ============================================================================
class TestTrustLayerTables:
    """Verifie la creation des tables trust layer dans migration 011."""

    def test_action_receipts_created(self, migration_contents: dict[str, str]) -> None:
        content = migration_contents["011_trust_system"]
        assert "core.action_receipts" in content
        assert "CREATE TABLE" in content

    def test_correction_rules_created(self, migration_contents: dict[str, str]) -> None:
        content = migration_contents["011_trust_system"]
        assert "core.correction_rules" in content

    def test_trust_metrics_created(self, migration_contents: dict[str, str]) -> None:
        content = migration_contents["011_trust_system"]
        assert "core.trust_metrics" in content

    def test_trust_level_constraint(self, migration_contents: dict[str, str]) -> None:
        content = migration_contents["011_trust_system"]
        assert "'auto'" in content
        assert "'propose'" in content
        assert "'blocked'" in content


# ============================================================================
# Test 3.6 / AC#7: Index HNSW sur knowledge.embeddings
# ============================================================================
class TestEmbeddingsIndex:
    """Verifie l'index HNSW sur knowledge.embeddings."""

    def test_embeddings_table_exists(self, migration_contents: dict[str, str]) -> None:
        content = migration_contents["008_knowledge_embeddings"]
        assert "knowledge.embeddings" in content

    def test_vector_column_exists(self, migration_contents: dict[str, str]) -> None:
        content = migration_contents["008_knowledge_embeddings"]
        assert "vector(1024)" in content

    def test_hnsw_index_exists(self, migration_contents: dict[str, str]) -> None:
        content = migration_contents["008_knowledge_embeddings"]
        assert "hnsw" in content.lower(), "HNSW index must be created on embeddings"


# ============================================================================
# Test 3.7: Idempotence (pas de crash sur re-run)
# ============================================================================
class TestIdempotence:
    """Verifie que les migrations utilisent IF NOT EXISTS pour idempotence."""

    def test_schemas_use_if_not_exists(self, migration_contents: dict[str, str]) -> None:
        content = migration_contents["001_init_schemas"]
        assert "CREATE SCHEMA IF NOT EXISTS core" in content
        assert "CREATE SCHEMA IF NOT EXISTS ingestion" in content
        assert "CREATE SCHEMA IF NOT EXISTS knowledge" in content

    def test_modified_migrations_use_if_not_exists(
        self, migration_contents: dict[str, str]
    ) -> None:
        """Les migrations modifiees/creees en Story 1.2+ utilisent IF NOT EXISTS."""
        # Migrations modifiees dans Story 1.2 (008, 010, 011, 012)
        # Les migrations legacy (002-009) reposent sur schema_migrations pour l'idempotence
        story_12_migrations = {
            "008_knowledge_embeddings",
            "010_knowledge_finance",
            "011_trust_system",
            "012_ingestion_emails_legacy",
        }
        for name, content in migration_contents.items():
            if name not in story_12_migrations:
                continue
            lines = [
                line.strip() for line in content.split("\n") if not line.strip().startswith("--")
            ]
            sql = "\n".join(lines)

            # Trouver tous les CREATE TABLE
            all_creates = re.findall(r"CREATE\s+TABLE\s+(\S+)\s*\(", sql, re.IGNORECASE)
            if_creates = re.findall(
                r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\S+)\s*\(", sql, re.IGNORECASE
            )
            for table in all_creates:
                assert table in if_creates, (
                    f"Migration {name}: CREATE TABLE {table} without IF NOT EXISTS. "
                    f"All tables should use IF NOT EXISTS for idempotence."
                )


# ============================================================================
# Test 3.8 / AC#3: Backup cree avant chaque migration
# ============================================================================
class TestBackup:
    """Verifie le backup pre-migration via pg_dump (async)."""

    @pytest.mark.asyncio
    async def test_backup_calls_pg_dump(self, tmp_path: Path) -> None:
        """backup_database appelle pg_dump avec les bons arguments via asyncio subprocess."""
        log = MagicMock()
        backup_dir = tmp_path / "backups"

        async def fake_create_subprocess(*args: Any, **kwargs: Any) -> MagicMock:
            """Simule asyncio.create_subprocess_exec pour pg_dump."""
            # Trouver le flag -f dans les args et creer le fichier
            args_list = list(args)
            for i, arg in enumerate(args_list):
                if arg == "-f" and i + 1 < len(args_list):
                    Path(args_list[i + 1]).write_bytes(b"fake dump content")

            mock_proc = MagicMock()
            mock_proc.returncode = 0

            async def mock_communicate() -> tuple[bytes, bytes]:
                return b"", b""

            mock_proc.communicate = mock_communicate
            return mock_proc

        with patch(
            "apply_migrations.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess
        ) as mock_exec:
            result = await backup_database(
                "postgresql://friday:secret@localhost:5432/friday",
                "001_init_schemas",
                backup_dir,
                log,
            )

            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            assert call_args[0] == "pg_dump"
            assert "--format=custom" in call_args
            assert "--compress=6" in call_args
            # Securite: le password ne doit PAS etre dans les arguments CLI
            assert "secret" not in " ".join(
                str(a) for a in call_args
            ), "Database password must not appear in pg_dump CLI arguments"
            # Le password doit etre passe via PGPASSWORD env var
            call_env = mock_exec.call_args[1].get("env", {})
            assert call_env.get("PGPASSWORD") == "secret"

    @pytest.mark.asyncio
    async def test_backup_raises_on_pg_dump_failure(self, tmp_path: Path) -> None:
        """BackupError si pg_dump echoue."""
        log = MagicMock()

        async def fake_failing_subprocess(*args: Any, **kwargs: Any) -> MagicMock:
            mock_proc = MagicMock()
            mock_proc.returncode = 1

            async def mock_communicate() -> tuple[bytes, bytes]:
                return b"", b"connection refused"

            mock_proc.communicate = mock_communicate
            return mock_proc

        with patch(
            "apply_migrations.asyncio.create_subprocess_exec", side_effect=fake_failing_subprocess
        ):
            with pytest.raises(BackupError, match="pg_dump echoue"):
                await backup_database(
                    "postgresql://test@localhost/test",
                    "001_init_schemas",
                    tmp_path / "backups",
                    log,
                )

    @pytest.mark.asyncio
    async def test_backup_timeout_raises(self, tmp_path: Path) -> None:
        """BackupError si pg_dump depasse le timeout."""
        log = MagicMock()

        async def fake_hanging_subprocess(*args: Any, **kwargs: Any) -> MagicMock:
            mock_proc = MagicMock()

            async def mock_communicate() -> tuple[bytes, bytes]:
                await asyncio.sleep(999)  # Simule un pg_dump qui ne repond pas
                return b"", b""

            mock_proc.communicate = mock_communicate
            mock_proc.kill = MagicMock()
            return mock_proc

        with patch(
            "apply_migrations.asyncio.create_subprocess_exec", side_effect=fake_hanging_subprocess
        ):
            with patch("apply_migrations.BACKUP_TIMEOUT_SECONDS", 0.01):
                with pytest.raises(BackupError, match="timeout"):
                    await backup_database(
                        "postgresql://test@localhost/test",
                        "001_init_schemas",
                        tmp_path / "backups",
                        log,
                    )


# ============================================================================
# Test 3.9: Rollback fonctionne si migration SQL invalide
# ============================================================================
class TestRollback:
    """Verifie que les migrations sont dans des transactions pour rollback."""

    def test_all_migrations_have_transaction(self, migration_contents: dict[str, str]) -> None:
        """Chaque migration doit avoir BEGIN et COMMIT."""
        for name, content in migration_contents.items():
            assert re.search(
                r"^\s*BEGIN\s*;", content, re.MULTILINE | re.IGNORECASE
            ), f"Migration {name} manque BEGIN;"
            assert re.search(
                r"^\s*COMMIT\s*;", content, re.MULTILINE | re.IGNORECASE
            ), f"Migration {name} manque COMMIT;"

    def test_strip_transaction_wrapper(self) -> None:
        """strip_transaction_wrapper retire BEGIN/COMMIT correctement."""
        sql = "BEGIN;\nCREATE TABLE core.test (id INT);\nCOMMIT;"
        result = strip_transaction_wrapper(sql)
        assert "BEGIN" not in result
        assert "COMMIT" not in result
        assert "CREATE TABLE core.test" in result

    def test_strip_transaction_preserves_content(self) -> None:
        """Le contenu SQL est preserve apres strip."""
        sql = (
            "-- Comment\nBEGIN;\n\n"
            "CREATE TABLE core.test (\n    id UUID PRIMARY KEY\n);\n\n"
            "CREATE INDEX idx_test ON core.test(id);\n\n"
            "COMMIT;\n"
        )
        result = strip_transaction_wrapper(sql)
        assert "CREATE TABLE core.test" in result
        assert "CREATE INDEX idx_test" in result
        assert "-- Comment" in result


# ============================================================================
# Test 3.10: Mode --dry-run ne modifie rien
# ============================================================================
class TestDryRun:
    """Verifie que --dry-run ne modifie pas la base."""

    def test_dry_run_argument_exists(self) -> None:
        """Le script accepte --dry-run."""
        script = (PROJECT_ROOT / "scripts" / "apply_migrations.py").read_text()
        assert "--dry-run" in script

    @pytest.mark.asyncio
    async def test_dry_run_does_not_execute_sql(self, tmp_path: Path) -> None:
        """En dry-run, apply_migration ne doit PAS executer le SQL ni creer de backup."""
        log = MagicMock()
        mock_conn = AsyncMock()
        sql_file = tmp_path / "001_test.sql"
        sql_file.write_text("BEGIN;\nCREATE TABLE core.test (id INT);\nCOMMIT;")

        await apply_migration(
            conn=mock_conn,
            filepath=sql_file,
            db_url="postgresql://test@localhost/test",
            backup_dir=tmp_path / "backups",
            dry_run=True,
            no_backup=False,
            log=log,
        )

        # En dry-run: pas d'execution SQL, pas de transaction, pas de backup
        mock_conn.transaction.assert_not_called()
        mock_conn.execute.assert_not_called()


# ============================================================================
# Test 3.11: Mode --status affiche l'etat (read-only)
# ============================================================================
class TestStatusMode:
    """Verifie que --status est read-only."""

    def test_status_argument_exists(self) -> None:
        """Le script accepte --status."""
        script = (PROJECT_ROOT / "scripts" / "apply_migrations.py").read_text()
        assert "--status" in script

    @pytest.mark.asyncio
    async def test_show_status_is_read_only(self) -> None:
        """show_status ne doit PAS creer de schema ou table (read-only)."""
        log = MagicMock()
        mock_conn = AsyncMock()
        # Simuler: la table schema_migrations existe
        mock_conn.fetchval.return_value = True
        mock_conn.fetch.return_value = []

        await show_status(mock_conn, log)

        # Doit faire un fetchval pour verifier l'existence (SELECT, pas CREATE)
        mock_conn.fetchval.assert_called_once()
        fetchval_sql = mock_conn.fetchval.call_args[0][0]
        assert "information_schema" in fetchval_sql
        # Ne doit PAS appeler execute (qui ferait un CREATE)
        mock_conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_show_status_no_table_returns_empty(self) -> None:
        """show_status avec table inexistante retourne 0 migrations appliquees."""
        log = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = False  # Table n'existe pas

        await show_status(mock_conn, log)

        # Ne doit PAS appeler fetch (pas de query sur table inexistante)
        mock_conn.fetch.assert_not_called()


# ============================================================================
# Tests helpers additionnels
# ============================================================================
class TestHelpers:
    """Tests pour les fonctions helpers du script."""

    def test_get_database_url_raises_if_missing(self) -> None:
        """ConfigError si DATABASE_URL non definie."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigError, match="DATABASE_URL non definie"):
                get_database_url()

    def test_get_database_url_returns_value(self) -> None:
        """Retourne DATABASE_URL si definie."""
        test_url = "postgresql://test@localhost/test"
        with patch.dict(os.environ, {"DATABASE_URL": test_url}):
            assert get_database_url() == test_url

    def test_calculate_checksum_is_deterministic(self, tmp_path: Path) -> None:
        """Le checksum est deterministe pour le meme contenu."""
        test_file = tmp_path / "test.sql"
        test_file.write_text("CREATE TABLE core.test (id INT);")
        checksum1 = calculate_checksum(test_file)
        checksum2 = calculate_checksum(test_file)
        assert checksum1 == checksum2
        assert len(checksum1) == 64  # SHA-256

    def test_calculate_checksum_uses_sha256(self, tmp_path: Path) -> None:
        """Le checksum utilise SHA-256 (pas MD5)."""
        test_file = tmp_path / "test.sql"
        test_file.write_text("test content")
        checksum = calculate_checksum(test_file)
        assert len(checksum) == 64  # SHA-256 = 64 hex chars

    def test_no_default_password_in_script(self) -> None:
        """Le script ne doit pas avoir de password en default."""
        script = (PROJECT_ROOT / "scripts" / "apply_migrations.py").read_text()
        assert "friday:password" not in script, "Script must not have default password"


# ============================================================================
# Tests coherence SQL entre migrations
# ============================================================================
class TestSQLConsistency:
    """Verifie la coherence SQL entre toutes les migrations."""

    def test_all_timestamps_are_timestamptz(self, migration_contents: dict[str, str]) -> None:
        """Toutes les colonnes timestamp doivent etre TIMESTAMPTZ."""
        for name, content in migration_contents.items():
            lines = [
                line.strip() for line in content.split("\n") if not line.strip().startswith("--")
            ]
            for line in lines:
                # Skip CREATE INDEX lines (column names may contain "timestamp")
                if re.match(r"CREATE\s+INDEX", line, re.IGNORECASE):
                    continue
                if re.search(r"\bTIMESTAMP\b", line, re.IGNORECASE):
                    # TIMESTAMP WITH TIME ZONE est equivalent a TIMESTAMPTZ
                    if "TIMESTAMP WITH TIME ZONE" in line.upper():
                        continue
                    # TIMESTAMPTZ est OK
                    if "TIMESTAMPTZ" in line.upper():
                        continue
                    # TIMESTAMP seul est interdit
                    if re.search(r"\bTIMESTAMP\b(?!\s+WITH)", line, re.IGNORECASE):
                        pytest.fail(
                            f"Migration {name}: Found TIMESTAMP without timezone: {line.strip()}"
                        )

    def test_uuid_generation_consistency(self, migration_contents: dict[str, str]) -> None:
        """Toutes les migrations doivent utiliser uuid_generate_v4()."""
        for name, content in migration_contents.items():
            if "gen_random_uuid()" in content:
                pytest.fail(
                    f"Migration {name}: Uses gen_random_uuid() instead of uuid_generate_v4(). "
                    f"Standardize on uuid_generate_v4() (extension uuid-ossp)."
                )

    def test_account_type_matches_perimeters(self, migration_contents: dict[str, str]) -> None:
        """Migration 010: account_type doit correspondre aux 5 perimetres."""
        content = migration_contents["010_knowledge_finance"]
        expected_types = {"selarl", "scm", "sci_ravas", "sci_malbosc", "personal"}
        # Extraire les types du CHECK constraint
        match = re.search(r"account_type\s+IN\s*\(([^)]+)\)", content, re.IGNORECASE)
        assert match, "account_type CHECK constraint not found in migration 010"
        types_str = match.group(1)
        actual_types = {t.strip().strip("'\"") for t in types_str.split(",")}
        assert actual_types == expected_types, (
            f"account_type CHECK mismatch. " f"Expected: {expected_types}, Got: {actual_types}"
        )

    def test_no_emoji_in_migrations(self, migration_contents: dict[str, str]) -> None:
        """Pas d'emoji dans les fichiers SQL."""
        import unicodedata

        for name, content in migration_contents.items():
            for char in content:
                if ord(char) > 127:
                    category = unicodedata.category(char)
                    if category.startswith("So"):  # Symbol, Other (includes emoji)
                        pytest.fail(f"Migration {name}: Contains emoji character: {char}")

    def test_schemas_created_in_order(self, migration_contents: dict[str, str]) -> None:
        """Migration 001 cree les 3 schemas."""
        content = migration_contents["001_init_schemas"]
        assert "CREATE SCHEMA IF NOT EXISTS core" in content
        assert "CREATE SCHEMA IF NOT EXISTS ingestion" in content
        assert "CREATE SCHEMA IF NOT EXISTS knowledge" in content

    def test_no_public_function_in_011(self, migration_contents: dict[str, str]) -> None:
        """Migration 011 ne doit pas creer de fonction dans public."""
        content = migration_contents["011_trust_system"]
        assert (
            "update_updated_at_column" not in content
        ), "Migration 011 should use core.update_updated_at() not public.update_updated_at_column()"

    def test_011_uses_core_trigger_function(self, migration_contents: dict[str, str]) -> None:
        """Migration 011 doit utiliser core.update_updated_at()."""
        content = migration_contents["011_trust_system"]
        assert "core.update_updated_at()" in content


# ============================================================================
# Tests securite et helpers apply_migrations.py
# ============================================================================
class TestParseDbUrl:
    """Verifie le parsing securise de DATABASE_URL."""

    def test_parse_full_url(self) -> None:
        """Parse une URL complete avec tous les composants."""
        parts = _parse_db_url("postgresql://friday:secret@db.example.com:5432/friday_db")
        assert parts["host"] == "db.example.com"
        assert parts["port"] == "5432"
        assert parts["username"] == "friday"
        assert parts["password"] == "secret"
        assert parts["dbname"] == "friday_db"

    def test_parse_url_without_password(self) -> None:
        """Parse une URL sans password."""
        parts = _parse_db_url("postgresql://friday@localhost/friday")
        assert parts["host"] == "localhost"
        assert parts["username"] == "friday"
        assert "password" not in parts
        assert parts["dbname"] == "friday"

    def test_parse_url_default_port(self) -> None:
        """Parse une URL sans port explicite."""
        parts = _parse_db_url("postgresql://friday@localhost/friday")
        assert "port" not in parts

    def test_parse_url_decodes_encoded_password(self) -> None:
        """Les passwords URL-encoded sont decodes (ex: %40 → @)."""
        parts = _parse_db_url("postgresql://friday:p%40ss%23word@localhost/friday")
        assert parts["password"] == "p@ss#word"

    def test_parse_url_decodes_encoded_username(self) -> None:
        """Les usernames URL-encoded sont decodes."""
        parts = _parse_db_url("postgresql://user%40domain:secret@localhost/friday")
        assert parts["username"] == "user@domain"


class TestExceptionHierarchy:
    """Verifie que la hierarchie d'exceptions est correcte."""

    def test_migration_error_is_friday_error(self) -> None:
        assert issubclass(MigrationError, FridayError)

    def test_backup_error_is_friday_error(self) -> None:
        assert issubclass(BackupError, FridayError)

    def test_config_error_is_friday_error(self) -> None:
        assert issubclass(ConfigError, FridayError)

    def test_friday_error_is_exception(self) -> None:
        assert issubclass(FridayError, Exception)

    def test_pipeline_error_is_friday_error(self) -> None:
        """PipelineError herite de FridayError (architecture CLAUDE.md)."""
        assert issubclass(PipelineError, FridayError)

    def test_migration_error_is_pipeline_error(self) -> None:
        """MigrationError herite de PipelineError (pas directement FridayError)."""
        assert issubclass(MigrationError, PipelineError)

    def test_backup_error_is_pipeline_error(self) -> None:
        """BackupError herite de PipelineError."""
        assert issubclass(BackupError, PipelineError)


class TestScriptSecurity:
    """Verifie les pratiques de securite du script."""

    def test_no_default_database_url(self) -> None:
        """Aucune valeur default pour DATABASE_URL dans le script."""
        script = (PROJECT_ROOT / "scripts" / "apply_migrations.py").read_text()
        # Pas de getenv avec default contenant password
        assert 'getenv("DATABASE_URL", "' not in script
        assert "getenv('DATABASE_URL', '" not in script

    def test_password_not_in_pg_dump_command(self) -> None:
        """Le script utilise PGPASSWORD et non l'URL directe pour pg_dump."""
        script = (PROJECT_ROOT / "scripts" / "apply_migrations.py").read_text()
        assert "PGPASSWORD" in script, "Script should use PGPASSWORD env var for pg_dump"
        assert "_parse_db_url" in script, "Script should parse DB URL for secure pg_dump"


# ============================================================================
# Tests fonctions core (H3: ensure_migrations_table, apply_migration, main)
# ============================================================================
class TestEnsureMigrationsTable:
    """Verifie le bootstrap de core.schema_migrations."""

    @pytest.mark.asyncio
    async def test_creates_schema_and_table(self) -> None:
        """ensure_migrations_table cree le schema core et la table."""
        mock_conn = AsyncMock()

        await ensure_migrations_table(mock_conn)

        # Doit executer 2 statements: CREATE SCHEMA + CREATE TABLE
        assert mock_conn.execute.call_count == 2
        calls = [str(c) for c in mock_conn.execute.call_args_list]
        assert any("CREATE SCHEMA IF NOT EXISTS core" in c for c in calls)
        assert any("core.schema_migrations" in c for c in calls)

    @pytest.mark.asyncio
    async def test_idempotent_with_if_not_exists(self) -> None:
        """ensure_migrations_table utilise IF NOT EXISTS (idempotent)."""
        mock_conn = AsyncMock()

        await ensure_migrations_table(mock_conn)

        schema_sql = mock_conn.execute.call_args_list[0][0][0]
        table_sql = mock_conn.execute.call_args_list[1][0][0]
        assert "IF NOT EXISTS" in schema_sql
        assert "IF NOT EXISTS" in table_sql


class TestApplyMigration:
    """Verifie la logique d'application d'une migration."""

    @staticmethod
    def _make_mock_conn() -> AsyncMock:
        """Cree un mock asyncpg connection avec transaction() fonctionnel.

        asyncpg.connection.transaction() est synchrone mais retourne un
        context manager async. On doit reproduire ce pattern.
        """
        mock_conn = AsyncMock()
        mock_tx = MagicMock()
        mock_tx.__aenter__ = AsyncMock(return_value=mock_tx)
        mock_tx.__aexit__ = AsyncMock(return_value=False)
        # transaction() est synchrone dans asyncpg -> MagicMock, pas AsyncMock
        mock_conn.transaction = MagicMock(return_value=mock_tx)
        return mock_conn

    @pytest.mark.asyncio
    async def test_applies_sql_in_transaction(self, tmp_path: Path) -> None:
        """apply_migration execute le SQL dans une transaction asyncpg."""
        log = MagicMock()
        sql_file = tmp_path / "001_test.sql"
        sql_file.write_text("BEGIN;\nCREATE TABLE core.test (id INT);\nCOMMIT;")

        mock_conn = self._make_mock_conn()

        await apply_migration(
            conn=mock_conn,
            filepath=sql_file,
            db_url="postgresql://test@localhost/test",
            backup_dir=tmp_path / "backups",
            dry_run=False,
            no_backup=True,
            log=log,
        )

        # Doit executer le SQL et inserer dans schema_migrations
        assert mock_conn.execute.call_count >= 2
        execute_calls = [str(c) for c in mock_conn.execute.call_args_list]
        assert any("CREATE TABLE core.test" in c for c in execute_calls)
        assert any("INSERT INTO core.schema_migrations" in c for c in execute_calls)

    @pytest.mark.asyncio
    async def test_strips_begin_commit_before_executing(self, tmp_path: Path) -> None:
        """apply_migration retire BEGIN/COMMIT du SQL avant execution."""
        log = MagicMock()
        sql_file = tmp_path / "001_test.sql"
        sql_file.write_text("BEGIN;\nCREATE TABLE core.test (id INT);\nCOMMIT;")

        mock_conn = self._make_mock_conn()

        await apply_migration(
            conn=mock_conn,
            filepath=sql_file,
            db_url="postgresql://test@localhost/test",
            backup_dir=tmp_path / "backups",
            dry_run=False,
            no_backup=True,
            log=log,
        )

        # Le SQL execute ne doit PAS contenir BEGIN/COMMIT
        sql_executed = mock_conn.execute.call_args_list[0][0][0]
        assert "BEGIN" not in sql_executed
        assert "COMMIT" not in sql_executed

    @pytest.mark.asyncio
    async def test_raises_migration_error_on_failure(self, tmp_path: Path) -> None:
        """MigrationError si l'execution SQL echoue."""
        log = MagicMock()
        sql_file = tmp_path / "001_test.sql"
        sql_file.write_text("BEGIN;\nINVALID SQL;\nCOMMIT;")

        mock_conn = self._make_mock_conn()
        mock_conn.execute.side_effect = Exception("syntax error")

        with pytest.raises(MigrationError, match="echouee"):
            await apply_migration(
                conn=mock_conn,
                filepath=sql_file,
                db_url="postgresql://test@localhost/test",
                backup_dir=tmp_path / "backups",
                dry_run=False,
                no_backup=True,
                log=log,
            )


class TestMainFlow:
    """Verifie le flux principal de main()."""

    @pytest.mark.asyncio
    async def test_main_raises_without_database_url(self) -> None:
        """main() echoue si DATABASE_URL n'est pas definie."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigError, match="DATABASE_URL"):
                await main()
