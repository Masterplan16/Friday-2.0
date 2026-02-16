"""
Unit tests for ReportGenerator (Story 3.8, AC4).

Tests:
- CSV generation with all columns
- Header statistics
- UTF-8 encoding (accents in filenames)
"""

from datetime import datetime
from pathlib import Path

import pytest

from agents.src.agents.dedup.models import (
    DedupAction,
    DedupGroup,
    FileEntry,
    ScanResult,
)
from agents.src.agents.dedup.report_generator import ReportGenerator


@pytest.fixture
def generator():
    """Default report generator."""
    return ReportGenerator()


@pytest.fixture
def sample_result():
    """Sample scan result with 2 groups."""
    return ScanResult(
        scan_date=datetime(2026, 2, 16, 14, 35, 22),
        total_scanned=45328,
        duplicate_groups_count=2,
        total_duplicates=3,
        space_reclaimable_bytes=15_200_000_000,
        space_reclaimable_gb=14.15,
        groups=[
            DedupGroup(
                group_id=1,
                sha256_hash="abc123def456789012345678901234567890123456789012345678901234",
                files=[
                    FileEntry(
                        file_path=Path(r"C:\Users\lopez\BeeStation\Friday\Archives\Photos\vacances.jpg"),
                        sha256_hash="abc123def456789012345678901234567890123456789012345678901234",
                        size_bytes=2_458_000,
                        action=DedupAction.keep,
                        priority_score=100,
                        reason="BeeStation path",
                        resolution="3840x2160",
                        filename_score=30,
                    ),
                    FileEntry(
                        file_path=Path(r"C:\Users\lopez\Downloads\vacances.jpg"),
                        sha256_hash="abc123def456789012345678901234567890123456789012345678901234",
                        size_bytes=2_458_000,
                        action=DedupAction.delete,
                        priority_score=30,
                        reason="Lower priority path",
                        resolution="3840x2160",
                        filename_score=30,
                    ),
                ],
            ),
            DedupGroup(
                group_id=2,
                sha256_hash="def456abc789012345678901234567890123456789012345678901234567",
                files=[
                    FileEntry(
                        file_path=Path(r"C:\Users\lopez\Desktop\facture.pdf"),
                        sha256_hash="def456abc789012345678901234567890123456789012345678901234567",
                        size_bytes=458_000,
                        action=DedupAction.keep,
                        priority_score=50,
                        reason="Desktop path",
                        filename_score=15,
                    ),
                    FileEntry(
                        file_path=Path(r"C:\Users\lopez\Downloads\facture (1).pdf"),
                        sha256_hash="def456abc789012345678901234567890123456789012345678901234567",
                        size_bytes=458_000,
                        action=DedupAction.delete,
                        priority_score=30,
                        reason="Duplicate suffix",
                        filename_score=-10,
                    ),
                ],
            ),
        ],
    )


class TestCSVGeneration:
    """Test CSV report generation."""

    def test_csv_generation_columns(self, generator, sample_result, tmp_path):
        """All expected columns present in CSV."""
        output_path = tmp_path / "report.csv"
        generator.generate_csv(sample_result, output_path)

        content = output_path.read_text(encoding="utf-8")

        # Check all columns in header
        for col in ReportGenerator.CSV_COLUMNS:
            assert col in content, f"Column {col} missing from CSV"

    def test_csv_header_stats(self, generator, sample_result, tmp_path):
        """Header statistics present as comments."""
        output_path = tmp_path / "report.csv"
        generator.generate_csv(sample_result, output_path)

        content = output_path.read_text(encoding="utf-8")

        assert "# Scan Date: 2026-02-16 14:35:22" in content
        assert "# Total Files Scanned: 45,328" in content
        assert "# Duplicate Groups: 2" in content
        assert "# Space Reclaimable:" in content

    def test_csv_encoding_utf8(self, generator, tmp_path):
        """CSV supports filenames with accents."""
        result = ScanResult(
            total_scanned=100,
            duplicate_groups_count=1,
            total_duplicates=1,
            space_reclaimable_bytes=1000,
            space_reclaimable_gb=0.0,
            groups=[
                DedupGroup(
                    group_id=1,
                    sha256_hash="abc123",
                    files=[
                        FileEntry(
                            file_path=Path(r"C:\Users\lopez\Documents\relevé_bancaire_février.pdf"),
                            sha256_hash="abc123",
                            size_bytes=1000,
                            action=DedupAction.keep,
                            priority_score=50,
                            reason="test",
                        ),
                        FileEntry(
                            file_path=Path(r"C:\Users\lopez\Downloads\relevé_bancaire_février (1).pdf"),
                            sha256_hash="abc123",
                            size_bytes=1000,
                            action=DedupAction.delete,
                            priority_score=30,
                            reason="duplicate",
                        ),
                    ],
                ),
            ],
        )

        output_path = tmp_path / "report_accents.csv"
        generator.generate_csv(result, output_path)

        content = output_path.read_text(encoding="utf-8")
        assert "relevé_bancaire_février" in content
