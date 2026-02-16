"""
Batch deletion with safety checks (Story 3.8).

Features:
- 4 safety checks before each deletion
- send2trash (Corbeille Windows, rollback possible)
- Progress tracking with Telegram updates
- Audit trail logging

AC6: Suppression batch avec safety checks
AC7: Securite & rollback
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Callable, Optional

import structlog

from agents.src.agents.dedup.models import (
    DedupAction,
    DedupGroup,
    FileEntry,
)

logger = structlog.get_logger(__name__)


class DeletionResult:
    """Result of batch deletion."""

    def __init__(self):
        self.total_to_delete: int = 0
        self.deleted: int = 0
        self.skipped: int = 0
        self.errors: int = 0
        self.space_reclaimed_bytes: int = 0
        self.skip_reasons: list[tuple[str, str]] = []  # (file_path, reason)
        self.error_details: list[tuple[str, str]] = []  # (file_path, error)
        self.deleted_files: list[str] = []

    @property
    def space_reclaimed_gb(self) -> float:
        return round(self.space_reclaimed_bytes / (1024**3), 2)


class SafeDeleter:
    """
    Batch file deleter with safety checks and send2trash.

    Safety checks (per file):
    1. File still exists
    2. Hash still matches (not modified since scan)
    3. Not in system/excluded zone
    4. Keeper file exists in the same group
    """

    def __init__(
        self,
        excluded_folders: Optional[set[str]] = None,
        chunk_size: int = 65536,
        progress_callback: Optional[Callable[[DeletionResult], None]] = None,
    ):
        """
        Initialize deleter.

        Args:
            excluded_folders: System folders to double-check exclusion
            chunk_size: For re-hashing verification
            progress_callback: Called after each file for progress updates
        """
        self.excluded_folders = (
            excluded_folders
            if excluded_folders is not None
            else {
                "windows",
                "program files",
                "program files (x86)",
                "appdata\\local\\temp",
                "$recycle.bin",
            }
        )
        self.chunk_size = chunk_size
        self.progress_callback = progress_callback
        self._cancelled = False

    def cancel(self) -> None:
        """Cancel the deletion."""
        self._cancelled = True

    async def delete_duplicates(
        self,
        groups: list[DedupGroup],
    ) -> DeletionResult:
        """
        Delete all files marked as 'delete' in duplicate groups.

        Args:
            groups: Duplicate groups with keeper/delete selections

        Returns:
            DeletionResult with counts and details

        AC6: Batch deletion with safety
        AC7: send2trash for rollback
        """
        result = DeletionResult()
        self._cancelled = False

        import send2trash as _send2trash

        # Count total to delete
        for group in groups:
            result.total_to_delete += len(group.to_delete)

        logger.info(
            "dedup_deletion_started",
            total_to_delete=result.total_to_delete,
            groups=len(groups),
        )

        for group in groups:
            if self._cancelled:
                logger.info("dedup_deletion_cancelled")
                break

            for entry in group.to_delete:
                if self._cancelled:
                    break

                # Run 4 safety checks
                safe, reason = self._safety_check(entry, group)

                if not safe:
                    result.skipped += 1
                    result.skip_reasons.append((str(entry.file_path), reason))
                    logger.debug(
                        "dedup_file_skipped",
                        file_path=str(entry.file_path),
                        reason=reason,
                    )
                    continue

                # Delete via send2trash (Corbeille Windows)
                try:
                    try:
                        file_size = entry.file_path.stat().st_size
                    except OSError:
                        file_size = entry.size_bytes
                    _send2trash.send2trash(str(entry.file_path))

                    result.deleted += 1
                    result.space_reclaimed_bytes += file_size
                    result.deleted_files.append(str(entry.file_path))

                    logger.info(
                        "dedup_file_deleted",
                        file_path=str(entry.file_path),
                        size_bytes=file_size,
                    )

                except PermissionError as e:
                    result.errors += 1
                    result.error_details.append((str(entry.file_path), f"Permission denied: {e}"))
                    logger.warning(
                        "dedup_delete_permission_denied",
                        file_path=str(entry.file_path),
                    )
                except Exception as e:
                    result.errors += 1
                    result.error_details.append((str(entry.file_path), str(e)))
                    logger.error(
                        "dedup_delete_failed",
                        file_path=str(entry.file_path),
                        error=str(e),
                    )

                # Progress callback
                if self.progress_callback:
                    self.progress_callback(result)

        logger.info(
            "dedup_deletion_completed",
            deleted=result.deleted,
            skipped=result.skipped,
            errors=result.errors,
            space_reclaimed_gb=result.space_reclaimed_gb,
        )

        return result

    def _safety_check(
        self,
        entry: FileEntry,
        group: DedupGroup,
    ) -> tuple[bool, str]:
        """
        Run 4 safety checks before deleting a file.

        Returns:
            (is_safe, reason_if_not_safe)

        AC6: Safety checks
        """
        file_path = entry.file_path

        # Check 1: File still exists
        if not file_path.exists():
            return False, "File no longer exists"

        # Check 2: Hash still matches (not modified since scan)
        try:
            current_hash = self._hash_file(file_path)
            if current_hash != entry.sha256_hash:
                return False, "Hash mismatch (file modified since scan)"
        except (OSError, PermissionError) as e:
            return False, f"Cannot read file for hash check: {e}"

        # Check 3: Not in system/excluded zone
        path_str_lower = str(file_path).lower()
        for excl in self.excluded_folders:
            if "\\" + excl + "\\" in path_str_lower:
                return False, f"File in excluded zone: {excl}"

        # Check 4: Keeper still exists
        if group.keeper is not None:
            if not group.keeper.file_path.exists():
                return False, "Keeper file no longer exists"

        return True, ""

    def _hash_file(self, file_path: Path) -> str:
        """Compute SHA256 hash for verification."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(self.chunk_size):
                sha256.update(chunk)
        return sha256.hexdigest()
