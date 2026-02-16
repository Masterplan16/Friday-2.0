"""
Unit tests for batch processor core.

Tests AC2 (Pipeline processing) and AC6 (Error handling).

Coverage:
- Recursive folder scan with filters
- SHA256 deduplication
- System files skip
- Pipeline processing
- Rate limiting
- Fail-safe error handling
- Pause/cancel support
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta


# ============================================================================
# Test scan_folder_with_filters (AC2)
# ============================================================================


def test_scan_folder_recursive(tmp_path):
    """
    Test scan récursif avec filtres

    AC2: scan récursif dossier
    """
    from agents.src.agents.archiviste.batch_processor import (
        BatchProcessor,
        BatchFilters,
    )

    # Create test files
    (tmp_path / "file1.pdf").write_text("test")
    (tmp_path / "file2.png").write_text("test")
    subfolder = tmp_path / "subfolder"
    subfolder.mkdir()
    (subfolder / "file3.jpg").write_text("test")

    # Create processor
    filters = BatchFilters(extensions=[".pdf", ".png", ".jpg"])
    processor = BatchProcessor(
        batch_id="test",
        folder_path=str(tmp_path),
        filters=filters,
        progress_tracker=None,
    )

    # Scan
    files = processor.scan_folder_with_filters()

    # Assert 3 files found
    assert len(files) == 3
    assert any("file1.pdf" in str(f) for f in files)
    assert any("file3.jpg" in str(f) for f in files)


def test_is_system_file_tmp():
    """
    Test détection fichier .tmp

    AC2: skip fichiers système
    """
    from agents.src.agents.archiviste.batch_shared import is_system_file

    assert is_system_file(Path("/tmp/test.tmp")) is True
    assert is_system_file(Path("/tmp/valid.pdf")) is False


def test_is_system_file_office_temp():
    """
    Test détection ~$*.docx

    AC2: skip fichiers Office temporaires
    """
    from agents.src.agents.archiviste.batch_shared import is_system_file

    assert is_system_file(Path("/tmp/~$document.docx")) is True
    assert is_system_file(Path("/tmp/document.docx")) is False


def test_is_system_file_desktop_ini():
    """
    Test détection desktop.ini

    AC2: skip fichiers système Windows
    """
    from agents.src.agents.archiviste.batch_shared import is_system_file

    assert is_system_file(Path("/tmp/desktop.ini")) is True
    assert is_system_file(Path("/tmp/.DS_Store")) is True
    assert is_system_file(Path("/tmp/thumbs.db")) is True


def test_is_system_file_git_folder():
    """
    Test détection .git/

    AC2: skip dossiers version control
    """
    from agents.src.agents.archiviste.batch_shared import is_system_file

    assert is_system_file(Path("/tmp/.git/config")) is True
    assert is_system_file(Path("/tmp/__pycache__/module.pyc")) is True


# ============================================================================
# Test matches_filters (AC5)
# ============================================================================


def test_matches_filters_extensions(tmp_path):
    """
    Test filtre extensions

    AC5: whitelist extensions
    """
    from agents.src.agents.archiviste.batch_processor import (
        BatchProcessor,
        BatchFilters,
    )

    # Create test files
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_text("test")
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("test")

    # Processor with filter
    filters = BatchFilters(extensions=[".pdf"])
    processor = BatchProcessor(
        batch_id="test",
        folder_path=str(tmp_path),
        filters=filters,
        progress_tracker=None,
    )

    # Test
    assert processor.matches_filters(pdf_file) is True
    assert processor.matches_filters(txt_file) is False


def test_matches_filters_date_after(tmp_path):
    """
    Test filtre date

    AC5: fichiers après date
    """
    from agents.src.agents.archiviste.batch_processor import (
        BatchProcessor,
        BatchFilters,
    )

    # Create old file
    old_file = tmp_path / "old.pdf"
    old_file.write_text("test")

    # Set old mtime
    old_time = (datetime.now() - timedelta(days=30)).timestamp()
    old_file.touch()
    import os

    os.utime(old_file, (old_time, old_time))

    # Create recent file
    recent_file = tmp_path / "recent.pdf"
    recent_file.write_text("test")

    # Processor with date filter
    filters = BatchFilters(date_after=datetime.now() - timedelta(days=7))
    processor = BatchProcessor(
        batch_id="test",
        folder_path=str(tmp_path),
        filters=filters,
        progress_tracker=None,
    )

    # Test
    assert processor.matches_filters(old_file) is False
    assert processor.matches_filters(recent_file) is True


def test_matches_filters_max_size(tmp_path):
    """
    Test filtre taille

    AC5: taille max
    """
    from agents.src.agents.archiviste.batch_processor import (
        BatchProcessor,
        BatchFilters,
    )

    # Create small file (1 KB)
    small_file = tmp_path / "small.pdf"
    small_file.write_bytes(b"x" * 1024)

    # Create large file (2 MB)
    large_file = tmp_path / "large.pdf"
    large_file.write_bytes(b"x" * (2 * 1024 * 1024))

    # Processor with size filter (1 MB max)
    filters = BatchFilters(max_size_mb=1)
    processor = BatchProcessor(
        batch_id="test",
        folder_path=str(tmp_path),
        filters=filters,
        progress_tracker=None,
    )

    # Test
    assert processor.matches_filters(small_file) is True
    assert processor.matches_filters(large_file) is False


# ============================================================================
# Test deduplicate_files (AC2)
# ============================================================================


@pytest.mark.asyncio
async def test_deduplicate_files_sha256():
    """
    Test déduplication SHA256

    AC2: skip fichiers déjà traités
    """
    from agents.src.agents.archiviste.batch_processor import (
        BatchProcessor,
        BatchFilters,
    )

    # Mock database
    mock_db = MagicMock()
    mock_db.fetchval = AsyncMock(side_effect=[True, False])  # First exists, second doesn't

    # Create temp files
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        file1 = Path(tmpdir) / "file1.pdf"
        file1.write_text("test1")
        file2 = Path(tmpdir) / "file2.pdf"
        file2.write_text("test2")

        # Processor
        filters = BatchFilters()
        processor = BatchProcessor(
            batch_id="test",
            folder_path=tmpdir,
            filters=filters,
            progress_tracker=None,
        )
        processor.db = mock_db

        # Deduplicate
        files = [file1, file2]
        deduped = await processor.deduplicate_files(files)

        # Assert only file2 kept (file1 already exists in DB)
        assert len(deduped) == 1
        assert deduped[0] == file2


# ============================================================================
# Test process_single_file (AC2)
# ============================================================================


@pytest.mark.asyncio
async def test_process_single_file_success():
    """
    Test traitement fichier réussi

    AC2: pipeline Archiviste complet
    """
    from agents.src.agents.archiviste.batch_processor import (
        BatchProcessor,
        BatchFilters,
    )

    # Mock dependencies
    mock_db = MagicMock()
    mock_db.fetchrow = AsyncMock(
        return_value={"status": "completed", "final_path": "/path", "category": "finance"}
    )
    mock_redis = MagicMock()

    with patch(
        "agents.src.agents.archiviste.batch_processor.upload_file_to_vps",
        new_callable=AsyncMock,
    ) as mock_upload:
        with patch(
            "agents.src.agents.archiviste.batch_processor.publish_document_received",
            new_callable=AsyncMock,
        ) as mock_publish:
            # Processor
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                test_file = Path(tmpdir) / "test.pdf"
                test_file.write_text("test")

                filters = BatchFilters()
                processor = BatchProcessor(
                    batch_id="test",
                    folder_path=tmpdir,
                    filters=filters,
                    progress_tracker=None,
                )
                processor.db = mock_db
                processor.redis = mock_redis

                # Process
                await processor.process_single_file(test_file)

                # Assert upload and publish called
                assert mock_upload.called
                assert mock_publish.called


@pytest.mark.asyncio
async def test_process_single_file_timeout():
    """
    Test timeout après 5 min

    AC6: timeout protection
    """
    from agents.src.agents.archiviste.batch_processor import (
        BatchProcessor,
        BatchFilters,
    )

    # Mock dependencies (never returns completed)
    mock_db = MagicMock()
    mock_db.fetchrow = AsyncMock(return_value=None)  # Never completes
    mock_redis = MagicMock()

    with patch(
        "agents.src.agents.archiviste.batch_processor.upload_file_to_vps",
        new_callable=AsyncMock,
    ):
        with patch(
            "agents.src.agents.archiviste.batch_processor.publish_document_received",
            new_callable=AsyncMock,
        ):
            # Processor with short timeout
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                test_file = Path(tmpdir) / "test.pdf"
                test_file.write_text("test")

                filters = BatchFilters()
                processor = BatchProcessor(
                    batch_id="test",
                    folder_path=tmpdir,
                    filters=filters,
                    progress_tracker=None,
                )
                processor.db = mock_db
                processor.redis = mock_redis

                # Override timeout for test
                processor.processing_timeout = 1  # 1 second

                # Process should timeout
                with pytest.raises(TimeoutError):
                    await processor.process_single_file(test_file)


# ============================================================================
# Test rate_limiting (AC2)
# ============================================================================


@pytest.mark.asyncio
async def test_rate_limiting_5_per_minute():
    """
    Test rate limiter activé

    AC2: 5 fichiers/min max
    """
    from agents.src.agents.archiviste.batch_processor import SimpleRateLimiter
    import time

    limiter = SimpleRateLimiter(max_requests=5, window_seconds=60)

    # Process 5 files (should be fast)
    start = time.time()
    for _ in range(5):
        await limiter.wait()
    elapsed = time.time() - start

    # Should be very fast (<1s)
    assert elapsed < 1

    # 6th file should wait
    start = time.time()
    await limiter.wait()
    elapsed = time.time() - start

    # Should have waited (~12s for next slot)
    assert elapsed >= 10  # Allow some slack


# ============================================================================
# Test fail_safe_continue_on_error (AC6)
# ============================================================================


@pytest.mark.asyncio
async def test_fail_safe_continue_on_error():
    """
    Test continue si 1 fichier échoue

    AC6: fail-safe processing
    """
    from agents.src.agents.archiviste.batch_processor import (
        BatchProcessor,
        BatchFilters,
    )

    # Mock progress tracker
    mock_progress = MagicMock()
    mock_progress.increment_failed = MagicMock()
    mock_progress.increment_success = MagicMock()
    mock_progress.update_telegram = AsyncMock()
    mock_progress.total_files = 0
    mock_progress.processed = 0
    mock_progress.failed = 0
    mock_progress.cancelled = False
    mock_progress.paused = False

    # Mock processor with failing file
    with patch(
        "agents.src.agents.archiviste.batch_processor.BatchProcessor.process_single_file"
    ) as mock_process:
        # First file fails, second succeeds
        mock_process.side_effect = [Exception("OCR failed"), None]

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "fail.pdf"
            file1.write_text("test")
            file2 = Path(tmpdir) / "success.pdf"
            file2.write_text("test")

            filters = BatchFilters()
            processor = BatchProcessor(
                batch_id="test",
                folder_path=tmpdir,
                filters=filters,
                progress_tracker=mock_progress,
            )

            # Mock other methods
            processor.scan_folder_with_filters = MagicMock(return_value=[file1, file2])
            processor.deduplicate_files = AsyncMock(return_value=[file1, file2])
            processor.rate_limiter = MagicMock()
            processor.rate_limiter.wait = AsyncMock()
            processor.move_to_errors = AsyncMock()
            processor.generate_final_report = AsyncMock()

            # Process batch
            await processor.process()

            # Assert both files attempted
            assert mock_process.call_count == 2
            # Assert progress tracked
            assert mock_progress.increment_failed.called
            assert mock_progress.increment_success.called


# ============================================================================
# Test compute_sha256 (AC2)
# ============================================================================


def test_compute_sha256(tmp_path):
    """
    Test SHA256 hash calculation

    AC2: déduplication via SHA256
    """
    from agents.src.agents.archiviste.batch_processor import compute_sha256

    # Create test file
    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"test content")

    # Compute hash
    hash1 = compute_sha256(test_file)

    # Create identical file
    test_file2 = tmp_path / "test2.pdf"
    test_file2.write_bytes(b"test content")

    hash2 = compute_sha256(test_file2)

    # Hashes should match
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 = 64 hex chars


def test_compute_sha256_different_files(tmp_path):
    """
    Test SHA256 différents fichiers

    AC2: fichiers différents -> hashes différents
    """
    from agents.src.agents.archiviste.batch_processor import compute_sha256

    # Create files with different content
    file1 = tmp_path / "file1.pdf"
    file1.write_bytes(b"content1")

    file2 = tmp_path / "file2.pdf"
    file2.write_bytes(b"content2")

    hash1 = compute_sha256(file1)
    hash2 = compute_sha256(file2)

    # Hashes should be different
    assert hash1 != hash2


# ============================================================================
# Test SHA256 cache (performance fix)
# ============================================================================


def test_sha256_cache(tmp_path):
    """
    Test SHA256 hash caching avoids double computation.

    Code review fix: SHA256 was computed twice per file.
    """
    from agents.src.agents.archiviste.batch_processor import (
        BatchProcessor,
        BatchFilters,
    )

    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"test content")

    processor = BatchProcessor(
        batch_id="test",
        folder_path=str(tmp_path),
        filters=BatchFilters(),
        progress_tracker=None,
    )

    # First call computes
    hash1 = processor._get_sha256(test_file)
    # Second call uses cache
    hash2 = processor._get_sha256(test_file)

    assert hash1 == hash2
    assert str(test_file) in processor._sha256_cache


# ============================================================================
# Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_file_deleted_during_processing(tmp_path):
    """
    Edge case: fichier supprimé pendant traitement

    AC6: error handling robuste
    """
    from agents.src.agents.archiviste.batch_processor import (
        BatchProcessor,
        BatchFilters,
    )

    # Create file
    test_file = tmp_path / "test.pdf"
    test_file.write_text("test")

    filters = BatchFilters()
    processor = BatchProcessor(
        batch_id="test",
        folder_path=str(tmp_path),
        filters=filters,
        progress_tracker=None,
    )

    # Delete file before processing
    test_file.unlink()

    # Should handle error gracefully
    with pytest.raises(FileNotFoundError):
        await processor.process_single_file(test_file)


def test_empty_folder(tmp_path):
    """
    Edge case: dossier vide

    AC2: retourne 0 fichiers
    """
    from agents.src.agents.archiviste.batch_processor import (
        BatchProcessor,
        BatchFilters,
    )

    filters = BatchFilters()
    processor = BatchProcessor(
        batch_id="test",
        folder_path=str(tmp_path),
        filters=filters,
        progress_tracker=None,
    )

    files = processor.scan_folder_with_filters()

    assert len(files) == 0
