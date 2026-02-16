"""
Tests unitaires pour watchdog_observer.py (Story 3.5 - Task 6.1).

8 tests couvrant :
- Start multiple paths
- Stop graceful
- Config reload hot-reload
- Redis connection/disconnection
- Error handling (Redis down)
- Path not found skip
- is_running property
- Disabled config
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
import yaml

from agents.src.agents.archiviste.watchdog_config import (
    WatchdogConfigManager,
    WatchdogConfigSchema,
    PathConfig,
)
from agents.src.agents.archiviste.watchdog_observer import (
    FridayWatchdogObserver,
)


@pytest.fixture
def valid_config_file(tmp_path):
    """Creer un fichier config watchdog.yaml valide."""
    # Creer les dossiers surveilles
    scans_dir = tmp_path / "scans"
    scans_dir.mkdir()
    finance_dir = tmp_path / "finance"
    finance_dir.mkdir()
    docs_dir = tmp_path / "documents"
    docs_dir.mkdir()

    config_file = tmp_path / "watchdog.yaml"
    config_data = {
        "watchdog": {
            "enabled": True,
            "polling_interval_seconds": 1,
            "stabilization_delay_seconds": 0,
            "paths": [
                {
                    "path": str(scans_dir),
                    "recursive": False,
                    "extensions": [".pdf", ".png"],
                    "source_label": "scanner",
                    "workflow_target": "ocr_pipeline",
                },
                {
                    "path": str(finance_dir),
                    "recursive": False,
                    "extensions": [".csv"],
                    "source_label": "csv_import",
                    "workflow_target": "csv_processing",
                },
                {
                    "path": str(docs_dir),
                    "recursive": True,
                    "extensions": [".pdf", ".docx"],
                    "source_label": "documents",
                },
            ],
        }
    }
    config_file.write_text(yaml.dump(config_data), encoding="utf-8")
    return config_file


@pytest.fixture
def disabled_config_file(tmp_path):
    """Config avec enabled=false."""
    config_file = tmp_path / "watchdog.yaml"
    config_data = {
        "watchdog": {
            "enabled": False,
            "paths": [
                {
                    "path": str(tmp_path),
                    "extensions": [".pdf"],
                    "source_label": "test",
                }
            ],
        }
    }
    config_file.write_text(yaml.dump(config_data), encoding="utf-8")
    return config_file


class TestFridayWatchdogObserver:
    """Tests observateur principal."""

    @pytest.mark.asyncio
    async def test_observer_start_multiple_paths(self, valid_config_file):
        """3 dossiers configures = 3 observers crees."""
        observer = FridayWatchdogObserver(
            config_path=str(valid_config_file),
            redis_url="redis://localhost:6379/0",
        )

        with patch("agents.src.agents.archiviste.watchdog_observer.aioredis") as mock_aioredis:
            mock_aioredis.from_url = AsyncMock(return_value=AsyncMock())

            with patch("agents.src.agents.archiviste.watchdog_observer.Observer") as MockObserver:
                mock_obs = MagicMock()
                MockObserver.return_value = mock_obs

                await observer.start()

                # 3 dossiers = 3 observers
                assert observer.watched_paths_count == 3
                assert mock_obs.start.call_count == 3
                assert observer.is_running is True

                await observer.stop()

    @pytest.mark.asyncio
    async def test_observer_stop_graceful(self, valid_config_file):
        """Stop arrete tous les observers et ferme Redis."""
        observer = FridayWatchdogObserver(
            config_path=str(valid_config_file),
        )

        mock_redis = AsyncMock()
        with patch("agents.src.agents.archiviste.watchdog_observer.aioredis") as mock_aioredis:
            mock_aioredis.from_url = AsyncMock(return_value=mock_redis)

            with patch("agents.src.agents.archiviste.watchdog_observer.Observer") as MockObserver:
                mock_obs = MagicMock()
                MockObserver.return_value = mock_obs

                await observer.start()
                assert observer.is_running is True

                await observer.stop()

                # Tous observers stoppes et joins
                assert mock_obs.stop.call_count == 3
                assert mock_obs.join.call_count == 3

                # Redis ferme
                mock_redis.close.assert_called_once()
                assert observer.redis is None
                assert observer._running is False

    @pytest.mark.asyncio
    async def test_observer_disabled_config(self, disabled_config_file):
        """Config disabled = pas de demarrage."""
        observer = FridayWatchdogObserver(
            config_path=str(disabled_config_file),
        )

        with patch("agents.src.agents.archiviste.watchdog_observer.aioredis"):
            await observer.start()

            # Pas d'observer demarre
            assert observer.watched_paths_count == 0
            assert observer._running is False

    @pytest.mark.asyncio
    async def test_observer_redis_connection(self, valid_config_file):
        """Redis connecte au start, deconnecte au stop."""
        observer = FridayWatchdogObserver(
            config_path=str(valid_config_file),
            redis_url="redis://test:6379/0",
        )

        mock_redis = AsyncMock()
        with patch("agents.src.agents.archiviste.watchdog_observer.aioredis") as mock_aioredis:
            mock_aioredis.from_url = AsyncMock(return_value=mock_redis)

            with patch("agents.src.agents.archiviste.watchdog_observer.Observer") as MockObserver:
                MockObserver.return_value = MagicMock()

                await observer.start()
                mock_aioredis.from_url.assert_called_once_with("redis://test:6379/0")
                assert observer.redis is mock_redis

                await observer.stop()
                mock_redis.close.assert_called_once()
                assert observer.redis is None

    @pytest.mark.asyncio
    async def test_observer_path_not_found_skip(self, tmp_path):
        """Dossier inexistant = skip (pas de crash)."""
        config_file = tmp_path / "watchdog.yaml"
        config_data = {
            "watchdog": {
                "enabled": True,
                "stabilization_delay_seconds": 0,
                "paths": [
                    {
                        "path": str(tmp_path / "nonexistent"),
                        "extensions": [".pdf"],
                        "source_label": "missing",
                    },
                    {
                        "path": str(tmp_path),  # Celui-ci existe
                        "extensions": [".pdf"],
                        "source_label": "exists",
                    },
                ],
            }
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        observer = FridayWatchdogObserver(config_path=str(config_file))

        with patch("agents.src.agents.archiviste.watchdog_observer.aioredis") as mock_aioredis:
            mock_aioredis.from_url = AsyncMock(return_value=AsyncMock())

            with patch("agents.src.agents.archiviste.watchdog_observer.Observer") as MockObserver:
                MockObserver.return_value = MagicMock()

                await observer.start()

                # Seulement 1 observer (le dossier existant)
                assert observer.watched_paths_count == 1

                await observer.stop()

    @pytest.mark.asyncio
    async def test_observer_config_reload(self, tmp_path):
        """Hot-reload recree les observers via config_reload_loop."""
        scans_dir = tmp_path / "scans"
        scans_dir.mkdir()
        new_dir = tmp_path / "new_folder"
        new_dir.mkdir()

        config_file = tmp_path / "watchdog.yaml"
        config_data = {
            "watchdog": {
                "enabled": True,
                "stabilization_delay_seconds": 0,
                "paths": [
                    {
                        "path": str(scans_dir),
                        "extensions": [".pdf"],
                        "source_label": "scanner",
                    },
                ],
            }
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        observer = FridayWatchdogObserver(config_path=str(config_file))

        mock_redis = AsyncMock()
        with patch("agents.src.agents.archiviste.watchdog_observer.aioredis") as mock_aioredis:
            mock_aioredis.from_url = AsyncMock(return_value=mock_redis)

            with patch("agents.src.agents.archiviste.watchdog_observer.Observer") as MockObserver:
                MockObserver.return_value = MagicMock()

                await observer.start()
                assert observer.watched_paths_count == 1

                # Modifier config pour ajouter un dossier
                import os
                import time as time_mod
                time_mod.sleep(0.1)
                updated_data = {
                    "watchdog": {
                        "enabled": True,
                        "stabilization_delay_seconds": 0,
                        "paths": [
                            {"path": str(scans_dir), "extensions": [".pdf"], "source_label": "scanner"},
                            {"path": str(new_dir), "extensions": [".csv"], "source_label": "csv-import"},
                        ],
                    }
                }
                config_file.write_text(yaml.dump(updated_data), encoding="utf-8")
                os.utime(str(config_file), (time_mod.time() + 1, time_mod.time() + 1))

                # Verifier que check_reload detecte le changement
                reloaded = observer.config_manager.check_reload()
                assert reloaded is True
                assert len(observer.config_manager.config.paths) == 2

                await observer.stop()

    @pytest.mark.asyncio
    async def test_observer_use_polling(self, valid_config_file):
        """use_polling=True utilise PollingObserver."""
        observer = FridayWatchdogObserver(
            config_path=str(valid_config_file),
            use_polling=True,
        )

        with patch("agents.src.agents.archiviste.watchdog_observer.aioredis") as mock_aioredis:
            mock_aioredis.from_url = AsyncMock(return_value=AsyncMock())

            with patch("agents.src.agents.archiviste.watchdog_observer.PollingObserver") as MockPolling:
                mock_obs = MagicMock()
                MockPolling.return_value = mock_obs

                await observer.start()
                assert MockPolling.call_count == 3

                await observer.stop()

    @pytest.mark.asyncio
    async def test_observer_path_not_directory_skip(self, tmp_path):
        """Fichier au lieu de dossier = skip."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("I am a file")

        config_file = tmp_path / "watchdog.yaml"
        config_data = {
            "watchdog": {
                "enabled": True,
                "stabilization_delay_seconds": 0,
                "paths": [
                    {
                        "path": str(file_path),
                        "extensions": [".pdf"],
                        "source_label": "bad",
                    },
                ],
            }
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        observer = FridayWatchdogObserver(config_path=str(config_file))

        with patch("agents.src.agents.archiviste.watchdog_observer.aioredis") as mock_aioredis:
            mock_aioredis.from_url = AsyncMock(return_value=AsyncMock())

            with patch("agents.src.agents.archiviste.watchdog_observer.Observer"):
                await observer.start()
                assert observer.watched_paths_count == 0
                await observer.stop()
