"""
E2E test for complete dedup workflow (Story 3.8).

Tests the full pipeline: scan -> priority -> report -> delete.
Uses real filesystem, mocked send2trash, no external services needed.
"""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.src.agents.dedup.deleter import SafeDeleter
from agents.src.agents.dedup.models import ScanConfig
from agents.src.agents.dedup.priority_engine import PriorityEngine
from agents.src.agents.dedup.report_generator import ReportGenerator
from agents.src.agents.dedup.scanner import DedupScanner


def _create_realistic_tree(root: Path) -> dict:
    """
    Create realistic file tree simulating user's PC.

    Structure:
        root/
            BeeStation/Friday/Archives/Photos/
                vacation_paris.jpg  (keeper - highest priority)
            Desktop/
                vacation_paris (1).jpg  (dup - copy on Desktop)
                rapport_financier.pdf  (unique)
            Downloads/
                vacation_paris.jpg  (dup - also in Downloads)
                facture_edf_2025.pdf  (dup C)
            Documents/
                facture_edf_2025.pdf  (dup C - same in Documents)
    """
    # BeeStation (highest priority = 100)
    bee_photos = root / "BeeStation" / "Friday" / "Archives" / "Photos"
    bee_photos.mkdir(parents=True)

    # Desktop (priority = 50)
    desktop = root / "Desktop"
    desktop.mkdir()

    # Downloads (priority = 30)
    downloads = root / "Downloads"
    downloads.mkdir()

    # Documents (priority = 0, unknown)
    documents = root / "Documents"
    documents.mkdir()

    # Dup group A: vacation photo (3 copies)
    photo_content = b"JPEG vacation photo data " * 200  # ~5KB
    (bee_photos / "vacation_paris.jpg").write_bytes(photo_content)
    (desktop / "vacation_paris (1).jpg").write_bytes(photo_content)
    (downloads / "vacation_paris.jpg").write_bytes(photo_content)

    # Dup group B: facture (2 copies)
    facture_content = b"PDF facture EDF content " * 150
    (downloads / "facture_edf_2025.pdf").write_bytes(facture_content)
    (documents / "facture_edf_2025.pdf").write_bytes(facture_content)

    # Unique files
    (desktop / "rapport_financier.pdf").write_bytes(b"unique rapport" * 100)

    return {
        "total_files": 6,
        "dup_groups": 2,
        "total_duplicates": 3,  # (3-1) + (2-1) = 3
        "photo_hash": hashlib.sha256(photo_content).hexdigest(),
        "facture_hash": hashlib.sha256(facture_content).hexdigest(),
    }


@pytest.mark.asyncio
async def test_complete_dedup_workflow(tmp_path):
    """
    E2E: Full dedup workflow from scan to deletion.

    Verifies:
    1. Scan finds all duplicates (AC1 + AC2)
    2. Priority selects BeeStation as keeper (AC3)
    3. CSV report generated correctly (AC5)
    4. Safety checks pass (AC6)
    5. Deletion targets correct files (AC7)
    """
    info = _create_realistic_tree(tmp_path)

    # === Phase 1: SCAN ===
    config = ScanConfig(
        root_path=tmp_path,
        min_file_size=1,
        excluded_folders=set(),
    )
    scanner = DedupScanner(config=config)
    result = await scanner.scan()

    assert result.total_scanned == info["total_files"]
    assert result.duplicate_groups_count == info["dup_groups"]
    assert result.total_duplicates == info["total_duplicates"]

    # === Phase 2: PRIORITY SELECTION ===
    engine = PriorityEngine()
    for group in result.groups:
        selection = engine.select_keeper(group)

        if group.sha256_hash == info["photo_hash"]:
            # BeeStation should be keeper (highest path priority = 100)
            assert "BeeStation" in str(selection.keeper.file_path)
            assert len(selection.to_delete) == 2
        elif group.sha256_hash == info["facture_hash"]:
            assert selection.keeper is not None
            assert len(selection.to_delete) == 1

    # === Phase 3: CSV REPORT ===
    generator = ReportGenerator(priority_engine=engine)
    report_path = tmp_path / "dedup_report.csv"
    generator.generate_csv(result, report_path)

    assert report_path.exists()
    csv_content = report_path.read_text(encoding="utf-8")
    assert "keep" in csv_content
    assert "delete" in csv_content
    assert "BeeStation" in csv_content

    # === Phase 4: DELETION (mocked send2trash) ===
    deleted_files = []

    def track_deletions(path_str):
        deleted_files.append(path_str)

    deleter = SafeDeleter(excluded_folders=set())

    with patch("send2trash.send2trash", side_effect=track_deletions):
        deletion_result = await deleter.delete_duplicates(result.groups)

    # 3 duplicates should be deleted (2 photo copies + 1 facture copy)
    assert deletion_result.deleted == 3
    assert deletion_result.skipped == 0
    assert deletion_result.errors == 0
    assert len(deleted_files) == 3

    # BeeStation file should NOT be in deleted list
    for deleted_path in deleted_files:
        assert "BeeStation" not in deleted_path, (
            f"BeeStation keeper incorrectly deleted: {deleted_path}"
        )

    # Verify keeper files would still exist (send2trash was mocked)
    bee_photo = tmp_path / "BeeStation" / "Friday" / "Archives" / "Photos" / "vacation_paris.jpg"
    assert bee_photo.exists(), "BeeStation keeper should still exist"
