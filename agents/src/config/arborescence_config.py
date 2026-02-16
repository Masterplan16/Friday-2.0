"""
Configuration de l'arborescence Friday pour classement documents.

Story 3.2 - Task 2.5 et 2.6
Charge et valide config/arborescence.yaml
"""
import os
from pathlib import Path
from typing import Dict, Any, Set
import yaml
from pydantic import BaseModel, Field, field_validator


class ArborescenceConfig(BaseModel):
    """
    Configuration de l'arborescence Friday.

    Attributes:
        root_path: Chemin racine archives sur PC
        transit_paths: Chemins zones transit (VPS + PC)
        categories: Structure hiérarchique complète
        validation: Règles de validation
        anti_contamination: Règles anti-contamination finance
    """

    root_path: str = Field(..., description="Chemin racine archives PC")
    transit_paths: Dict[str, str] = Field(..., description="Chemins transit VPS/PC")
    categories: Dict[str, Any] = Field(..., description="Structure hiérarchique")
    validation: Dict[str, Any] = Field(..., description="Règles validation")
    anti_contamination: Dict[str, Any] = Field(..., description="Règles anti-contamination")

    @field_validator("root_path")
    @classmethod
    def validate_root_path_not_empty(cls, v: str) -> str:
        """Valide que le chemin racine n'est pas vide."""
        if not v or not v.strip():
            raise ValueError("root_path cannot be empty")
        return v

    @field_validator("categories")
    @classmethod
    def validate_categories_structure(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Valide la structure des catégories."""
        required_categories = {"pro", "finance", "universite", "recherche", "perso"}
        actual_categories = set(v.keys())

        if actual_categories != required_categories:
            raise ValueError(
                f"Categories must be exactly: {required_categories}. "
                f"Got: {actual_categories}"
            )

        # Vérifier périmètres finance (CRITIQUE)
        finance = v.get("finance", {})
        finance_subcats = finance.get("subcategories", {})
        required_finance = {"selarl", "scm", "sci_ravas", "sci_malbosc", "personal"}
        actual_finance = set(finance_subcats.keys())

        if actual_finance != required_finance:
            raise ValueError(
                f"Finance subcategories must be exactly: {required_finance}. "
                f"Got: {actual_finance}"
            )

        return v

    @field_validator("validation")
    @classmethod
    def validate_validation_rules(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Valide et applique les règles de validation (Task 2.5)."""
        # max_depth doit être défini et raisonnable
        max_depth = v.get("max_depth")
        if max_depth is not None:
            if not isinstance(max_depth, int) or max_depth < 1 or max_depth > 10:
                raise ValueError(
                    f"max_depth must be an integer between 1 and 10, got: {max_depth}"
                )

        # forbidden_names doit être une liste
        forbidden_names = v.get("forbidden_names", [])
        if not isinstance(forbidden_names, list):
            raise ValueError("forbidden_names must be a list")

        # forbidden_chars doit être une liste
        forbidden_chars = v.get("forbidden_chars", [])
        if not isinstance(forbidden_chars, list):
            raise ValueError("forbidden_chars must be a list")

        return v

    def get_category_path(self, category: str, subcategory: str | None = None) -> str:
        """
        Retourne le chemin relatif pour une catégorie/subcategory.

        Args:
            category: Catégorie principale
            subcategory: Sous-catégorie (obligatoire pour finance)

        Returns:
            Chemin relatif (ex: "finance/selarl", "pro/administratif")

        Raises:
            KeyError: Si catégorie ou subcategory invalide
        """
        if category not in self.categories:
            raise KeyError(f"Unknown category: {category}")

        category_config = self.categories[category]

        if subcategory:
            subcats = category_config.get("subcategories", {})
            if subcategory not in subcats:
                raise KeyError(
                    f"Unknown subcategory '{subcategory}' in category '{category}'"
                )
            return subcats[subcategory]["path"].split("{")[0].rstrip("/")
        else:
            return category

    def validate_path_name(self, name: str) -> bool:
        """
        Valide qu'un nom de dossier/fichier respecte les règles (Task 2.5).

        Args:
            name: Nom à valider

        Returns:
            True si valide

        Raises:
            ValueError: Si nom interdit ou contient caractères interdits
        """
        forbidden_names = self.validation.get("forbidden_names", [])
        forbidden_chars = self.validation.get("forbidden_chars", [])

        # Vérifier noms réservés Windows
        name_upper = name.upper().split(".")[0]  # Sans extension
        if name_upper in forbidden_names:
            raise ValueError(
                f"Reserved name not allowed: '{name}'"
            )

        # Vérifier caractères interdits
        for char in forbidden_chars:
            if char in name:
                raise ValueError(
                    f"Forbidden character '{char}' in name: '{name}'"
                )

        return True

    def validate_path_depth(self, path: str) -> bool:
        """
        Valide que la profondeur d'un chemin ne dépasse pas max_depth (Task 2.5).

        Args:
            path: Chemin relatif à valider

        Returns:
            True si valide

        Raises:
            ValueError: Si profondeur > max_depth
        """
        max_depth = self.validation.get("max_depth", 6)
        parts = [p for p in path.replace("\\", "/").split("/") if p]

        if len(parts) > max_depth:
            raise ValueError(
                f"Path depth {len(parts)} exceeds max_depth {max_depth}: '{path}'"
            )

        return True

    def validate_finance_perimeter(self, subcategory: str) -> bool:
        """
        Valide qu'un périmètre finance est valide.

        Args:
            subcategory: Périmètre à valider

        Returns:
            True si valide

        Raises:
            ValueError: Si périmètre invalide
        """
        valid_perimeters = {"selarl", "scm", "sci_ravas", "sci_malbosc", "personal"}

        if subcategory not in valid_perimeters:
            raise ValueError(
                f"Invalid financial perimeter '{subcategory}'. "
                f"Must be one of: {valid_perimeters}"
            )

        return True


def load_arborescence_config(config_path: str | None = None) -> ArborescenceConfig:
    """
    Charge la configuration d'arborescence depuis YAML.

    Args:
        config_path: Chemin vers config YAML (défaut: config/arborescence.yaml)

    Returns:
        ArborescenceConfig validée

    Raises:
        FileNotFoundError: Si fichier config introuvable
        yaml.YAMLError: Si YAML invalide
        ValidationError: Si structure invalide
    """
    if config_path is None:
        # Default: repo root / config / arborescence.yaml
        repo_root = Path(__file__).parent.parent.parent.parent
        config_path = repo_root / "config" / "arborescence.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    return ArborescenceConfig(**config_data)


# Singleton instance (lazy loaded)
_arborescence_config: ArborescenceConfig | None = None


def get_arborescence_config() -> ArborescenceConfig:
    """
    Retourne l'instance singleton de la configuration.

    Returns:
        ArborescenceConfig chargée et validée
    """
    global _arborescence_config

    if _arborescence_config is None:
        _arborescence_config = load_arborescence_config()

    return _arborescence_config
