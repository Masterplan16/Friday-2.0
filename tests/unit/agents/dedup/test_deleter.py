"""
Unit tests for SafeDeleter (Story 3.8, AC6 + AC7).

Tests:
- Safety checks (exists, hash match, exclusions, keeper)
- send2trash integration (mocked)
- Permission denied handling
- Progress tracking
"""

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from agents.src.agents.dedup.deleter import DeletionResult, SafeDeleter
from agents.src.agents.dedup.models import DedupAction, DedupGroup, FileEntry


@pytest.fixture
def deleter():
    """Default deleter."""
    return SafeDeleter(excluded_folders={"windows", "$recycle.bin"})


def _make_hash(content: bytes) -> str:
    """Helper to compute SHA256."""
    return hashlib.sha256(content).hexdigest()


def _make_group(
    tmp_path: Path,
    keeper_name: str = "keeper.txt",
    delete_names: list[str] = None,
    content: bytes = b"duplicate content",
) -> DedupGroup:
    """Helper to create a duplicate group with real files."""
    if delete_names is None:
        delete_names = ["delete1.txt"]

    sha256 = _make_hash(content)

    keeper_path = tmp_path / keeper_name
    keeper_path.write_bytes(content)

    keeper = FileEntry(
        file_path=keeper_path,
        sha256_hash=sha256,
        size_bytes=len(content),
        action=DedupAction.keep,
    )

    to_delete = []
    for name in delete_names:
        delete_path = tmp_path / name
        delete_path.write_bytes(content)
        to_delete.append(
            FileEntry(
                file_path=delete_path,
                sha256_hash=sha256,
                size_bytes=len(content),
                action=DedupAction.delete,
            )
        )

    return DedupGroup(
        group_id=1,
        sha256_hash=sha256,
        files=[keeper] + to_delete,
        keeper=keeper,
        to_delete=to_delete,
    )


class TestSafetyChecks:
    """Test 4 safety checks."""

    def test_safety_check_file_exists(self, deleter, tmp_path):
        """Skip if file no longer exists."""
        group = _make_group(tmp_path)
        # Delete the file before safety check
        group.to_delete[0].file_path.unlink()

        safe, reason = deleter._safety_check(group.to_delete[0], group)
        assert safe is False
        assert "no longer exists" in reason

    def test_safety_check_hash_match(self, deleter, tmp_path):
        """Skip if hash changed (file modified since scan)."""
        group = _make_group(tmp_path)
        # Modify the file after scan
        group.to_delete[0].file_path.write_bytes(b"modified content")

        safe, reason = deleter._safety_check(group.to_delete[0], group)
        assert safe is False
        assert "Hash mismatch" in reason

    def test_safety_check_excluded_zone(self, tmp_path):
        """Skip if file in excluded zone."""
        deleter = SafeDeleter(excluded_folders={"protected_zone"})
        content = b"test content"
        sha256 = _make_hash(content)

        # Create file in excluded zone
        excluded_dir = tmp_path / "protected_zone" / "sub"
        excluded_dir.mkdir(parents=True)
        file_path = excluded_dir / "file.txt"
        file_path.write_bytes(content)

        entry = FileEntry(
            file_path=file_path,
            sha256_hash=sha256,
            size_bytes=len(content),
            action=DedupAction.delete,
        )

        keeper_path = tmp_path / "keeper.txt"
        keeper_path.write_bytes(content)
        keeper = FileEntry(
            file_path=keeper_path,
            sha256_hash=sha256,
            size_bytes=len(content),
            action=DedupAction.keep,
        )

        group = DedupGroup(
            group_id=1,
            sha256_hash=sha256,
            files=[keeper, entry],
            keeper=keeper,
            to_delete=[entry],
        )

        safe, reason = deleter._safety_check(entry, group)
        assert safe is False
        assert "excluded zone" in reason

    def test_safety_check_keeper_exists(self, deleter, tmp_path):
        """Skip if keeper no longer exists."""
        group = _make_group(tmp_path)
        # Delete the keeper
        group.keeper.file_path.unlink()

        safe, reason = deleter._safety_check(group.to_delete[0], group)
        assert safe is False
        assert "Keeper file no longer exists" in reason

    def test_safety_check_all_pass(self, deleter, tmp_path):
        """All checks pass -> safe to delete."""
        group = _make_group(tmp_path)

        safe, reason = deleter._safety_check(group.to_delete[0], group)
        assert safe is True
        assert reason == ""


class TestDeletion:
    """Test batch deletion."""

    @pytest.mark.asyncio
    @patch("send2trash.send2trash")
    async def test_send2trash_success(self, mock_s2t_fn, tmp_path):
        """Successful deletion via send2trash."""
        deleter = SafeDeleter(excluded_folders=set())
        group = _make_group(tmp_path)

        result = await deleter.delete_duplicates([group])

        assert result.deleted == 1
        assert result.skipped == 0
        assert result.errors == 0
        mock_s2t_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_send2trash_failure_permissions(self, tmp_path):
        """Permission denied -> skip with error."""
        deleter = SafeDeleter(excluded_folders=set())
        group = _make_group(tmp_path)

        with patch(
            "send2trash.send2trash",
            side_effect=PermissionError("Access denied"),
        ):
            result = await deleter.delete_duplicates([group])

        assert result.deleted == 0
        assert result.errors == 1

    @pytest.mark.asyncio
    async def test_deletion_with_skip(self, tmp_path):
        """File deleted between scan and deletion -> skipped."""
        deleter = SafeDeleter(excluded_folders=set())
        group = _make_group(tmp_path)
        # Remove file before deletion
        group.to_delete[0].file_path.unlink()

        result = await deleter.delete_duplicates([group])

        assert result.deleted == 0
        assert result.skipped == 1

    @pytest.mark.asyncio
    @patch("send2trash.send2trash")
    async def test_deletion_progress_callback(self, mock_s2t_fn, tmp_path):
        """Progress callback is called during deletion."""
        progress_calls = []

        deleter = SafeDeleter(
            excluded_folders=set(),
            progress_callback=lambda r: progress_calls.append(r.deleted),
        )
        group = _make_group(tmp_path, delete_names=["d1.txt", "d2.txt", "d3.txt"])

        await deleter.delete_duplicates([group])

        assert len(progress_calls) == 3  # Called for each file

    @pytest.mark.asyncio
    @patch("send2trash.send2trash")
    async def test_deletion_cancel(self, mock_s2t_fn, tmp_path):
        """Cancel stops deletion mid-way."""
        deleter = SafeDeleter(excluded_folders=set())
        group = _make_group(tmp_path, delete_names=["d1.txt", "d2.txt", "d3.txt"])

        # Cancel via progress callback after first deletion
        def cancel_after_first(result):
            if result.deleted >= 1:
                deleter.cancel()

        deleter.progress_callback = cancel_after_first
        result = await deleter.delete_duplicates([group])

        # Should have stopped before deleting all 3
        assert result.deleted < 3
