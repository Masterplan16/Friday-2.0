"""
Integration tests for dedup scan pipeline (Story 3.8).

Tests:
- Full scan + duplicate grouping + priority selection
- CSV report generation from scan results
- Deletion safety checks with real filesystem
- Deletion recovery (send2trash -> Recycle Bin)
- End-to-end: scan -> priority -> report -> delete

All tests use real filesystem (tmpdir) but mock send2trash.
"""

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.src.agents.dedup.deleter import SafeDeleter
from agents.src.agents.dedup.models import ScanConfig
from agents.src.agents.dedup.priority_engine import PriorityEngine
from agents.src.agents.dedup.report_generator import ReportGenerator
from agents.src.agents.dedup.scanner import DedupScanner


def _create_test_tree(root: Path) -> dict:
    """
    Create a realistic file tree for testing.

    Structure:
        root/
            photos/
                vacation_paris_2025.jpg  (unique)
                IMG_20250815.jpg  (dup A)
                screenshot.png  (unique)
            downloads/
                IMG_20250815 (1).jpg  (dup A - copy)
                document.pdf  (dup B)
            desktop/
                document (1).pdf  (dup B - copy)
                notes.txt  (unique)

    Returns dict with file paths and content hashes.
    """
    photos = root / "photos"
    downloads = root / "downloads"
    desktop = root / "desktop"
    photos.mkdir()
    downloads.mkdir()
    desktop.mkdir()

    # Duplicate group A: same photo
    content_a = b"JPEG photo content " * 100  # ~2KB
    (photos / "IMG_20250815.jpg").write_bytes(content_a)
    (downloads / "IMG_20250815 (1).jpg").write_bytes(content_a)

    # Duplicate group B: same PDF
    content_b = b"PDF document content " * 100
    (downloads / "document.pdf").write_bytes(content_b)
    (desktop / "document (1).pdf").write_bytes(content_b)

    # Unique files
    (photos / "vacation_paris_2025.jpg").write_bytes(b"unique photo A" * 50)
    (photos / "screenshot.png").write_bytes(b"unique screenshot" * 50)
    (desktop / "notes.txt").write_bytes(b"unique notes" * 50)

    return {
        "hash_a": hashlib.sha256(content_a).hexdigest(),
        "hash_b": hashlib.sha256(content_b).hexdigest(),
        "total_files": 7,
        "dup_groups": 2,
        "total_duplicates": 2,  # (2-1) + (2-1) = 2
    }


@pytest.mark.asyncio
async def test_full_scan_finds_duplicates(tmp_path):
    """
    Integration: scan real files -> correct duplicate groups.

    AC1 + AC2: Scan recursif + SHA256 grouping.
    """
    info = _create_test_tree(tmp_path)

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

    # Verify hashes
    group_hashes = {g.sha256_hash for g in result.groups}
    assert info["hash_a"] in group_hashes
    assert info["hash_b"] in group_hashes


@pytest.mark.asyncio
async def test_priority_selects_best_keeper(tmp_path):
    """
    Integration: scan -> priority engine selects correct keeper.

    AC3: Priority rules (path > filename > copy detection).
    """
    _create_test_tree(tmp_path)

    config = ScanConfig(
        root_path=tmp_path,
        min_file_size=1,
        excluded_folders=set(),
    )
    scanner = DedupScanner(config=config)
    result = await scanner.scan()

    engine = PriorityEngine()

    for group in result.groups:
        selection = engine.select_keeper(group)

        assert selection.keeper is not None
        assert len(selection.to_delete) == 1

        # Keeper should always have highest priority score
        keeper_score = selection.keeper.priority_score
        for to_del in selection.to_delete:
            assert keeper_score >= to_del.priority_score, (
                f"Keeper score {keeper_score} < delete score {to_del.priority_score}"
            )


@pytest.mark.asyncio
async def test_csv_report_from_scan(tmp_path):
    """
    Integration: scan -> priority -> CSV report.

    AC5: CSV report generation.
    """
    _create_test_tree(tmp_path)

    config = ScanConfig(
        root_path=tmp_path,
        min_file_size=1,
        excluded_folders=set(),
    )
    scanner = DedupScanner(config=config)
    result = await scanner.scan()

    engine = PriorityEngine()
    for group in result.groups:
        engine.select_keeper(group)

    generator = ReportGenerator()
    report_path = tmp_path / "dedup_report.csv"
    generator.generate_csv(result, report_path)

    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")

    # Header stats present (English format from report_generator.py)
    assert "# Scan Date:" in content
    assert "# Total Files Scanned:" in content
    assert "# Duplicate Groups:" in content

    # CSV data present (at least header + 2 groups * 2 files each = 4 data rows)
    lines = [line for line in content.split("\n") if line and not line.startswith("#")]
    assert len(lines) >= 5  # header + 4 data rows


@pytest.mark.asyncio
async def test_deletion_safety_with_real_files(tmp_path):
    """
    Integration: scan -> priority -> safety checks -> deletion.

    AC6: 4 safety checks pass on real files.
    AC7: send2trash (mocked) called correctly.
    """
    _create_test_tree(tmp_path)

    config = ScanConfig(
        root_path=tmp_path,
        min_file_size=1,
        excluded_folders=set(),
    )
    scanner = DedupScanner(config=config)
    result = await scanner.scan()

    engine = PriorityEngine()
    for group in result.groups:
        engine.select_keeper(group)

    deleter = SafeDeleter(excluded_folders=set())

    with patch("send2trash.send2trash") as mock_s2t:
        deletion_result = await deleter.delete_duplicates(result.groups)

    assert deletion_result.deleted == 2  # 2 duplicates deleted
    assert deletion_result.skipped == 0
    assert deletion_result.errors == 0
    assert mock_s2t.call_count == 2


@pytest.mark.asyncio
async def test_deletion_skips_modified_file(tmp_path):
    """
    Integration: file modified between scan and deletion -> skipped.

    AC6: Safety check #2 (hash mismatch).
    """
    _create_test_tree(tmp_path)

    config = ScanConfig(
        root_path=tmp_path,
        min_file_size=1,
        excluded_folders=set(),
    )
    scanner = DedupScanner(config=config)
    result = await scanner.scan()

    engine = PriorityEngine()
    for group in result.groups:
        engine.select_keeper(group)

    # Modify one file after scan (simulating user edit)
    for group in result.groups:
        if group.to_delete:
            first_delete = group.to_delete[0]
            first_delete.file_path.write_bytes(b"MODIFIED CONTENT!")
            break

    deleter = SafeDeleter(excluded_folders=set())

    with patch("send2trash.send2trash") as mock_s2t:
        deletion_result = await deleter.delete_duplicates(result.groups)

    # One file skipped (hash mismatch), one deleted
    assert deletion_result.deleted == 1
    assert deletion_result.skipped == 1
    assert deletion_result.errors == 0
