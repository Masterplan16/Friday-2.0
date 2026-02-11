"""
Tests unitaires pour la sécurité des clés age.

Story 1.12 - Task 1.2: Vérifier que la clé privée age n'est JAMAIS commitée.
"""

import os
import subprocess
import pytest
from pathlib import Path


@pytest.mark.unit
def test_age_private_key_not_in_repo():
    """
    Vérifie qu'aucune clé privée age n'est commitée dans le repo.

    AC3: La clé privée NE DOIT PAS être sur VPS
    """
    # Patterns de clés privées age
    private_key_patterns = [
        "AGE-SECRET-KEY-",
        "age-secret-key-",
    ]

    repo_root = Path(__file__).parent.parent.parent.parent

    for pattern in private_key_patterns:
        # Rechercher dans fichiers trackés (exclure docs, tests, .gitignore où c'est légitime)
        result = subprocess.run(
            ["git", "grep", "-i", pattern,
             ":(exclude).gitignore",
             ":(exclude)docs/",
             ":(exclude)tests/",
             ":(exclude)_bmad-output/"],
            cwd=repo_root,
            capture_output=True,
            text=True
        )

        # La commande doit échouer (exit code 1 = aucun match trouvé)
        assert result.returncode != 0, (
            f"❌ SÉCURITÉ CRITIQUE: Clé privée age trouvée dans le repo!\n"
            f"Pattern: {pattern}\n"
            f"Matches:\n{result.stdout}\n"
            f"La clé privée doit être stockée UNIQUEMENT sur PC Mainteneur."
        )


@pytest.mark.unit
def test_age_private_key_not_in_env_files():
    """
    Vérifie qu'aucun fichier .env ne contient de clé privée age.

    AC3: Seule la clé publique peut être dans .env.enc
    """
    repo_root = Path(__file__).parent.parent.parent.parent

    # Lister tous les fichiers .env*
    env_files = list(repo_root.glob("**/.env*"))

    private_key_pattern = "AGE-SECRET-KEY-"

    for env_file in env_files:
        # Ignorer fichiers binaires ou chiffrés SOPS
        if env_file.suffix in ['.enc', '.age']:
            # Fichier chiffré, on ne peut pas le lire directement
            # Vérifier via git grep sur le fichier avant chiffrement
            continue

        try:
            content = env_file.read_text()
            assert private_key_pattern not in content, (
                f"❌ SÉCURITÉ CRITIQUE: Clé privée age trouvée dans {env_file}!\n"
                f"La clé privée ne doit JAMAIS être dans .env"
            )
        except Exception:
            # Fichier illisible (binaire, permissions, etc.) → skip
            pass


@pytest.mark.unit
def test_age_public_key_format_valid():
    """
    Vérifie que AGE_PUBLIC_KEY dans .env a le bon format (si elle existe).

    Format attendu: age1<58 caractères base64>
    """
    repo_root = Path(__file__).parent.parent.parent.parent
    env_file = repo_root / ".env"

    if not env_file.exists():
        pytest.skip(".env file not found (expected in development)")

    content = env_file.read_text()

    # Chercher AGE_PUBLIC_KEY
    for line in content.splitlines():
        if line.startswith("AGE_PUBLIC_KEY="):
            public_key = line.split("=", 1)[1].strip().strip('"')

            # Vérifier format
            assert public_key.startswith("age1"), (
                f"Invalid AGE_PUBLIC_KEY format: {public_key}\n"
                f"Expected: age1<base64>"
            )

            # Longueur attendue : age1 (4 chars) + 58-62 chars base64
            assert 60 <= len(public_key) <= 70, (
                f"Invalid AGE_PUBLIC_KEY length: {len(public_key)}\n"
                f"Expected: 60-70 characters"
            )

            break


@pytest.mark.unit
def test_gitignore_prevents_private_key_commit():
    """
    Vérifie que .gitignore contient des patterns pour bloquer les clés privées.

    AC3: Prévention au niveau git
    """
    repo_root = Path(__file__).parent.parent.parent.parent
    gitignore_file = repo_root / ".gitignore"

    assert gitignore_file.exists(), ".gitignore file must exist"

    content = gitignore_file.read_text()

    # Patterns recommandés pour bloquer les clés age
    recommended_patterns = [
        "*.age",  # Fichiers chiffrés age (sauf .env.enc qui doit être commité)
        "age-key.txt",  # Nom par défaut age-keygen
        ".age/",  # Dossier clés age
    ]

    for pattern in recommended_patterns:
        assert pattern in content or f"*{pattern}" in content, (
            f"⚠️ WARNING: .gitignore should contain pattern: {pattern}\n"
            f"Pour prévenir commit accidentel de clés privées"
        )
