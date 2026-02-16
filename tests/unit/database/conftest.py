"""
Fixtures pour les tests de migrations SQL (Story 1.2).

Fournit:
- Chemins vers les fichiers de migration
- Chargement du contenu SQL
- Fixtures pour tests unitaires (mock DB) et integration (vraie DB)
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = PROJECT_ROOT / "database" / "migrations"


@pytest.fixture
def migrations_dir() -> Path:
    """Repertoire des migrations SQL."""
    return MIGRATIONS_DIR


@pytest.fixture
def migration_files(migrations_dir: Path) -> list[Path]:
    """Liste triee de tous les fichiers de migration SQL."""
    return sorted(migrations_dir.glob("*.sql"))


@pytest.fixture
def migration_contents(migration_files: list[Path]) -> dict[str, str]:
    """Dictionnaire {nom_fichier: contenu_sql} pour chaque migration."""
    return {f.stem: f.read_text(encoding="utf-8") for f in migration_files}
