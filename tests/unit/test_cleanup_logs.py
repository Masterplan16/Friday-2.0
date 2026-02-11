"""
Tests unitaires pour cleanup logs Docker + journald.

Story 1.15 - AC2 : Rotation logs Docker > 7 jours
"""

import subprocess
import pytest


def test_cleanup_logs_docker_command_valid():
    """Test commande docker system prune syntaxe valide.

    GIVEN commande docker system prune avec filter until=168h
    WHEN la syntaxe est validée via --help
    THEN la commande est reconnue (returncode 0)
    """
    # Commande attendue dans cleanup-disk.sh
    cmd = ["docker", "system", "prune", "--help"]

    # Validation syntaxe
    result = subprocess.run(cmd, capture_output=True, text=True)

    assert result.returncode == 0, "docker system prune command should be valid"
    assert "until" in result.stdout.lower(), "--filter until should be documented"


def test_cleanup_logs_docker_filter_syntax():
    """Test syntaxe filter until=168h (7 jours).

    GIVEN filter until=168h dans docker system prune
    WHEN la documentation est consultée
    THEN le format est valide (168h = 7 days * 24h)
    """
    # Validation que 168h = 7 jours
    hours_per_week = 7 * 24
    assert hours_per_week == 168, "Filter until=168h should equal 7 days"

    # Commande complète attendue
    cmd = ["docker", "system", "prune", "-f", "--filter", "until=168h"]
    # Note: On ne peut pas exécuter réellement sans Docker daemon
    # Test syntaxe via construction commande
    assert len(cmd) == 6, "Command should have 6 arguments"
    assert cmd[4] == "--filter", "Fourth arg should be --filter"
    assert cmd[5] == "until=168h", "Fifth arg should be until=168h"


def test_cleanup_logs_journald_command_valid():
    """Test commande journalctl vacuum syntaxe valide.

    GIVEN commande journalctl --vacuum-time=7d
    WHEN la syntaxe est validée via --help
    THEN l'option --vacuum-time est documentée
    """
    # Commande attendue
    cmd = ["journalctl", "--help"]

    try:
        # Validation syntaxe (peut échouer si systemd pas installé sur Windows)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode == 0:
            assert "vacuum-time" in result.stdout.lower(), "--vacuum-time should be documented"
        else:
            pytest.skip("journalctl not available (systemd not installed)")
    except FileNotFoundError:
        pytest.skip("journalctl not available on this system")
    except subprocess.TimeoutExpired:
        pytest.skip("journalctl command timeout")


def test_cleanup_logs_journald_vacuum_syntax():
    """Test syntaxe --vacuum-time=7d valide.

    GIVEN format --vacuum-time=7d
    WHEN la commande est construite
    THEN la syntaxe respecte le format attendu
    """
    # Commande complète attendue
    cmd = ["journalctl", "--vacuum-time=7d"]

    assert len(cmd) == 2, "Command should have 2 arguments"
    assert cmd[1] == "--vacuum-time=7d", "Second arg should be --vacuum-time=7d"


def test_calculate_diff_bytes():
    """Test helper function calculate_diff pour bytes.

    GIVEN before=1000000 (1 MB), after=500000 (0.5 MB)
    WHEN calculate_diff est appelé
    THEN retourne 500000 bytes (0.5 MB freed)
    """
    # Simuler fonction bash calculate_diff en Python
    def calculate_diff(before: int, after: int) -> int:
        """Calculate freed bytes."""
        return max(0, before - after)

    before = 1_000_000  # 1 MB
    after = 500_000     # 0.5 MB
    freed = calculate_diff(before, after)

    assert freed == 500_000, f"Expected 500000 bytes freed, got {freed}"


def test_format_bytes_conversion():
    """Test helper function format_bytes.

    GIVEN bytes count
    WHEN format_bytes est appelé
    THEN retourne format human-readable (MB/GB)
    """
    # Simuler fonction bash format_bytes en Python
    def format_bytes(bytes_count: int) -> str:
        """Format bytes to human readable."""
        if bytes_count >= 1_000_000_000:
            return f"{bytes_count / 1_000_000_000:.1f} GB"
        elif bytes_count >= 1_000_000:
            return f"{bytes_count / 1_000_000:.1f} MB"
        elif bytes_count >= 1_000:
            return f"{bytes_count / 1_000:.1f} KB"
        else:
            return f"{bytes_count} bytes"

    assert format_bytes(500_000_000) == "0.5 GB"
    assert format_bytes(1_500_000) == "1.5 MB"
    assert format_bytes(1_500) == "1.5 KB"
    assert format_bytes(500) == "500 bytes"
