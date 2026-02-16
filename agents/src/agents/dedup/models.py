"""
Pydantic models for dedup agent (Story 3.8).

Models:
- ScanConfig: Scan configuration (paths, exclusions, limits)
- ScanStats: Real-time scan statistics
- ScanResult: Final scan result
- FileEntry: Single file with metadata
- DedupGroup: Group of duplicate files (same SHA256)
- DedupJob: Audit trail record
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class DedupAction(str, Enum):
    """Action to take on a file in a dedup group."""

    keep = "keep"
    delete = "delete"


class DedupJobStatus(str, Enum):
    """Status of a dedup job."""

    scanning = "scanning"
    report_ready = "report_ready"
    deleting = "deleting"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ScanConfig(BaseModel):
    """Configuration for a dedup scan."""

    root_path: Path = Field(description="Root directory to scan")
    priority_paths: dict[str, int] = Field(
        default_factory=lambda: {
            "BeeStation\\Friday\\Archives\\Photos": 100,
            "BeeStation\\Friday\\Archives\\Documents": 100,
            "BeeStation\\Friday\\Archives": 90,
            "BeeStation": 80,
            "Desktop": 50,
            "Downloads": 30,
            "Temp": 10,
        },
        description="Path fragments to priority scores (higher = keep)",
    )
    excluded_folders: set[str] = Field(
        default_factory=lambda: {
            "windows",
            "program files",
            "program files (x86)",
            "appdata\\local\\temp",
            "$recycle.bin",
        },
        description="Folder names/paths to exclude (lowercased)",
    )
    excluded_dev_folders: set[str] = Field(
        default_factory=lambda: {
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "venv",
        },
        description="Dev folder names to exclude",
    )
    excluded_extensions: set[str] = Field(
        default_factory=lambda: {
            ".sys",
            ".dll",
            ".exe",
            ".msi",
            ".tmp",
            ".cache",
            ".log",
        },
        description="File extensions to exclude (lowercased)",
    )
    excluded_filenames: set[str] = Field(
        default_factory=lambda: {
            "desktop.ini",
            ".ds_store",
            "thumbs.db",
        },
        description="Exact filenames to exclude (lowercased)",
    )
    min_file_size: int = Field(
        default=100,
        description="Minimum file size in bytes (skip smaller)",
    )
    max_file_size: int = Field(
        default=2 * 1024 * 1024 * 1024,  # 2 GB
        description="Maximum file size in bytes (skip larger)",
    )
    chunk_size: int = Field(
        default=65536,
        description="SHA256 hashing chunk size in bytes",
    )
    scan_timeout_hours: int = Field(
        default=4,
        description="Abort scan if exceeds this duration",
    )


class ScanStats(BaseModel):
    """Real-time scan statistics."""

    total_scanned: int = 0
    total_skipped: int = 0
    total_errors: int = 0
    duplicate_groups: int = 0
    total_duplicates: int = 0
    space_reclaimable_bytes: int = 0
    current_directory: str = ""


class FileEntry(BaseModel):
    """Single file entry with metadata."""

    file_path: Path
    sha256_hash: str
    size_bytes: int
    action: DedupAction = DedupAction.keep
    priority_score: int = 0
    reason: str = ""
    resolution: Optional[str] = None
    exif_date: Optional[str] = None
    filename_score: int = 0


class DedupGroup(BaseModel):
    """Group of duplicate files sharing the same SHA256 hash."""

    group_id: int
    sha256_hash: str
    files: list[FileEntry] = Field(default_factory=list)
    keeper: Optional[FileEntry] = None
    to_delete: list[FileEntry] = Field(default_factory=list)


class ScanResult(BaseModel):
    """Final scan result."""

    scan_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_scanned: int = 0
    duplicate_groups_count: int = 0
    total_duplicates: int = 0
    space_reclaimable_bytes: int = 0
    space_reclaimable_gb: float = 0.0
    groups: list[DedupGroup] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class DedupJob(BaseModel):
    """Dedup job audit trail record (maps to core.dedup_jobs)."""

    dedup_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    scan_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_scanned: int = 0
    duplicate_groups: int = 0
    files_deleted: int = 0
    space_reclaimed_gb: float = 0.0
    csv_report_path: Optional[str] = None
    status: DedupJobStatus = DedupJobStatus.scanning
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
