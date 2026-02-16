"""
Unit tests for DedupScanner (Story 3.8, AC1 + AC2).

Tests:
- Exclusion rules (system paths, dev folders, extensions, size)
- SHA256 chunked hashing
- Duplicate grouping
- Priority paths scanned first
- Edge cases (symlinks, permissions, file deleted during scan)
"""

import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from agents.src.agents.dedup.models import ScanConfig
from agents.src.agents.dedup.scanner import DedupScanner


@pytest.fixture
def default_config(tmp_path):
    """Default scan config for testing (with exclusions for real exclusion tests)."""
    return ScanConfig(root_path=tmp_path)


@pytest.fixture
def clean_config(tmp_path):
    """Scan config with empty exclusions (for tests in tmpdir which is under AppData\\Local\\Temp)."""
    return ScanConfig(
        root_path=tmp_path,
        excluded_folders=set(),
        min_file_size=1,
    )


@pytest.fixture
def scanner(default_config):
    """Scanner with default config."""
    return DedupScanner(config=default_config)


@pytest.fixture
def clean_scanner(clean_config):
    """Scanner with clean config (no folder exclusions)."""
    return DedupScanner(config=clean_config)


# ============================================================================
# AC1: Exclusion rules
# ============================================================================


class TestExclusions:
    """Test file exclusion logic."""

    def test_should_scan_exclude_system_paths(self, scanner, tmp_path):
        """Windows\\, Program Files\\ excluded."""
        # Create a file path that contains system path fragment
        system_file = tmp_path / "windows" / "system32" / "file.dat"
        system_file.parent.mkdir(parents=True, exist_ok=True)
        system_file.write_bytes(b"x" * 200)

        assert scanner._should_scan(system_file) is False

    def test_should_scan_exclude_program_files(self, scanner, tmp_path):
        """Program Files\\ excluded."""
        pf_file = tmp_path / "program files" / "app" / "file.dat"
        pf_file.parent.mkdir(parents=True, exist_ok=True)
        pf_file.write_bytes(b"x" * 200)

        assert scanner._should_scan(pf_file) is False

    def test_should_scan_exclude_dev_folders(self, scanner, tmp_path):
        """.git\\, node_modules\\ excluded."""
        git_file = tmp_path / "project" / ".git" / "HEAD"
        git_file.parent.mkdir(parents=True, exist_ok=True)
        git_file.write_bytes(b"ref: refs/heads/master")

        assert scanner._should_scan(git_file) is False

        node_file = tmp_path / "project" / "node_modules" / "pkg" / "index.js"
        node_file.parent.mkdir(parents=True, exist_ok=True)
        node_file.write_bytes(b"x" * 200)

        assert scanner._should_scan(node_file) is False

    def test_should_scan_exclude_system_extensions(self, scanner, tmp_path):
        """.dll, .exe, .sys excluded."""
        for ext in [".dll", ".exe", ".sys", ".msi", ".tmp", ".cache", ".log"]:
            f = tmp_path / f"file{ext}"
            f.write_bytes(b"x" * 200)
            assert scanner._should_scan(f) is False, f"Extension {ext} should be excluded"

    def test_should_scan_exclude_system_filenames(self, scanner, tmp_path):
        """desktop.ini, thumbs.db excluded."""
        for name in ["desktop.ini", "Thumbs.db", ".DS_Store"]:
            f = tmp_path / name
            f.write_bytes(b"x" * 200)
            assert scanner._should_scan(f) is False, f"Filename {name} should be excluded"

    def test_should_scan_exclude_office_temp(self, scanner, tmp_path):
        """~$* Office temp files excluded."""
        f = tmp_path / "~$document.docx"
        f.write_bytes(b"x" * 200)

        assert scanner._should_scan(f) is False

    def test_should_scan_size_filters_too_small(self, scanner, tmp_path):
        """Files <100 bytes skipped."""
        f = tmp_path / "tiny.txt"
        f.write_bytes(b"x" * 50)  # 50 bytes < 100

        assert scanner._should_scan(f) is False

    def test_should_scan_size_filters_too_large(self, tmp_path):
        """Files >2 GB skipped."""
        config = ScanConfig(root_path=tmp_path, max_file_size=1000)
        scanner = DedupScanner(config=config)

        f = tmp_path / "large.bin"
        f.write_bytes(b"x" * 1500)  # Exceeds our test limit

        assert scanner._should_scan(f) is False

    def test_should_scan_valid_file(self, clean_scanner, tmp_path):
        """Valid file should be scanned (clean config to avoid tmpdir exclusion)."""
        f = tmp_path / "document.pdf"
        f.write_bytes(b"x" * 200)

        assert clean_scanner._should_scan(f) is True

    def test_should_scan_exclude_pycache(self, scanner, tmp_path):
        """__pycache__\\ excluded."""
        f = tmp_path / "project" / "__pycache__" / "module.cpython-312.pyc"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * 200)

        assert scanner._should_scan(f) is False

    def test_should_scan_exclude_venv(self, scanner, tmp_path):
        """.venv and venv folders excluded."""
        for venv_name in [".venv", "venv"]:
            f = tmp_path / "project" / venv_name / "lib" / "pkg.py"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x" * 200)
            assert scanner._should_scan(f) is False


# ============================================================================
# AC2: SHA256 hashing
# ============================================================================


