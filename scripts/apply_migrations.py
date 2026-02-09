#!/usr/bin/env python3
"""
Script d'application des migrations SQL pour Friday 2.0

Usage:
    python scripts/apply_migrations.py
    python scripts/apply_migrations.py --dry-run
    python scripts/apply_migrations.py --status
    python scripts/apply_migrations.py --backup-dir /path/to/backups

Fonctionnalites:
    - Execute les migrations SQL dans l'ordre numerique (001, 002, ...)
    - Track les migrations appliquees dans core.schema_migrations
    - Backup automatique via pg_dump avant chaque migration
    - Rollback en cas d'erreur (transaction par migration)
    - Verification post-migration : aucune table dans schema public
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import asyncpg
import structlog


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FridayError(Exception):
    """Base exception Friday 2.0"""


class PipelineError(FridayError):
    """Erreurs pipeline ingestion/traitement"""


class MigrationError(PipelineError):
    """Erreur lors de l'application d'une migration"""


class BackupError(PipelineError):
    """Erreur lors du backup pre-migration"""


class ConfigError(FridayError):
    """Erreur de configuration (variable env manquante, etc.)"""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIGRATIONS_DIR = Path(__file__).parent.parent / "database" / "migrations"
DEFAULT_BACKUP_DIR = Path(__file__).parent.parent / "backups" / "migrations"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def configure_logging() -> structlog.stdlib.BoundLogger:
    """Configure structlog pour logging JSON structure."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if sys.stderr.isatty()
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger(service="apply-migrations")


# ---------------------------------------------------------------------------
# Database URL
# ---------------------------------------------------------------------------


def get_database_url() -> str:
    """Recupere DATABASE_URL depuis l'environnement. Echoue si absente."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ConfigError(
            "DATABASE_URL non definie. "
            "Definir la variable d'environnement DATABASE_URL avant de lancer le script. "
            "Exemple: export DATABASE_URL=postgresql://friday:xxx@localhost:5432/friday"
        )
    return db_url


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------


def strip_transaction_wrapper(sql: str) -> str:
    """Retire BEGIN/COMMIT du SQL pour wrapper dans une transaction asyncpg.

    Les migrations SQL contiennent leur propre BEGIN/COMMIT, mais on veut
    les executer dans une transaction asyncpg qui inclut aussi l'INSERT
    dans core.schema_migrations (atomicite).
    """
    sql = re.sub(r"^\s*BEGIN\s*;\s*$", "", sql, flags=re.MULTILINE | re.IGNORECASE)
    sql = re.sub(r"^\s*COMMIT\s*;\s*$", "", sql, flags=re.MULTILINE | re.IGNORECASE)
    return sql.strip()


def calculate_checksum(filepath: Path) -> str:
    """Calcule le checksum SHA-256 d'un fichier SQL."""
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


