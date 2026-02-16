"""
CSV dry-run report generator for dedup results (Story 3.8).

Generates CSV report with:
- Header statistics (comments)
- Columns: group_id, hash, file_path, size, action, priority_score, etc.
- UTF-8 encoding (accents in filenames)

AC4: Rapport CSV dry-run obligatoire
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

from agents.src.agents.dedup.models import DedupGroup, ScanResult
from agents.src.agents.dedup.priority_engine import PriorityEngine

logger = structlog.get_logger(__name__)


class ReportGenerator:
    """
    Generate CSV dry-run report from scan results.

    Features:
    - Header stats as CSV comments
    - Full columns with scores and reasons
    - UTF-8 encoding support
    """

    CSV_COLUMNS = [
        "group_id",
        "hash",
        "file_path",
        "size_bytes",
        "size_mb",
        "action",
        "priority_score",
        "reason",
        "resolution",
        "exif_date",
        "filename_score",
    ]

    def __init__(self, priority_engine: Optional[PriorityEngine] = None):
        """
        Initialize report generator.

        Args:
            priority_engine: Engine for resolution/EXIF extraction (optional)
        """
        self.priority_engine = priority_engine or PriorityEngine()

    def generate_csv(
        self,
        scan_result: ScanResult,
        output_path: Path,
    ) -> Path:
        """
        Generate CSV report file.

        Args:
            scan_result: Scan result with duplicate groups
            output_path: Where to save the CSV file

        Returns:
            Path to generated CSV file

        AC4: CSV generation with header stats
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            # Write header statistics as comments
            self._write_header_stats(f, scan_result)

            # Write CSV data
            writer = csv.DictWriter(f, fieldnames=self.CSV_COLUMNS)
            writer.writeheader()

            for group in scan_result.groups:
                for entry in group.files:
                    # Extract resolution and EXIF for images
                    resolution = entry.resolution
                    exif_date = entry.exif_date

                    if resolution is None:
                        resolution = self.priority_engine.get_resolution_string(entry.file_path)
                    if exif_date is None:
                        exif_date = self.priority_engine.get_exif_date_string(entry.file_path)

                    writer.writerow(
                        {
                            "group_id": group.group_id,
                            "hash": entry.sha256_hash[:12] + "...",
                            "file_path": str(entry.file_path),
                            "size_bytes": entry.size_bytes,
                            "size_mb": round(entry.size_bytes / (1024 * 1024), 2),
                            "action": entry.action.value,
                            "priority_score": entry.priority_score,
                            "reason": entry.reason,
                            "resolution": resolution or "-",
                            "exif_date": exif_date or "-",
                            "filename_score": entry.filename_score,
                        }
                    )

        logger.info(
            "dedup_report_generated",
            output_path=str(output_path),
            groups=len(scan_result.groups),
        )

        return output_path

    def generate_csv_string(self, scan_result: ScanResult) -> str:
        """
        Generate CSV content as string (for Telegram attachment).

        Args:
            scan_result: Scan result with duplicate groups

        Returns:
            CSV content as string
        """
        output = io.StringIO()

        self._write_header_stats(output, scan_result)

        writer = csv.DictWriter(output, fieldnames=self.CSV_COLUMNS)
        writer.writeheader()

        for group in scan_result.groups:
            for entry in group.files:
                writer.writerow(
                    {
                        "group_id": group.group_id,
                        "hash": entry.sha256_hash[:12] + "...",
                        "file_path": str(entry.file_path),
                        "size_bytes": entry.size_bytes,
                        "size_mb": round(entry.size_bytes / (1024 * 1024), 2),
                        "action": entry.action.value,
                        "priority_score": entry.priority_score,
                        "reason": entry.reason,
                        "resolution": entry.resolution or "-",
                        "exif_date": entry.exif_date or "-",
                        "filename_score": entry.filename_score,
                    }
                )

        return output.getvalue()

    @staticmethod
    def _write_header_stats(f, scan_result: ScanResult) -> None:
        """Write header statistics as CSV comments."""
        total_delete = sum(
            1
            for group in scan_result.groups
            for entry in group.files
            if entry.action.value == "delete"
        )

        f.write(f"# Scan Date: {scan_result.scan_date.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Total Files Scanned: {scan_result.total_scanned:,}\n")
        f.write(f"# Duplicate Groups: {scan_result.duplicate_groups_count:,}\n")
        f.write(
            f"# Total Duplicates: {total_delete} files "
            f"({scan_result.space_reclaimable_gb:.1f} GB)\n"
        )
        f.write(f"# Space Reclaimable: {scan_result.space_reclaimable_gb:.1f} GB\n")
