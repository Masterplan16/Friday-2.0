"""
PC-wide file scanner with SHA256 deduplication (Story 3.8).

Features:
- Recursive scan with Path.rglob()
- Smart exclusions (system paths, dev folders, extensions)
- Chunked SHA256 hashing (65536 bytes)
- In-memory hash cache for performance
- Priority path ordering (BeeStation first)
- Progress callback for Telegram updates

AC1: Scan PC-wide recursif avec exclusions intelligentes
AC2: Deduplication SHA256 avec cache intelligent
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Callable, Optional

import structlog

from agents.src.agents.dedup.models import (
    DedupGroup,
    FileEntry,
    ScanConfig,
    ScanResult,
    ScanStats,
)

logger = structlog.get_logger(__name__)


class DedupScanner:
    """
    PC-wide file scanner with SHA256 deduplication.

    Features:
    - Recursive scan with Path.rglob()
    - Smart exclusions (system paths, dev folders)
    - Chunked SHA256 hashing (65536 bytes)
    - In-memory cache for performance
    - Priority path ordering
    """

    def __init__(
        self,
        config: ScanConfig,
        progress_callback: Optional[Callable[[ScanStats], None]] = None,
    ):
        """
        Initialize scanner.

        Args:
            config: Scan configuration
            progress_callback: Optional callback for real-time progress updates
        """
        self.config = config
        self.progress_callback = progress_callback
        self.hash_cache: dict[str, str] = {}  # path_str -> sha256
        self.size_cache: dict[str, int] = {}  # path_str -> size
        self._hash_groups: dict[str, list[str]] = {}  # sha256 -> [path_str, ...]
        self.stats = ScanStats()
        self._start_time: float = 0.0
        self._cancelled = False
        self._dup_groups_count: int = 0

    def cancel(self) -> None:
        """Cancel the scan."""
        self._cancelled = True

    async def scan(self) -> ScanResult:
        """
        Main scan entry point.

        Steps:
        1. Scan priority paths first (BeeStation)
        2. Scan remaining paths
        3. Group duplicates by hash
        4. Return results

        Returns:
            ScanResult with duplicate groups

        AC1: Scan recursif avec exclusions
        AC2: Deduplication SHA256
        """
        self._start_time = time.time()
        self._cancelled = False

        logger.info(
            "dedup_scan_started",
            root_path=str(self.config.root_path),
            priority_paths=len(self.config.priority_paths),
        )

        # Check timeout
        timeout_seconds = self.config.scan_timeout_hours * 3600

        # Phase 1: Scan priority paths first (highest score first)
        sorted_priorities = sorted(
            self.config.priority_paths.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        scanned_paths: set[str] = set()

        for priority_fragment, _score in sorted_priorities:
            if self._cancelled:
                break

            # Build full priority path
            priority_path = self.config.root_path / priority_fragment
            if priority_path.exists() and priority_path.is_dir():
                await self._scan_directory(
                    priority_path, scanned_paths, timeout_seconds
                )

        # Phase 2: Scan remaining paths under root
        if not self._cancelled:
            await self._scan_directory(
                self.config.root_path, scanned_paths, timeout_seconds
            )

        # Phase 3: Build duplicate groups
        groups = self._build_duplicate_groups()

        # Calculate space reclaimable
        space_reclaimable = 0
        total_duplicates = 0
        for group in groups:
            # All files except the first are duplicates
            for entry in group.files[1:]:
                space_reclaimable += entry.size_bytes
                total_duplicates += 1

        result = ScanResult(
            total_scanned=self.stats.total_scanned,
            duplicate_groups_count=len(groups),
            total_duplicates=total_duplicates,
            space_reclaimable_bytes=space_reclaimable,
            space_reclaimable_gb=round(space_reclaimable / (1024**3), 2),
            groups=groups,
            errors=[],
        )

        logger.info(
            "dedup_scan_completed",
            total_scanned=result.total_scanned,
            duplicate_groups=result.duplicate_groups_count,
            total_duplicates=result.total_duplicates,
            space_reclaimable_gb=result.space_reclaimable_gb,
            elapsed_seconds=int(time.time() - self._start_time),
        )

        return result

    async def _scan_directory(
        self,
        directory: Path,
        already_scanned: set[str],
        timeout_seconds: int,
    ) -> None:
        """
        Scan a directory recursively.

        Args:
            directory: Directory to scan
            already_scanned: Set of already-scanned file paths (avoid re-scan)
            timeout_seconds: Abort if exceeded
        """
        try:
            for file_path in directory.rglob("*"):
                if self._cancelled:
                    return

                # Timeout check
                if time.time() - self._start_time > timeout_seconds:
                    logger.warning(
                        "dedup_scan_timeout",
                        timeout_hours=self.config.scan_timeout_hours,
                    )
                    return

                # Skip already scanned (resolve to canonical path for
                # case-insensitive Windows: Desktop/ == desktop/)
                resolved_key = str(file_path.resolve())
                if resolved_key in already_scanned:
                    continue

                # Skip directories
                if file_path.is_dir():
                    continue

                # Apply exclusions
                if not self._should_scan(file_path):
                    self.stats.total_skipped += 1
                    already_scanned.add(resolved_key)
                    continue

                # Process file
                try:
                    await self._process_file(file_path)
                    already_scanned.add(resolved_key)
                except PermissionError:
                    self.stats.total_errors += 1
                    already_scanned.add(resolved_key)
                    logger.debug(
                        "dedup_permission_denied",
                        file_path=str(file_path),
                    )
                except OSError as e:
                    self.stats.total_errors += 1
                    already_scanned.add(resolved_key)
                    logger.debug(
                        "dedup_os_error",
                        file_path=str(file_path),
                        error=str(e),
                    )

                # Yield control periodically
                if self.stats.total_scanned % 100 == 0:
                    await asyncio.sleep(0)

                    # Progress callback
                    if self.progress_callback:
                        self.stats.current_directory = str(directory)
                        self.stats.duplicate_groups = self._dup_groups_count
                        self.progress_callback(self.stats)

        except PermissionError:
            logger.debug(
                "dedup_directory_permission_denied",
                directory=str(directory),
            )

    def _should_scan(self, file_path: Path) -> bool:
        """
        Check if file should be scanned (exclusions).

        Args:
            file_path: File to check

        Returns:
            True if file should be scanned

        AC1: Exclusions intelligentes
        """
        # System paths (case-insensitive)
        path_str_lower = str(file_path).lower()
        for excl in self.config.excluded_folders:
            # Use path separator to avoid partial matches
            if "\\" + excl + "\\" in path_str_lower or path_str_lower.startswith(
                excl
            ):
                return False

        # Dev folders (check any part of path)
        for part in file_path.parts:
            if part in self.config.excluded_dev_folders:
                return False

        # System extensions
        if file_path.suffix.lower() in self.config.excluded_extensions:
            return False

        # System filenames
        if file_path.name.lower() in self.config.excluded_filenames:
            return False

        # Office temp files (~$*)
        if file_path.name.startswith("~$"):
            return False

        # Size filters (handle stat errors)
        try:
            file_size = file_path.stat().st_size
        except (OSError, PermissionError):
            return False

        if file_size < self.config.min_file_size:
            return False

        if file_size > self.config.max_file_size:
            return False

        # Skip symlinks
        if file_path.is_symlink():
            return False

        return True

    async def _process_file(self, file_path: Path) -> None:
        """
        Process single file: compute hash and group duplicates.

        Args:
            file_path: File to process

        AC2: SHA256 chunked hashing + grouping
        """
        path_str = str(file_path)

        # Get file size
        file_size = file_path.stat().st_size
        self.size_cache[path_str] = file_size

        # Compute SHA256 (run in thread to avoid blocking)
        sha256_hash = await asyncio.to_thread(
            self._hash_file, file_path
        )

        # Cache
        self.hash_cache[path_str] = sha256_hash

        # Group by hash
        if sha256_hash not in self._hash_groups:
            self._hash_groups[sha256_hash] = []
        self._hash_groups[sha256_hash].append(path_str)

        # Track duplicate groups incrementally (avoid O(n) recomputation)
        if len(self._hash_groups[sha256_hash]) == 2:
            self._dup_groups_count += 1

        # Stats
        self.stats.total_scanned += 1

    def _hash_file(self, file_path: Path) -> str:
        """
        Compute SHA256 hash (chunked for memory efficiency).

        Args:
            file_path: File to hash

        Returns:
            Hex digest string

        AC2: SHA256 chunks 65536 bytes
        """
        sha256 = hashlib.sha256()

        with open(file_path, "rb") as f:
            while chunk := f.read(self.config.chunk_size):
                sha256.update(chunk)

        return sha256.hexdigest()

    def _build_duplicate_groups(self) -> list[DedupGroup]:
        """
        Build duplicate groups from hash index.

        Only groups with 2+ files are duplicates.

        Returns:
            List of DedupGroup with FileEntry objects
        """
        groups = []
        group_id = 1

        for sha256_hash, path_strs in self._hash_groups.items():
            if len(path_strs) < 2:
                continue

            entries = []
            for path_str in path_strs:
                entries.append(
                    FileEntry(
                        file_path=Path(path_str),
                        sha256_hash=sha256_hash,
                        size_bytes=self.size_cache.get(path_str, 0),
                    )
                )

            groups.append(
                DedupGroup(
                    group_id=group_id,
                    sha256_hash=sha256_hash,
                    files=entries,
                )
            )
            group_id += 1

        return groups