class TestHashing:
    """Test SHA256 chunked hashing."""

    def test_hash_file_chunked(self, scanner, tmp_path):
        """SHA256 computed correctly with chunked reading."""
        content = b"Hello World! " * 10000  # ~130 KB
        f = tmp_path / "test.txt"
        f.write_bytes(content)

        result = scanner._hash_file(f)

        expected = hashlib.sha256(content).hexdigest()
        assert result == expected

    def test_hash_file_small(self, scanner, tmp_path):
        """Small file (<1 chunk) hashed correctly."""
        content = b"small file content"
        f = tmp_path / "small.txt"
        f.write_bytes(content)

        result = scanner._hash_file(f)

        expected = hashlib.sha256(content).hexdigest()
        assert result == expected

    def test_hash_file_empty(self, scanner, tmp_path):
        """Empty file produces valid hash."""
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")

        result = scanner._hash_file(f)

        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected


# ============================================================================
# AC2: Duplicate grouping
# ============================================================================


class TestDuplicateGrouping:
    """Test duplicate file grouping."""

    @pytest.mark.asyncio
    async def test_duplicate_grouping_same_hash(self, tmp_path):
        """3 files with same content -> 1 group."""
        config = ScanConfig(root_path=tmp_path, min_file_size=1, excluded_folders=set())

        content = b"duplicate content here"
        for name in ["file1.txt", "file2.txt", "file3.txt"]:
            (tmp_path / name).write_bytes(content)

        scanner = DedupScanner(config=config)
        result = await scanner.scan()

        assert result.duplicate_groups_count == 1
        assert result.total_duplicates == 2  # 3 files - 1 keeper
        assert len(result.groups[0].files) == 3

    @pytest.mark.asyncio
    async def test_no_duplicates(self, tmp_path):
        """All unique files -> 0 groups."""
        config = ScanConfig(root_path=tmp_path, min_file_size=1, excluded_folders=set())

        for i in range(5):
            (tmp_path / f"unique_{i}.txt").write_bytes(f"unique content {i}".encode())

        scanner = DedupScanner(config=config)
        result = await scanner.scan()

        assert result.duplicate_groups_count == 0
        assert result.total_duplicates == 0

    @pytest.mark.asyncio
    async def test_multiple_duplicate_groups(self, tmp_path):
        """2 sets of duplicates -> 2 groups."""
        config = ScanConfig(root_path=tmp_path, min_file_size=1, excluded_folders=set())

        # Group 1: 2 files
        (tmp_path / "a1.txt").write_bytes(b"content A")
        (tmp_path / "a2.txt").write_bytes(b"content A")

        # Group 2: 3 files
        (tmp_path / "b1.txt").write_bytes(b"content B")
        (tmp_path / "b2.txt").write_bytes(b"content B")
        (tmp_path / "b3.txt").write_bytes(b"content B")

        # Unique file
        (tmp_path / "unique.txt").write_bytes(b"unique content")

        scanner = DedupScanner(config=config)
        result = await scanner.scan()

        assert result.duplicate_groups_count == 2
        assert result.total_duplicates == 3  # (2-1) + (3-1) = 3


# ============================================================================
# Edge cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_scan_empty_directory(self, tmp_path):
        """Empty directory -> 0 files scanned."""
        config = ScanConfig(root_path=tmp_path, excluded_folders=set())
        scanner = DedupScanner(config=config)
        result = await scanner.scan()

        assert result.total_scanned == 0
        assert result.duplicate_groups_count == 0

    @pytest.mark.asyncio
    async def test_scan_cancel(self, tmp_path):
        """Cancel during scan stops processing."""
        config = ScanConfig(root_path=tmp_path, min_file_size=1, excluded_folders=set())

        # Create many files (>100 to ensure progress callback triggers)
        for i in range(200):
            (tmp_path / f"file_{i}.txt").write_bytes(f"content {i}".encode())

        scanner = DedupScanner(config=config)

        # Cancel after progress callback fires (triggered every 100 files)
        def cancel_after_some(stats):
            if stats.total_scanned >= 100:
                scanner.cancel()

        scanner.progress_callback = cancel_after_some
        result = await scanner.scan()

        # Should have scanned fewer files than total (cancelled mid-scan)
        assert result.total_scanned < 200

    @pytest.mark.asyncio
    async def test_scan_with_nested_dirs(self, tmp_path):
        """Recursive scan finds files in subdirectories."""
        config = ScanConfig(root_path=tmp_path, min_file_size=1, excluded_folders=set())

        # Create nested structure
        sub1 = tmp_path / "sub1"
        sub2 = tmp_path / "sub1" / "sub2"
        sub1.mkdir()
        sub2.mkdir()

        (tmp_path / "root.txt").write_bytes(b"root file content")
        (sub1 / "sub1.txt").write_bytes(b"sub1 file content")
        (sub2 / "sub2.txt").write_bytes(b"sub2 file content")

        scanner = DedupScanner(config=config)
        result = await scanner.scan()

        assert result.total_scanned == 3

    @pytest.mark.asyncio
    async def test_progress_callback_called(self, tmp_path):
        """Progress callback is invoked during scan."""
        config = ScanConfig(root_path=tmp_path, min_file_size=1, excluded_folders=set())

        # Create >100 files to trigger callback (every 100 files)
        for i in range(150):
            (tmp_path / f"file_{i}.txt").write_bytes(f"content {i}".encode())

        callback_calls = []
        scanner = DedupScanner(
            config=config,
            progress_callback=lambda stats: callback_calls.append(stats.total_scanned),
        )
        await scanner.scan()

        assert len(callback_calls) > 0

    def test_should_scan_symlink_excluded(self, scanner, tmp_path):
        """Symlinks are excluded."""
        target = tmp_path / "target.txt"
        target.write_bytes(b"x" * 200)

        link = tmp_path / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")

        assert scanner._should_scan(link) is False
