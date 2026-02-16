"""
Tests unitaires pour watchdog_handler.py (Story 3.5 - Task 6.2).

15 tests couvrant :
- Filtrage extensions (accepted/rejected)
- Publication Redis event + file size metadata
- Ignore directories
- Retry backoff (success + exhausted)
- Path traversal blocked + similar prefix
- File disappeared, event loop not running
- on_moved event
- Stabilisation (stable + deleted)
- Move to error dir (AC5) + pipeline error publish
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from agents.src.agents.archiviste.watchdog_handler import (
    DOCUMENT_RECEIVED_STREAM,
    MAX_RETRIES,
    FridayWatchdogHandler,
)


@pytest.fixture
def mock_redis():
    """Redis mock avec xadd async."""
    redis = AsyncMock()
    redis.xadd = AsyncMock(return_value="1234567890-0")
    return redis


@pytest.fixture
def mock_loop():
    """Event loop mock."""
    loop = MagicMock()
    loop.is_running.return_value = True
    return loop


@pytest.fixture
def handler(mock_redis, mock_loop, tmp_path):
    """Handler configure pour tests."""
    return FridayWatchdogHandler(
        redis=mock_redis,
        loop=mock_loop,
        extensions=[".pdf", ".png", ".csv"],
        source_label="test_source",
        watched_root=str(tmp_path),
        workflow_target="test_workflow",
        stabilization_delay=0,  # Pas d'attente en tests
    )


class TestFridayWatchdogHandler:
    """Tests handler evenements filesystem."""

    def test_handler_filter_extensions_accepted(self, handler, tmp_path, mock_loop):
        """Extension autorisee (.pdf) declenche traitement."""
        test_file = tmp_path / "scan.pdf"
        test_file.write_text("test content")

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(test_file)

        with patch("asyncio.run_coroutine_threadsafe") as mock_dispatch:
            handler.on_created(event)
            mock_dispatch.assert_called_once()

    def test_handler_filter_extensions_rejected(self, handler, tmp_path):
        """Extension non-autorisee (.txt) ignoree."""
        test_file = tmp_path / "readme.txt"
        test_file.write_text("test content")

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(test_file)

        with patch("asyncio.run_coroutine_threadsafe") as mock_dispatch:
            handler.on_created(event)
            mock_dispatch.assert_not_called()

    def test_handler_ignore_directories(self, handler):
        """Evenement dossier ignore."""
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/tmp/test_dir"

        with patch("asyncio.run_coroutine_threadsafe") as mock_dispatch:
            handler.on_created(event)
            mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_publish_redis_event(self, mock_redis, tmp_path):
        """Event data structure correcte dans Redis Streams."""
        test_file = tmp_path / "invoice.pdf"
        test_file.write_bytes(b"PDF content here " * 100)

        loop = asyncio.get_running_loop()
        handler = FridayWatchdogHandler(
            redis=mock_redis,
            loop=loop,
            extensions=[".pdf"],
            source_label="scanner_physique",
            watched_root=str(tmp_path),
            workflow_target="ocr_pipeline",
            stabilization_delay=0,
        )

        await handler._publish_with_retry(test_file)

        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args

        # Verifier stream name
        assert call_args[0][0] == DOCUMENT_RECEIVED_STREAM

        # Verifier event data (dict plat)
        event_data = call_args[0][1]
        assert event_data["filename"] == "invoice.pdf"
        assert event_data["extension"] == ".pdf"
        assert event_data["source"] == "scanner_physique"
        assert event_data["workflow_target"] == "ocr_pipeline"
        assert "detected_at" in event_data
        assert int(event_data["size_bytes"]) > 0

        # Verifier maxlen
        assert call_args[1]["maxlen"] == 10000

    @pytest.mark.asyncio
    async def test_handler_file_size_metadata(self, mock_redis, tmp_path):
        """file_size_bytes correctement inclus dans event."""
        test_file = tmp_path / "scan.png"
        content = b"x" * 4096
        test_file.write_bytes(content)

        loop = asyncio.get_running_loop()
        handler = FridayWatchdogHandler(
            redis=mock_redis,
            loop=loop,
            extensions=[".png"],
            source_label="test",
            watched_root=str(tmp_path),
            stabilization_delay=0,
        )

        await handler._publish_with_retry(test_file)

        event_data = mock_redis.xadd.call_args[0][1]
        assert event_data["size_bytes"] == "4096"

    @pytest.mark.asyncio
    async def test_handler_retry_on_redis_failure(self, tmp_path):
        """3x retry backoff sur erreur Redis."""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(
            side_effect=[
                ConnectionError("Redis down"),
                ConnectionError("Redis down"),
                "1234567890-0",  # Succes 3eme tentative
            ]
        )

        test_file = tmp_path / "doc.pdf"
        test_file.write_bytes(b"content")

        loop = asyncio.get_running_loop()
        handler = FridayWatchdogHandler(
            redis=mock_redis,
            loop=loop,
            extensions=[".pdf"],
            source_label="test",
            watched_root=str(tmp_path),
            stabilization_delay=0,
        )

        # Patcher asyncio.sleep pour accelerer le test
        with patch(
            "agents.src.agents.archiviste.watchdog_handler.asyncio.sleep", new_callable=AsyncMock
        ):
            await handler._publish_with_retry(test_file)

        assert mock_redis.xadd.call_count == 3

    @pytest.mark.asyncio
    async def test_handler_retry_exhausted_raises(self, tmp_path):
        """Toutes tentatives echouees leve exception."""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(side_effect=ConnectionError("Redis permanently down"))

        test_file = tmp_path / "doc.pdf"
        test_file.write_bytes(b"content")

        loop = asyncio.get_running_loop()
        handler = FridayWatchdogHandler(
            redis=mock_redis,
            loop=loop,
            extensions=[".pdf"],
            source_label="test",
            watched_root=str(tmp_path),
            stabilization_delay=0,
        )

        with patch(
            "agents.src.agents.archiviste.watchdog_handler.asyncio.sleep", new_callable=AsyncMock
        ):
            with pytest.raises(ConnectionError, match="permanently down"):
                await handler._publish_with_retry(test_file)

        assert mock_redis.xadd.call_count == MAX_RETRIES

    def test_handler_path_traversal_blocked(self, handler, tmp_path):
        """Path traversal bloque (../malicious)."""
        # Creer fichier en dehors du dossier surveille
        malicious_path = tmp_path.parent / "malicious.pdf"

        with patch("asyncio.run_coroutine_threadsafe") as mock_dispatch:
            handler._process_event(str(malicious_path))
            mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_file_disappeared(self, mock_redis, tmp_path):
        """Fichier disparu pendant traitement = pas d'event Redis."""
        nonexistent = tmp_path / "vanished.pdf"
        # Ne PAS creer le fichier

        loop = asyncio.get_running_loop()
        handler = FridayWatchdogHandler(
            redis=mock_redis,
            loop=loop,
            extensions=[".pdf"],
            source_label="test",
            watched_root=str(tmp_path),
            stabilization_delay=0,
        )

        await handler._publish_with_retry(nonexistent)
        mock_redis.xadd.assert_not_called()

    def test_handler_event_loop_not_running(self, mock_redis, tmp_path):
        """Event loop pas running = log warning, pas de dispatch."""
        loop = MagicMock()
        loop.is_running.return_value = False

        handler = FridayWatchdogHandler(
            redis=mock_redis,
            loop=loop,
            extensions=[".pdf"],
            source_label="test",
            watched_root=str(tmp_path),
            stabilization_delay=0,
        )

        test_file = tmp_path / "test.pdf"
        test_file.write_text("content")

        with patch("asyncio.run_coroutine_threadsafe") as mock_dispatch:
            handler._process_event(str(test_file))
            mock_dispatch.assert_not_called()

    def test_handler_on_moved_event(self, handler, tmp_path, mock_loop):
        """on_moved traite le fichier destination (extension acceptee)."""
        test_file = tmp_path / "moved.pdf"
        test_file.write_text("content")

        event = MagicMock()
        event.is_directory = False
        event.dest_path = str(test_file)

        with patch("asyncio.run_coroutine_threadsafe") as mock_dispatch:
            handler.on_moved(event)
            mock_dispatch.assert_called_once()

    def test_handler_on_moved_ignored_extension(self, handler, tmp_path, mock_loop):
        """on_moved ignore extension non-autorisee."""
        test_file = tmp_path / "moved.txt"
        test_file.write_text("content")

        event = MagicMock()
        event.is_directory = False
        event.dest_path = str(test_file)

        with patch("asyncio.run_coroutine_threadsafe") as mock_dispatch:
            handler.on_moved(event)
            mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_stabilization_wait(self, mock_redis, tmp_path):
        """Stabilisation detecte fichier stable."""
        test_file = tmp_path / "stable.pdf"
        test_file.write_bytes(b"stable content")

        loop = asyncio.get_running_loop()
        handler = FridayWatchdogHandler(
            redis=mock_redis,
            loop=loop,
            extensions=[".pdf"],
            source_label="test",
            watched_root=str(tmp_path),
            stabilization_delay=0.1,
        )

        result = await handler._wait_for_stabilization(test_file, max_wait=2.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_handler_stabilization_file_deleted(self, mock_redis, tmp_path):
        """Stabilisation retourne False si fichier supprime."""
        test_file = tmp_path / "deleted.pdf"
        # Fichier n'existe pas

        loop = asyncio.get_running_loop()
        handler = FridayWatchdogHandler(
            redis=mock_redis,
            loop=loop,
            extensions=[".pdf"],
            source_label="test",
            watched_root=str(tmp_path),
            stabilization_delay=0.1,
        )

        result = await handler._wait_for_stabilization(test_file, max_wait=0.5)
        assert result is False

    def test_handler_path_traversal_similar_prefix(self, mock_redis, tmp_path):
        """Path traversal bloque meme avec prefixe similaire (ex: Scans_evil)."""
        watched_dir = tmp_path / "Scans"
        watched_dir.mkdir()
        evil_dir = tmp_path / "Scans_evil"
        evil_dir.mkdir()
        evil_file = evil_dir / "malware.pdf"
        evil_file.write_text("evil")

        loop = MagicMock()
        loop.is_running.return_value = True

        handler = FridayWatchdogHandler(
            redis=mock_redis,
            loop=loop,
            extensions=[".pdf"],
            source_label="test",
            watched_root=str(watched_dir),
            stabilization_delay=0,
        )

        with patch("asyncio.run_coroutine_threadsafe") as mock_dispatch:
            handler._process_event(str(evil_file))
            mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_move_to_error_dir(self, mock_redis, tmp_path):
        """AC5: fichier deplace vers error_directory/{date}/ apres echec."""
        error_dir = tmp_path / "errors"
        test_file = tmp_path / "failed.pdf"
        test_file.write_bytes(b"content")

        loop = asyncio.get_running_loop()
        handler = FridayWatchdogHandler(
            redis=mock_redis,
            loop=loop,
            extensions=[".pdf"],
            source_label="test",
            watched_root=str(tmp_path),
            stabilization_delay=0,
            error_directory=str(error_dir),
        )

        handler._move_to_error_dir(test_file)

        # Fichier original disparu
        assert not test_file.exists()
        # Fichier dans error_dir/{date}/
        from datetime import date

        today = date.today().isoformat()
        moved = error_dir / today / "failed.pdf"
        assert moved.exists()

    @pytest.mark.asyncio
    async def test_handler_publish_pipeline_error(self, mock_redis, tmp_path):
        """AC5: pipeline.error publie dans Redis apres echec."""
        test_file = tmp_path / "failed.pdf"
        test_file.write_bytes(b"content")

        loop = asyncio.get_running_loop()
        handler = FridayWatchdogHandler(
            redis=mock_redis,
            loop=loop,
            extensions=[".pdf"],
            source_label="scanner_physique",
            watched_root=str(tmp_path),
            stabilization_delay=0,
        )

        error = ConnectionError("Redis down")
        await handler._publish_pipeline_error(test_file, error)

        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "pipeline.error"
        event_data = call_args[0][1]
        assert event_data["source"] == "watchdog"
        assert event_data["source_label"] == "scanner_physique"
        assert event_data["filename"] == "failed.pdf"
        assert "Redis down" in event_data["error"]
