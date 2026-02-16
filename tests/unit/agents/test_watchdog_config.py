"""
Tests unitaires pour watchdog_config.py (Story 3.5 - Task 6.3).

16 tests couvrant :
- PathConfig : valid, extensions lowercased, extension sans point, path vide, extensions vides, source_label invalide
- WatchdogConfigSchema : load valid, missing path, polling range, defaults
- WatchdogConfigManager : load file, not found, missing root key, hot-reload, callback, get_paths
"""

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from agents.src.agents.archiviste.watchdog_config import (
    PathConfig,
    WatchdogConfigManager,
    WatchdogConfigSchema,
)

# ---------------------------------------------------------------------------
# PathConfig Model Tests
# ---------------------------------------------------------------------------


class TestPathConfig:
    """Tests validation Pydantic PathConfig."""

    def test_valid_path_config(self):
        """PathConfig valide accepte."""
        config = PathConfig(
            path="C:\\Users\\test\\Transit\\Scans",
            recursive=False,
            extensions=[".pdf", ".png"],
            source_label="scanner",
        )
        assert config.path == "C:\\Users\\test\\Transit\\Scans"
        assert config.extensions == [".pdf", ".png"]
        assert config.source_label == "scanner"
        assert config.workflow_target is None

    def test_extensions_lowercased(self):
        """Extensions normalisees en minuscules."""
        config = PathConfig(
            path="/tmp/test",
            extensions=[".PDF", ".PNG", ".Jpg"],
            source_label="test",
        )
        assert config.extensions == [".pdf", ".png", ".jpg"]

    def test_extension_without_dot_raises(self):
        """Extension sans point leve ValidationError."""
        with pytest.raises(ValueError, match="must start with '.'"):
            PathConfig(
                path="/tmp/test",
                extensions=["pdf", ".png"],
                source_label="test",
            )

    def test_empty_path_raises(self):
        """Chemin vide leve ValidationError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            PathConfig(
                path="",
                extensions=[".pdf"],
                source_label="test",
            )

    def test_empty_extensions_list_raises(self):
        """Liste extensions vide leve ValidationError."""
        with pytest.raises(ValueError):
            PathConfig(
                path="/tmp/test",
                extensions=[],
                source_label="test",
            )

    def test_source_label_invalid_chars_raises(self):
        """source_label avec caracteres speciaux leve ValidationError."""
        with pytest.raises(ValueError, match="must only contain"):
            PathConfig(
                path="/tmp/test",
                extensions=[".pdf"],
                source_label="bad label!",
            )

    def test_source_label_valid_chars(self):
        """source_label avec [a-zA-Z0-9_-] accepte."""
        config = PathConfig(
            path="/tmp/test",
            extensions=[".pdf"],
            source_label="scanner_physique-01",
        )
        assert config.source_label == "scanner_physique-01"


# ---------------------------------------------------------------------------
# WatchdogConfigSchema Tests
# ---------------------------------------------------------------------------


class TestWatchdogConfigSchema:
    """Tests validation schema complet."""

    def test_config_load_valid_yaml(self):
        """YAML valide charge sans erreur."""
        config = WatchdogConfigSchema(
            enabled=True,
            polling_interval_seconds=1,
            paths=[
                PathConfig(
                    path="/tmp/scans",
                    extensions=[".pdf"],
                    source_label="scanner",
                )
            ],
        )
        assert config.enabled is True
        assert config.polling_interval_seconds == 1
        assert len(config.paths) == 1

    def test_config_validation_missing_path(self):
        """Schema sans paths leve ValidationError."""
        with pytest.raises(ValueError):
            WatchdogConfigSchema(
                enabled=True,
                paths=[],
            )

    def test_polling_interval_range(self):
        """Intervalle polling valide entre 1 et 10."""
        with pytest.raises(ValueError):
            WatchdogConfigSchema(
                polling_interval_seconds=0,
                paths=[
                    PathConfig(
                        path="/tmp/test",
                        extensions=[".pdf"],
                        source_label="test",
                    )
                ],
            )

    def test_default_values(self):
        """Valeurs par defaut correctes."""
        config = WatchdogConfigSchema(
            paths=[
                PathConfig(
                    path="/tmp/test",
                    extensions=[".pdf"],
                    source_label="test",
                )
            ],
        )
        assert config.enabled is True
        assert config.polling_interval_seconds == 1
        assert config.stabilization_delay_seconds == 1.0


# ---------------------------------------------------------------------------
# WatchdogConfigManager Tests
# ---------------------------------------------------------------------------


class TestWatchdogConfigManager:
    """Tests gestionnaire configuration."""

    def test_load_valid_config_file(self, tmp_path):
        """Charge un fichier YAML valide."""
        config_file = tmp_path / "watchdog.yaml"
        config_data = {
            "watchdog": {
                "enabled": True,
                "polling_interval_seconds": 2,
                "paths": [
                    {
                        "path": str(tmp_path / "scans"),
                        "recursive": False,
                        "extensions": [".pdf", ".png"],
                        "source_label": "scanner",
                    }
                ],
            }
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        manager = WatchdogConfigManager(str(config_file))
        assert manager.config.enabled is True
        assert manager.config.polling_interval_seconds == 2
        assert len(manager.config.paths) == 1

    def test_config_file_not_found_raises(self):
        """Fichier config inexistant leve FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            WatchdogConfigManager("/nonexistent/watchdog.yaml")

    def test_config_missing_root_key_raises(self, tmp_path):
        """YAML sans cle 'watchdog' leve ValueError."""
        config_file = tmp_path / "watchdog.yaml"
        config_file.write_text("paths: []", encoding="utf-8")

        with pytest.raises(ValueError, match="missing 'watchdog' root key"):
            WatchdogConfigManager(str(config_file))

    def test_config_hot_reload_detection(self, tmp_path):
        """Modification YAML detectee par check_reload."""
        config_file = tmp_path / "watchdog.yaml"
        initial_data = {
            "watchdog": {
                "paths": [
                    {
                        "path": str(tmp_path / "scans"),
                        "extensions": [".pdf"],
                        "source_label": "scanner",
                    }
                ],
            }
        }
        config_file.write_text(yaml.dump(initial_data), encoding="utf-8")

        manager = WatchdogConfigManager(str(config_file))
        assert len(manager.config.paths) == 1

        # Pas de reload si pas modifie
        assert manager.check_reload() is False

        # Modifier le fichier (forcer mtime different)
        time.sleep(0.1)
        updated_data = {
            "watchdog": {
                "paths": [
                    {
                        "path": str(tmp_path / "scans"),
                        "extensions": [".pdf"],
                        "source_label": "scanner",
                    },
                    {
                        "path": str(tmp_path / "finance"),
                        "extensions": [".csv"],
                        "source_label": "csv_import",
                    },
                ],
            }
        }
        config_file.write_text(yaml.dump(updated_data), encoding="utf-8")

        # Force mtime update
        os.utime(str(config_file), (time.time() + 1, time.time() + 1))

        assert manager.check_reload() is True
        assert len(manager.config.paths) == 2

    def test_config_reload_callback_called(self, tmp_path):
        """Callback appele lors du hot-reload."""
        config_file = tmp_path / "watchdog.yaml"
        data = {
            "watchdog": {
                "paths": [
                    {
                        "path": str(tmp_path / "scans"),
                        "extensions": [".pdf"],
                        "source_label": "scanner",
                    }
                ],
            }
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")

        manager = WatchdogConfigManager(str(config_file))
        callback = MagicMock()
        manager.on_reload(callback)

        # Modifier et recharger
        time.sleep(0.1)
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        os.utime(str(config_file), (time.time() + 1, time.time() + 1))

        manager.check_reload()
        callback.assert_called_once()

    def test_get_paths_returns_dicts(self, tmp_path):
        """get_paths() retourne des dicts serialisables."""
        config_file = tmp_path / "watchdog.yaml"
        data = {
            "watchdog": {
                "paths": [
                    {
                        "path": str(tmp_path / "scans"),
                        "extensions": [".pdf"],
                        "source_label": "scanner",
                    }
                ],
            }
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")

        manager = WatchdogConfigManager(str(config_file))
        paths = manager.get_paths()
        assert isinstance(paths, list)
        assert isinstance(paths[0], dict)
        assert paths[0]["source_label"] == "scanner"