async def ensure_migrations_table(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    """Cree le schema core et la table de tracking si necessaire.

    Resout le probleme de bootstrap : core.schema_migrations a besoin
    du schema core, qui est cree par migration 001. On cree le schema
    en avance avec IF NOT EXISTS (pas de conflit avec 001).
    """
    await conn.execute("CREATE SCHEMA IF NOT EXISTS core")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS core.schema_migrations (
            version VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            checksum VARCHAR(64)
        )
    """)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_applied_migrations(conn: asyncpg.Connection) -> set[str]:  # type: ignore[type-arg]
    """Recupere la liste des migrations deja appliquees."""
    rows: list[asyncpg.Record] = await conn.fetch(
        "SELECT version FROM core.schema_migrations ORDER BY version"
    )
    return {row["version"] for row in rows}


async def check_public_schema(conn: asyncpg.Connection) -> list[str]:  # type: ignore[type-arg]
    """Verifie qu'aucun objet utilisateur n'est dans le schema public.

    Verifie : tables, fonctions, vues, sequences, types custom.
    Les objets appartenant aux extensions installees (pgcrypto, uuid-ossp, vector)
    sont exclus dynamiquement via pg_depend, pas via une liste hardcodee.
    """
    violations: list[str] = []

    # Tables dans public non creees par des extensions
    rows: list[asyncpg.Record] = await conn.fetch("""
        SELECT t.tablename
        FROM pg_tables t
        LEFT JOIN pg_class c ON c.relname = t.tablename
            AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
        LEFT JOIN pg_depend d ON d.objid = c.oid AND d.deptype = 'e'
        WHERE t.schemaname = 'public'
          AND d.objid IS NULL
    """)
    violations.extend(f"table: public.{row['tablename']}" for row in rows)

    # Fonctions dans public non creees par des extensions
    func_rows: list[asyncpg.Record] = await conn.fetch("""
        SELECT p.proname
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        LEFT JOIN pg_depend d ON d.objid = p.oid AND d.deptype = 'e'
        WHERE n.nspname = 'public'
          AND p.prokind = 'f'
          AND d.objid IS NULL
    """)
    violations.extend(f"function: public.{row['proname']}" for row in func_rows)

    # Vues dans public
    view_rows: list[asyncpg.Record] = await conn.fetch("""
        SELECT viewname FROM pg_views WHERE schemaname = 'public'
    """)
    violations.extend(f"view: public.{row['viewname']}" for row in view_rows)

    # Sequences dans public non creees par des extensions
    seq_rows: list[asyncpg.Record] = await conn.fetch("""
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON c.relnamespace = n.oid
        LEFT JOIN pg_depend d ON d.objid = c.oid AND d.deptype = 'e'
        WHERE n.nspname = 'public'
          AND c.relkind = 'S'
          AND d.objid IS NULL
    """)
    violations.extend(f"sequence: public.{row['relname']}" for row in seq_rows)

    # Types custom dans public non crees par des extensions
    type_rows: list[asyncpg.Record] = await conn.fetch("""
        SELECT t.typname
        FROM pg_type t
        JOIN pg_namespace n ON t.typnamespace = n.oid
        LEFT JOIN pg_depend d ON d.objid = t.oid AND d.deptype = 'e'
        WHERE n.nspname = 'public'
          AND t.typtype = 'c'
          AND d.objid IS NULL
    """)
    violations.extend(f"type: public.{row['typname']}" for row in type_rows)

    return violations


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def _parse_db_url(db_url: str) -> dict[str, str]:
    """Parse DATABASE_URL en composants pour pg_dump (sans exposer le password en CLI).

    Les passwords URL-encoded (ex: p%40ss → p@ss) sont decodes automatiquement.
    """
    parsed = urlparse(db_url)
    result: dict[str, str] = {}
    if parsed.hostname:
        result["host"] = parsed.hostname
    if parsed.port:
        result["port"] = str(parsed.port)
    if parsed.username:
        result["username"] = unquote(parsed.username)
    if parsed.password:
        result["password"] = unquote(parsed.password)
    if parsed.path and parsed.path != "/":
        result["dbname"] = parsed.path.lstrip("/")
    return result


BACKUP_TIMEOUT_SECONDS = 300  # 5 minutes max pour pg_dump


async def backup_database(
    db_url: str,
    migration_version: str,
    backup_dir: Path,
    log: Any,
) -> Path:
    """Cree un backup reel via pg_dump avant migration.

    Le password est passe via PGPASSWORD (variable d'environnement)
    et non en argument CLI, pour eviter l'exposition dans la process list.
    Utilise asyncio.create_subprocess_exec pour ne pas bloquer l'event loop.
    Timeout de BACKUP_TIMEOUT_SECONDS secondes.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"pre_{migration_version}_{timestamp}.dump"

    log.info(
        "backup pre-migration",
        migration=migration_version,
        backup_file=str(backup_file),
    )

    db_parts = _parse_db_url(db_url)
    cmd = [
        "pg_dump",
        "--format=custom",
        "--compress=6",
        "-f",
        str(backup_file),
    ]
    if "host" in db_parts:
        cmd.extend(["--host", db_parts["host"]])
    if "port" in db_parts:
        cmd.extend(["--port", db_parts["port"]])
    if "username" in db_parts:
        cmd.extend(["--username", db_parts["username"]])
    if "dbname" in db_parts:
        cmd.append(db_parts["dbname"])

    env = os.environ.copy()
    if "password" in db_parts:
        env["PGPASSWORD"] = db_parts["password"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=BACKUP_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise BackupError(
            f"pg_dump timeout apres {BACKUP_TIMEOUT_SECONDS}s pour migration {migration_version}"
        )

    if proc.returncode != 0:
        raise BackupError(
            f"pg_dump echoue (code {proc.returncode}): {stderr.decode().strip()}"
        )

    log.info(
        "backup cree",
        migration=migration_version,
        backup_file=str(backup_file),
        size_bytes=backup_file.stat().st_size,
    )
    return backup_file


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


async def apply_migration(
    conn: asyncpg.Connection,  # type: ignore[type-arg]
    filepath: Path,
    db_url: str,
    backup_dir: Path,
    dry_run: bool,
    no_backup: bool,
    log: Any,
) -> None:
    """Applique une migration SQL avec backup et transaction."""
    version = filepath.stem

    with open(filepath, "r", encoding="utf-8") as f:
        sql_content = f.read()

    checksum = calculate_checksum(filepath)

    log.info("migration trouvee", version=version, file=filepath.name, chars=len(sql_content))

    if dry_run:
        log.info("dry-run: migration ignoree", version=version)
        return

    # Backup reel via pg_dump (sauf si --no-backup)
    if no_backup:
        log.info("backup ignore (--no-backup)", version=version)
    else:
        await backup_database(db_url, version, backup_dir, log)

    # Retirer BEGIN/COMMIT pour wrapper dans transaction asyncpg
    sql_stripped = strip_transaction_wrapper(sql_content)

    try:
        async with conn.transaction():
            await conn.execute(sql_stripped)
            await conn.execute(
                "INSERT INTO core.schema_migrations (version, applied_at, checksum) "
                "VALUES ($1, NOW(), $2)",
                version,
                checksum,
            )
        log.info("migration appliquee", version=version)

    except Exception as exc:
        log.error(
            "migration echouee - rollback automatique",
            version=version,
            error=str(exc),
        )
        raise MigrationError(f"Migration {version} echouee: {exc}") from exc


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


async def show_status(conn: asyncpg.Connection, log: Any) -> None:  # type: ignore[type-arg]
    """Affiche l'etat des migrations sans rien appliquer (read-only).

    Ne cree PAS le schema core ni la table schema_migrations.
    Si la table n'existe pas, considere que 0 migrations sont appliquees.
    """
    # Verifier si la table existe SANS la creer (read-only)
    table_exists: bool = await conn.fetchval("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'core' AND table_name = 'schema_migrations'
        )
    """)

    applied: set[str] = set()
    if table_exists:
        applied = await get_applied_migrations(conn)

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    log.info(
        "etat des migrations",
        total_disponibles=len(migration_files),
        appliquees=len(applied),
    )

    for filepath in migration_files:
        version = filepath.stem
        status = "appliquee" if version in applied else "en attente"
        log.info("migration", version=version, status=status)

    pending = [f for f in migration_files if f.stem not in applied]
    if pending:
        log.info("migrations en attente", count=len(pending))
    else:
        log.info("toutes les migrations sont appliquees")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(
    dry_run: bool = False,
    status_only: bool = False,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    no_backup: bool = False,
) -> None:
    """Point d'entree principal."""
    log = configure_logging()

    db_url = get_database_url()

    log.info("connexion a la base de donnees")

    try:
        conn: asyncpg.Connection = await asyncpg.connect(db_url)  # type: ignore[type-arg]
    except Exception as exc:
        log.error("connexion echouee", error=str(exc))
        raise ConfigError(f"Impossible de se connecter: {exc}") from exc

    try:
        # Mode status : afficher et quitter
        if status_only:
            await show_status(conn, log)
            return

        if dry_run:
            log.info("mode dry-run actif - aucune modification")

        # Bootstrap : assurer que core.schema_migrations existe
        await ensure_migrations_table(conn)

        # Migrations deja appliquees
        applied = await get_applied_migrations(conn)
        log.info("migrations deja appliquees", count=len(applied))

        # Lister toutes les migrations disponibles
        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        log.info("migrations disponibles", count=len(migration_files))

        if not migration_files:
            log.warning("aucune migration trouvee", directory=str(MIGRATIONS_DIR))
            return

        # Filtrer les migrations a appliquer
        pending = [f for f in migration_files if f.stem not in applied]

        if not pending:
            log.info("toutes les migrations sont deja appliquees")
            return

        log.info("migrations a appliquer", count=len(pending))

        # Appliquer chaque migration
        for filepath in pending:
            await apply_migration(conn, filepath, db_url, backup_dir, dry_run, no_backup, log)

        if not dry_run:
            # Verification post-migration : rien dans public
            violations = await check_public_schema(conn)
            if violations:
                log.error(
                    "objets detectes dans schema public",
                    violations=violations,
                )
                raise MigrationError(
                    f"Objets dans schema public apres migration: {violations}"
                )
            log.info("verification schema public: OK")

            log.info("toutes les migrations appliquees avec succes")

    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Applique les migrations SQL Friday 2.0"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simule l'application des migrations sans modifier la base",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Affiche l'etat des migrations sans rien appliquer",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=DEFAULT_BACKUP_DIR,
        help="Repertoire pour les backups pre-migration (default: ./backups/migrations/)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Ignore les backups pre-migration (utile en dev/CI sans pg_dump)",
    )

    args = parser.parse_args()

    try:
        asyncio.run(
            main(
                dry_run=args.dry_run,
                status_only=args.status,
                backup_dir=args.backup_dir,
                no_backup=args.no_backup,
            )
        )
    except KeyboardInterrupt:
        log = structlog.get_logger(service="apply-migrations")
        log.warning("interruption utilisateur")
        sys.exit(1)
    except FridayError as exc:
        log = structlog.get_logger(service="apply-migrations")
        log.error("erreur migration", error=str(exc), error_type=type(exc).__name__)
        sys.exit(1)
    except Exception as exc:
        log = structlog.get_logger(service="apply-migrations")
        log.error("erreur inattendue", error=str(exc), error_type=type(exc).__name__)
        sys.exit(2)
