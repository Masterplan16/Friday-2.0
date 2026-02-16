"""
Unit tests for PriorityEngine (Story 3.8, AC3).

Tests:
- Path priority scoring
- Resolution extraction (mocked Pillow)
- EXIF parsing (mocked Pillow)
- Filename scoring
- Keeper selection
- Edge cases
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from agents.src.agents.dedup.models import DedupAction, DedupGroup, FileEntry
from agents.src.agents.dedup.priority_engine import PriorityEngine


@pytest.fixture
def engine():
    """Default priority engine."""
    return PriorityEngine()


# ============================================================================
# Path priority scoring
# ============================================================================


class TestPathPriority:
    """Test path location priority scoring."""

    def test_beestation_photos_highest(self, engine):
        """BeeStation\\Photos = 100."""
        path = Path(r"C:\Users\lopez\BeeStation\Friday\Archives\Photos\vacation.jpg")
        assert engine.get_path_priority(path) == 100

    def test_beestation_documents_highest(self, engine):
        """BeeStation\\Documents = 100."""
        path = Path(r"C:\Users\lopez\BeeStation\Friday\Archives\Documents\facture.pdf")
        assert engine.get_path_priority(path) == 100

    def test_beestation_archives_90(self, engine):
        """BeeStation\\Archives = 90."""
        path = Path(r"C:\Users\lopez\BeeStation\Friday\Archives\misc\file.txt")
        # Will match "BeeStation\\Friday\\Archives" (90) and "BeeStation" (80)
        # Best match wins
        assert engine.get_path_priority(path) == 90

    def test_beestation_generic_80(self, engine):
        """BeeStation root = 80."""
        path = Path(r"C:\Users\lopez\BeeStation\other\file.txt")
        assert engine.get_path_priority(path) == 80

    def test_desktop_50(self, engine):
        """Desktop = 50."""
        path = Path(r"C:\Users\lopez\Desktop\document.pdf")
        assert engine.get_path_priority(path) == 50

    def test_downloads_30(self, engine):
        """Downloads = 30."""
        path = Path(r"C:\Users\lopez\Downloads\file.zip")
        assert engine.get_path_priority(path) == 30

    def test_unknown_path_0(self, engine):
        """Unknown path = 0."""
        path = Path(r"C:\Users\lopez\Documents\random\file.txt")
        assert engine.get_path_priority(path) == 0

    def test_beestation_gt_downloads(self, engine):
        """BeeStation always beats Downloads."""
        bee = Path(r"C:\Users\lopez\BeeStation\Friday\Archives\Photos\photo.jpg")
        dl = Path(r"C:\Users\lopez\Downloads\photo.jpg")
        assert engine.get_path_priority(bee) > engine.get_path_priority(dl)


# ============================================================================
# Resolution extraction
# ============================================================================


class TestResolution:
    """Test image resolution bonus (mocked Pillow)."""

    def test_resolution_bonus_4k(self, engine):
        """4K image -> +50 bonus."""
        mock_img = MagicMock()
        mock_img.size = (3840, 2160)  # 8.3M pixels
        mock_img.__enter__ = MagicMock(return_value=mock_img)
        mock_img.__exit__ = MagicMock(return_value=False)

        with patch("PIL.Image.open", return_value=mock_img):
            path = Path("photo.jpg")
            result = engine.get_resolution_bonus(path)

        assert result == 50

    def test_resolution_bonus_hd(self, engine):
        """HD image -> +30 bonus."""
        mock_img = MagicMock()
        mock_img.size = (1920, 1080)  # 2.1M pixels
        mock_img.__enter__ = MagicMock(return_value=mock_img)
        mock_img.__exit__ = MagicMock(return_value=False)

        with patch("PIL.Image.open", return_value=mock_img):
            path = Path("photo.jpg")
            result = engine.get_resolution_bonus(path)

        assert result == 30

    def test_resolution_bonus_non_image(self, engine):
        """Non-image file -> 0."""
        path = Path("document.pdf")
        assert engine.get_resolution_bonus(path) == 0

    def test_resolution_bonus_corrupted_image(self, engine, tmp_path):
        """Corrupted image -> 0 (no crash)."""
        f = tmp_path / "corrupt.jpg"
        f.write_bytes(b"not an image")
        assert engine.get_resolution_bonus(f) == 0


# ============================================================================
# EXIF parsing
# ============================================================================


class TestExif:
    """Test EXIF date extraction bonus."""

    def test_exif_bonus_with_date(self, engine, tmp_path):
        """Photo with EXIF DateTimeOriginal -> +20."""
        # Create a real JPEG with EXIF would be complex, so mock instead
        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img._getexif.return_value = {36867: "2025:08:15 14:30:00"}
            mock_img.__enter__ = MagicMock(return_value=mock_img)
            mock_img.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_img

            path = Path("photo.jpg")
            result = engine.get_exif_bonus(path)

        assert result == 20

    def test_exif_bonus_no_date(self, engine, tmp_path):
        """Photo without EXIF -> 0."""
        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img._getexif.return_value = None
            mock_img.__enter__ = MagicMock(return_value=mock_img)
            mock_img.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_img

            path = Path("photo.jpg")
            result = engine.get_exif_bonus(path)

        assert result == 0


# ============================================================================
# Filename scoring
# ============================================================================


class TestFilenameScore:
    """Test filename quality scoring."""

    def test_descriptive_name_long(self, engine):
        """Long descriptive name (>20 chars) -> 30."""
        path = Path("vacances_grece_famille_2025.jpg")
        assert engine.get_filename_score(path) == 30

    def test_medium_name(self, engine):
        """Medium name (10-20 chars) -> 15."""
        path = Path("facture_edf.pdf")
        assert engine.get_filename_score(path) == 15

    def test_short_name(self, engine):
        """Short name (<10 chars) -> 5."""
        path = Path("file.txt")
        assert engine.get_filename_score(path) == 5

    def test_generic_pattern_img(self, engine):
        """IMG_1234.jpg -> 0."""
        path = Path("IMG_20250815_143000.jpg")
        assert engine.get_filename_score(path) == 0

    def test_generic_pattern_dsc(self, engine):
        """DSC_1234.jpg -> 0."""
        path = Path("DSC_00456.jpg")
        assert engine.get_filename_score(path) == 0

    def test_generic_pattern_screenshot(self, engine):
        """Screenshot_* -> 0."""
        path = Path("Screenshot_2025-08-15.png")
        assert engine.get_filename_score(path) == 0

    def test_copy_suffix_penalty(self, engine):
        """Filename with (1) suffix -> -10."""
        path = Path("document (1).pdf")
        assert engine.get_filename_score(path) == -10

    def test_copy_suffix_underscore(self, engine):
        """Filename with _copy suffix -> -10."""
        path = Path("document_copy.pdf")
        assert engine.get_filename_score(path) == -10


# ============================================================================
# Keeper selection
# ============================================================================


class TestSelectKeeper:
    """Test keeper selection from duplicate groups."""

    def test_select_keeper_highest_score(self, engine):
        """Best score = keeper."""
        group = DedupGroup(
            group_id=1,
            sha256_hash="abc123",
            files=[
                FileEntry(
                    file_path=Path(r"C:\Users\lopez\Downloads\photo.jpg"),
                    sha256_hash="abc123",
                    size_bytes=1000,
                ),
                FileEntry(
                    file_path=Path(r"C:\Users\lopez\BeeStation\Friday\Archives\Photos\photo.jpg"),
                    sha256_hash="abc123",
                    size_bytes=1000,
                ),
            ],
        )

        result = engine.select_keeper(group)

        assert result.keeper is not None
        assert "BeeStation" in str(result.keeper.file_path)
        assert result.keeper.action == DedupAction.keep
        assert len(result.to_delete) == 1
        assert result.to_delete[0].action == DedupAction.delete

    def test_select_keeper_single_file(self, engine):
        """Single file group -> file is keeper."""
        group = DedupGroup(
            group_id=1,
            sha256_hash="abc123",
            files=[
                FileEntry(
                    file_path=Path(r"C:\Users\lopez\Desktop\file.txt"),
                    sha256_hash="abc123",
                    size_bytes=500,
                ),
            ],
        )

        result = engine.select_keeper(group)
        assert result.keeper is not None
        assert result.keeper.action == DedupAction.keep
        assert len(result.to_delete) == 0

    def test_select_keeper_three_files(self, engine):
        """3 files -> 1 keeper + 2 delete."""
        group = DedupGroup(
            group_id=1,
            sha256_hash="abc123",
            files=[
                FileEntry(
                    file_path=Path(r"C:\Users\lopez\Downloads\file (1).txt"),
                    sha256_hash="abc123",
                    size_bytes=1000,
                ),
                FileEntry(
                    file_path=Path(r"C:\Users\lopez\Desktop\important_document_review.txt"),
                    sha256_hash="abc123",
                    size_bytes=1000,
                ),
                FileEntry(
                    file_path=Path(r"C:\Users\lopez\Downloads\file.txt"),
                    sha256_hash="abc123",
                    size_bytes=1000,
                ),
            ],
        )

        result = engine.select_keeper(group)

        assert result.keeper is not None
        assert len(result.to_delete) == 2
        # Desktop + descriptive name should win over Downloads
        assert "Desktop" in str(result.keeper.file_path)
