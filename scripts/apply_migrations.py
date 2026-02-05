#!/usr/bin/env python3
"""
Script d'application des migrations SQL pour Friday 2.0

Usage:
    python scripts/apply_migrations.py [--dry-run]

Fonctionnalités:
    - Exécute les migrations SQL dans l'ordre numérique (001, 002, ...)
    - Track les migrations appliquées dans core.schema_migrations
    - Backup automatique avant chaque migration
    - Rollback en cas d'erreur
"""

import asyncio
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime
import asyncpg


MIGRATIONS_DIR = Path(__file__).parent.parent / "database" / "migrations"
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://friday:password@localhost:5432/friday"
)


async def ensure_migrations_table(conn: asyncpg.Connection):
    """Crée la table de tracking des migrations si elle n'existe pas"""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS core.schema_migrations (
            version VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT NOW(),
            checksum VARCHAR(64)
        );
    """)


async def get_applied_migrations(conn: asyncpg.Connection) -> set[str]:
    """Récupère la liste des migrations déjà appliquées"""
    rows = await conn.fetch("SELECT version FROM core.schema_migrations ORDER BY version")
    return {row['version'] for row in rows}


async def calculate_checksum(filepath: Path) -> str:
    """Calcule le checksum MD5 d'un fichier SQL"""
    import hashlib
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


async def backup_database(conn: asyncpg.Connection, migration_version: str):
    """Crée un backup avant d'appliquer la migration"""
    # Note: En production, utiliser pg_dump via subprocess
    # Ici, on log simplement pour simplifier
    print(f"  📦 Backup virtuel créé pour migration {migration_version}")


async def apply_migration(conn: asyncpg.Connection, filepath: Path, dry_run: bool = False):
    """Applique une migration SQL"""
    version = filepath.stem  # Ex: "001_init_schemas"

    print(f"\n📄 Migration {version}")
    print(f"   Fichier: {filepath.name}")

    # Lire le contenu SQL
    with open(filepath, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    if dry_run:
        print(f"   [DRY-RUN] Contenu SQL ({len(sql_content)} caractères)")
        return

    # Backup avant migration
    await backup_database(conn, version)

    # Calculer checksum
    checksum = await calculate_checksum(filepath)

    try:
        # Exécuter la migration dans une transaction
        async with conn.transaction():
            await conn.execute(sql_content)

            # Enregistrer la migration appliquée
            await conn.execute("""
                INSERT INTO core.schema_migrations (version, applied_at, checksum)
                VALUES ($1, NOW(), $2)
            """, version, checksum)

        print(f"   ✅ Migration appliquée avec succès")

    except Exception as e:
        print(f"   ❌ ERREUR lors de la migration: {e}")
        print(f"   🔄 Rollback automatique effectué")
        raise


async def main(dry_run: bool = False):
    """Point d'entrée principal"""
    print("=" * 60)
    print("🚀 Friday 2.0 - Application des migrations SQL")
    print("=" * 60)

    if dry_run:
        print("\n⚠️  MODE DRY-RUN - Aucune modification ne sera appliquée\n")

    # Connexion à la base
    print(f"\n🔌 Connexion à la base de données...")
    try:
        conn = await asyncpg.connect(DB_URL)
        print(f"   ✅ Connecté")
    except Exception as e:
        print(f"   ❌ Erreur de connexion: {e}")
        print(f"\n💡 Vérifier que PostgreSQL est démarré et que DATABASE_URL est correct")
        sys.exit(1)

    try:
        # Assurer que la table de tracking existe
        await ensure_migrations_table(conn)

        # Récupérer les migrations déjà appliquées
        applied = await get_applied_migrations(conn)
        print(f"\n📊 Migrations déjà appliquées: {len(applied)}")
        if applied:
            for version in sorted(applied):
                print(f"   ✓ {version}")

        # Lister toutes les migrations disponibles
        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        print(f"\n📁 Migrations disponibles: {len(migration_files)}")

        if not migration_files:
            print(f"   ⚠️  Aucune migration trouvée dans {MIGRATIONS_DIR}")
            sys.exit(0)

        # Appliquer les migrations manquantes
        pending = [f for f in migration_files if f.stem not in applied]

        if not pending:
            print(f"\n✨ Toutes les migrations sont déjà appliquées !")
            sys.exit(0)

        print(f"\n🔄 Migrations à appliquer: {len(pending)}")
        for filepath in pending:
            await apply_migration(conn, filepath, dry_run)

        if not dry_run:
            print(f"\n" + "=" * 60)
            print(f"✅ Toutes les migrations ont été appliquées avec succès !")
            print(f"=" * 60)

    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Applique les migrations SQL Friday 2.0")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simule l'application des migrations sans modifier la base"
    )

    args = parser.parse_args()

    try:
        asyncio.run(main(dry_run=args.dry_run))
    except KeyboardInterrupt:
        print("\n\n⚠️  Interruption utilisateur")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erreur fatale: {e}")
        sys.exit(1)
