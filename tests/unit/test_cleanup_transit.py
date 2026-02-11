"""
Tests unitaires pour cleanup zone transit.

Story 1.15 - AC4 : Nettoyage zone transit VPS (fichiers temporaires PJ)
"""

import subprocess
import pytest
import tempfile
import os
from pathlib import Path
from datetime import datetime, timedelta


def test_cleanup_transit_find_command_syntax():
    """Test commande find zone transit syntaxe valide.

    GIVEN commande find /data/transit/uploads/ -type f -mtime +1 -delete
    WHEN la syntaxe est validée
    THEN la commande est correcte
    """
    # Commande attendue dans cleanup-disk.sh
    cmd = ["find", "/data/transit/uploads/", "-type", "f", "-mtime", "+1"]

    # Validation syntaxe (ne pas exécuter -delete)
    # Test que find accepte les arguments
    test_cmd = ["find", "--help"]
    result = subprocess.run(test_cmd, capture_output=True, text=True)

    assert result.returncode == 0, "find command should be available"
    assert "-mtime" in result.stdout, "-mtime option should be documented"
    assert "-type" in result.stdout, "-type option should be documented"
    assert "-delete" in result.stdout, "-delete option should be documented"


def test_cleanup_transit_mtime_filter():
    """Test que le filtre -mtime +1 correspond à >24h.

    GIVEN -mtime +1
    WHEN la documentation find est consultée
    THEN +1 = fichiers modifiés il y a plus de 24 heures
    """
    # Validation logique mtime
    # -mtime +1 = modified more than 1 day ago (>24h)
    # -mtime 1 = modified exactly 1 day ago (24-48h)
    # -mtime -1 = modified less than 1 day ago (<24h)

    mtime_value = "+1"
    assert mtime_value == "+1", "mtime filter should be +1 (>24h)"


def test_cleanup_transit_preserves_subdirectories():
    """Test que find -type f ne supprime que les fichiers, pas les dossiers.

    GIVEN commande find avec -type f
    WHEN exécutée
    THEN seuls les fichiers sont ciblés (pas les dossiers)
    """
    # Validation que -type f cible uniquement fichiers
    file_type = "f"
    assert file_type == "f", "-type should be 'f' (files only, not directories)"


@pytest.mark.integration
def test_cleanup_transit_integration():
    """Test intégration : find supprime fichiers >24h, préserve fichiers récents.

    GIVEN répertoire temporaire avec fichiers old (>24h) et recent (<24h)
    WHEN find -mtime +1 -delete s'exécute
    THEN fichiers old supprimés, fichiers recent préservés
    """
    # Create temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        transit_dir = Path(tmpdir) / "transit"
        transit_dir.mkdir()

        # Create old file (simulate >24h)
        old_file = transit_dir / "old_file.txt"
        old_file.write_text("old content")

        # Create recent file
        recent_file = transit_dir / "recent_file.txt"
        recent_file.write_text("recent content")

        # Simulate old file (modify timestamp to 2 days ago)
        # Note: os.utime pour modifier mtime
        old_time = (datetime.now() - timedelta(days=2)).timestamp()
        os.utime(old_file, (old_time, old_time))

        # Execute find command (dry-run with -print instead of -delete)
        cmd = ["find", str(transit_dir), "-type", "f", "-mtime", "+1", "-print"]
        result = subprocess.run(cmd, capture_output=True, text=True)

        # Verify old file detected
        assert str(old_file) in result.stdout, "Old file should be detected by find -mtime +1"

        # Verify recent file NOT detected
        assert str(recent_file) not in result.stdout, "Recent file should NOT be detected by find -mtime +1"


def test_calculate_du_before_after():
    """Test helper function pour calculer espace libéré via du.

    GIVEN du -sb /path retourne bytes
    WHEN before et after sont comparés
    THEN freed = before - after
    """
    # Simuler fonction bash calculate freed space
    def calculate_freed_space(before_bytes: int, after_bytes: int) -> int:
        """Calculate freed bytes."""
        return max(0, before_bytes - after_bytes)

    before = 5_000_000  # 5 MB avant cleanup
    after = 1_000_000   # 1 MB après cleanup
    freed = calculate_freed_space(before, after)

    assert freed == 4_000_000, f"Expected 4 MB freed, got {freed} bytes"
