"""
Tests d'intégration pour vérifier l'installation de age CLI dans les containers.

Story 1.12 - Task 1.1: Installer age CLI
"""

import subprocess
import pytest


@pytest.mark.integration
def test_age_installed_in_n8n_container():
    """
    Vérifie que age CLI est installé dans le container n8n.

    AC1: L'exécution de `age --version` doit réussir
    """
    result = subprocess.run(
        ["docker", "exec", "friday-n8n", "age", "--version"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"age CLI not found: {result.stderr}"
    assert "age" in result.stdout.lower(), f"Unexpected version output: {result.stdout}"


@pytest.mark.integration
def test_age_version_meets_requirements():
    """
    Vérifie que la version de age installée est >= v1.3.0 (support post-quantum).

    AC1: Version age >= v1.3.0 selon Dev Notes
    """
    result = subprocess.run(
        ["docker", "exec", "friday-n8n", "age", "--version"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0

    # Format attendu: "age version v1.3.0" ou similaire
    version_line = result.stdout.strip()

    # Extraire version (format: v1.3.0 ou 1.3.0)
    import re
    match = re.search(r'v?(\d+)\.(\d+)\.(\d+)', version_line)
    assert match, f"Cannot parse version from: {version_line}"

    major, minor, patch = map(int, match.groups())

    # Vérifier >= v1.3.0
    assert major >= 1, f"Major version too old: {major}"
    if major == 1:
        assert minor >= 3, f"Minor version too old: {minor} (need >= 3)"


@pytest.mark.integration
def test_age_keygen_available():
    """
    Vérifie que age-keygen est aussi installé (nécessaire pour Task 1.2).

    AC1: age-keygen doit être disponible pour générer les keypairs
    """
    result = subprocess.run(
        ["docker", "exec", "friday-n8n", "age-keygen", "--help"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"age-keygen not found: {result.stderr}"
    assert "usage" in result.stdout.lower() or "age-keygen" in result.stdout.lower()
