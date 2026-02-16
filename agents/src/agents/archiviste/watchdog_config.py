"""
Gestionnaire configuration Watchdog avec hot-reload (Story 3.5 - Task 2).

Charge et valide config/watchdog.yaml.
Surveille modifications pour hot-reload sans redemarrage.
"""
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog
import yaml
from pydantic import BaseModel, Field, field_validator

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Models (Task 2.1)
# ---------------------------------------------------------------------------

class PathConfig(BaseModel):
    """Configuration d'un dossier surveille par Watchdog."""

    path: str = Field(..., description="Chemin absolu dossier surveille")
    recursive: bool = Field(default=False, description="Surveiller sous-dossiers")
    extensions: List[str] = Field(
        ...,
        min_length=1,
        description="Extensions autorisees (.pdf, .csv, etc.)"
    )
    source_label: str = Field(
        ...,
        min_length=1,
        description="Label source (scanner_physique, csv_bancaire, etc.)"
    )

    @field_validator("source_label")
    @classmethod
    def validate_source_label(cls, v: str) -> str:
        """Valider que le label source contient uniquement [a-zA-Z0-9_-]."""
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                f"source_label '{v}' must only contain [a-zA-Z0-9_-]"
            )
        return v
    workflow_target: Optional[str] = Field(
        None,
        description="n8n workflow ID cible"
    )

    @field_validator("extensions")
    @classmethod
    def validate_extensions(cls, v: List[str]) -> List[str]:
        """Valider que chaque extension commence par un point."""
        validated = []
        for ext in v:
            if not ext.startswith("."):
                raise ValueError(
                    f"Extension '{ext}' must start with '.'"
                )
            validated.append(ext.lower())
        return validated

    @field_validator("path")
    @classmethod
    def validate_path_not_empty(cls, v: str) -> str:
        """Valider que le chemin n'est pas vide."""
        if not v or not v.strip():
            raise ValueError("Path cannot be empty")
        return v


class WatchdogConfigSchema(BaseModel):
    """Schema complet de configuration Watchdog."""

    enabled: bool = Field(default=True, description="Activer watchdog global")
    polling_interval_seconds: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Intervalle polling (1-10s)"
    )
    stabilization_delay_seconds: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="Delai stabilisation fichier avant traitement"
    )
    error_directory: Optional[str] = Field(
        default=None,
        description="Dossier pour fichiers en erreur (sous-dossier date cree auto)"
    )
    paths: List[PathConfig] = Field(
        ...,
        min_length=1,
        description="Dossiers surveilles"
    )


# ---------------------------------------------------------------------------
# Config Manager (Task 2.2 - hot-reload)
# ---------------------------------------------------------------------------

class WatchdogConfigManager:
    """
    Gestionnaire configuration Watchdog avec hot-reload.

    Surveille watchdog.yaml pour modifications.
    Recharge automatiquement sans redemarrage.
    """

    def __init__(self, config_path: str = "config/watchdog.yaml"):
        self.config_path = Path(config_path).resolve()
        self._config: Optional[WatchdogConfigSchema] = None
        self._last_mtime: float = 0.0
        self._on_reload_callbacks: List[Callable] = []
        self._load()

    @property
    def config(self) -> WatchdogConfigSchema:
        """Retourne la configuration courante."""
        if self._config is None:
            self._load()
        return self._config

    def _load(self) -> None:
        """Charger et valider watchdog.yaml."""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Watchdog config not found: {self.config_path}"
            )

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if not raw or "watchdog" not in raw:
            raise ValueError(
                "Invalid watchdog config: missing 'watchdog' root key"
            )

        self._config = WatchdogConfigSchema(**raw["watchdog"])
        self._last_mtime = self.config_path.stat().st_mtime

        logger.info(
            "watchdog.config_loaded",
            config_path=str(self.config_path),
            paths_count=len(self._config.paths),
            enabled=self._config.enabled
        )

    def check_reload(self) -> bool:
        """
        Verifier si le fichier config a ete modifie et recharger si oui.

        Returns:
            True si config rechargee, False sinon.
        """
        try:
            current_mtime = self.config_path.stat().st_mtime
        except OSError:
            logger.warning(
                "watchdog.config_stat_failed",
                config_path=str(self.config_path)
            )
            return False

        if current_mtime <= self._last_mtime:
            return False

        try:
            old_paths_count = len(self._config.paths) if self._config else 0
            self._load()
            new_paths_count = len(self._config.paths)

            logger.info(
                "watchdog.config_reloaded",
                old_paths=old_paths_count,
                new_paths=new_paths_count
            )

            for callback in self._on_reload_callbacks:
                try:
                    callback(self._config)
                except Exception as e:
                    logger.error(
                        "watchdog.reload_callback_failed",
                        error=str(e)
                    )

            return True

        except Exception as e:
            logger.error(
                "watchdog.config_reload_failed",
                error=str(e)
            )
            return False

    def on_reload(self, callback: Callable) -> None:
        """Enregistrer un callback appele lors du rechargement."""
        self._on_reload_callbacks.append(callback)

    def get_paths(self) -> List[Dict[str, Any]]:
        """Retourne la liste des paths configurees sous forme de dicts."""
        return [p.model_dump() for p in self.config.paths]
