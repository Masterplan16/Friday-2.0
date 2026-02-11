"""
Tests unitaires syntaxiques pour migration 026_cold_start_tracking.sql

Vérifie la présence et syntaxe SQL sans connexion DB réelle.
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_FILE = (
    PROJECT_ROOT / "database" / "migrations" / "026_cold_start_tracking.sql"
)


def test_migration_026_file_exists():
    """Vérifie que le fichier migration 026 existe."""
    assert MIGRATION_FILE.exists(), (
        f"Migration 026 non trouvée: {MIGRATION_FILE}"
    )


def test_migration_026_has_begin_commit():
    """Vérifie que la migration est encadrée par BEGIN/COMMIT."""
    content = MIGRATION_FILE.read_text(encoding="utf-8")

    assert "BEGIN;" in content, "Migration doit commencer par BEGIN;"
    assert "COMMIT;" in content, "Migration doit se terminer par COMMIT;"

    # Vérifier que BEGIN apparaît avant COMMIT
    begin_pos = content.find("BEGIN;")
    commit_pos = content.find("COMMIT;")
    assert (
        begin_pos < commit_pos
    ), "BEGIN doit apparaître avant COMMIT"


def test_migration_026_creates_table():
    """Vérifie que la migration crée la table cold_start_tracking."""
    content = MIGRATION_FILE.read_text(encoding="utf-8")

    # Rechercher CREATE TABLE core.cold_start_tracking
    pattern = r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?core\.cold_start_tracking"
    assert re.search(pattern, content, re.IGNORECASE), (
        "Migration doit créer table core.cold_start_tracking"
    )


def test_migration_026_has_required_columns():
    """Vérifie que toutes les colonnes requises sont présentes."""
    content = MIGRATION_FILE.read_text(encoding="utf-8")

    required_columns = [
        "module",
        "action_type",
        "phase",
        "emails_processed",
        "accuracy",
        "created_at",
        "updated_at",
    ]

    for col in required_columns:
        # Chercher déclaration colonne (flexible sur espaces)
        pattern = rf"\b{col}\s+\w+"
        assert re.search(pattern, content, re.IGNORECASE), (
            f"Colonne '{col}' manquante dans migration 026"
        )


def test_migration_026_has_primary_key():
    """Vérifie que la clé primaire (module, action_type) est définie."""
    content = MIGRATION_FILE.read_text(encoding="utf-8")

    # PRIMARY KEY peut être définie de 2 façons:
    # 1. PRIMARY KEY (module, action_type)
    # 2. CONSTRAINT ... PRIMARY KEY (...)

    has_pk = (
        re.search(r"PRIMARY\s+KEY\s*\(\s*module\s*,\s*action_type\s*\)", content, re.IGNORECASE)
        is not None
    )

    assert has_pk, "Primary key (module, action_type) manquante"


def test_migration_026_has_phase_check_constraint():
    """Vérifie que la contrainte CHECK sur phase existe."""
    content = MIGRATION_FILE.read_text(encoding="utf-8")

    # Chercher CHECK constraint sur phase
    # phase IN ('cold_start', 'calibrated', 'production')
    pattern = r"phase\s+.*CHECK.*cold_start.*calibrated.*production"
    assert re.search(pattern, content, re.IGNORECASE | re.DOTALL), (
        "CHECK constraint sur phase manquante (doit inclure: cold_start, calibrated, production)"
    )


def test_migration_026_has_indexes():
    """Vérifie que les indexes requis sont créés."""
    content = MIGRATION_FILE.read_text(encoding="utf-8")

    # Index principal sur (module, action_type)
    pattern_main = r"CREATE\s+INDEX\s+.*idx_cold_start_module_action.*\(module\s*,\s*action_type\)"
    assert re.search(pattern_main, content, re.IGNORECASE | re.DOTALL), (
        "Index idx_cold_start_module_action manquant"
    )


def test_migration_026_seeds_email_classify():
    """Vérifie que le seed initial pour email.classify existe."""
    content = MIGRATION_FILE.read_text(encoding="utf-8")

    # Chercher INSERT pour email + classify
    has_seed = (
        re.search(r"INSERT\s+INTO\s+core\.cold_start_tracking", content, re.IGNORECASE)
        is not None
    )
    has_email = "'email'" in content or '"email"' in content
    has_classify = "'classify'" in content or '"classify"' in content

    assert has_seed, "INSERT INTO cold_start_tracking manquant"
    assert has_email, "Seed pour module 'email' manquant"
    assert has_classify, "Seed pour action 'classify' manquant"


def test_migration_026_has_comments():
    """Vérifie que la migration contient des commentaires documentation."""
    content = MIGRATION_FILE.read_text(encoding="utf-8")

    # Au moins un COMMENT ON TABLE ou COMMENT ON COLUMN
    has_comment = re.search(r"COMMENT\s+ON\s+(TABLE|COLUMN)", content, re.IGNORECASE)
    assert has_comment, (
        "Migration devrait contenir des COMMENT ON pour documentation"
    )


def test_migration_026_has_trigger_updated_at():
    """Vérifie que le trigger updated_at existe."""
    content = MIGRATION_FILE.read_text(encoding="utf-8")

    # Fonction trigger
    pattern_func = r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+.*update_cold_start_tracking_updated_at"
    assert re.search(pattern_func, content, re.IGNORECASE | re.DOTALL), (
        "Fonction trigger update_cold_start_tracking_updated_at manquante"
    )

    # Trigger
    pattern_trigger = r"CREATE\s+TRIGGER\s+.*trigger_cold_start_tracking_updated_at"
    assert re.search(pattern_trigger, content, re.IGNORECASE | re.DOTALL), (
        "Trigger trigger_cold_start_tracking_updated_at manquant"
    )


def test_migration_026_sql_syntax_valid():
    """
    Vérifie que le SQL n'a pas d'erreurs de syntaxe évidentes.

    Tests basiques :
    - BEGIN; et COMMIT; transactionnels présents
    - Pas de parenthèses non fermées
    """
    content = MIGRATION_FILE.read_text(encoding="utf-8")

    # Compter BEGIN; et COMMIT; transactionnels (avec point-virgule)
    # Cela exclut les BEGIN dans les fonctions PL/pgSQL
    begin_count = len(re.findall(r"\bBEGIN\s*;", content, re.IGNORECASE))
    commit_count = len(re.findall(r"\bCOMMIT\s*;", content, re.IGNORECASE))
    assert begin_count == commit_count, (
        f"Mismatch BEGIN;/COMMIT;: {begin_count} BEGIN;, {commit_count} COMMIT;"
    )
    assert begin_count >= 1, "Au moins un BEGIN; transactionnel requis"

    # Compter parenthèses ouvrantes vs fermantes
    open_parens = content.count("(")
    close_parens = content.count(")")
    assert open_parens == close_parens, (
        f"Parenthèses non balancées: {open_parens} '(' vs {close_parens} ')'"
    )
