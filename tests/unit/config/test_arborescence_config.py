"""
Tests unitaires pour la configuration d'arborescence.

Story 3.2 - Task 2.6
Tests validation YAML schema, edge cases
"""

import pytest
from agents.src.config.arborescence_config import (
    ArborescenceConfig,
    get_arborescence_config,
    load_arborescence_config,
)
from pydantic import ValidationError


def test_load_arborescence_config_default():
    """Test chargement configuration par défaut."""
    config = load_arborescence_config()

    assert isinstance(config, ArborescenceConfig)
    assert config.root_path
    assert "pro" in config.categories
    assert "finance" in config.categories
    assert "universite" in config.categories
    assert "recherche" in config.categories
    assert "perso" in config.categories


def test_arborescence_has_5_root_categories():
    """Test présence des 5 catégories racines."""
    config = load_arborescence_config()

    categories = set(config.categories.keys())
    expected = {"pro", "finance", "universite", "recherche", "perso"}

    assert categories == expected


def test_finance_has_5_perimeters():
    """Test présence des 5 périmètres finance OFFICIELS."""
    config = load_arborescence_config()

    finance_subcats = config.categories["finance"]["subcategories"]
    perimeters = set(finance_subcats.keys())
    expected = {"selarl", "scm", "sci_ravas", "sci_malbosc", "personal"}

    assert perimeters == expected


def test_get_category_path_pro():
    """Test calcul chemin catégorie pro."""
    config = load_arborescence_config()

    path = config.get_category_path("pro", "administratif")
    assert path == "pro/administratif"


def test_get_category_path_finance_selarl():
    """Test calcul chemin finance SELARL."""
    config = load_arborescence_config()

    path = config.get_category_path("finance", "selarl")
    # Path template: "finance/selarl/{year}/{month}-{month_name}"
    # get_category_path retourne le préfixe sans variables
    assert path == "finance/selarl"


def test_get_category_path_universite_theses():
    """Test calcul chemin université thèses."""
    config = load_arborescence_config()

    path = config.get_category_path("universite", "theses")
    assert path == "universite/theses"


def test_get_category_path_unknown_category_raises():
    """Test catégorie inconnue lève KeyError."""
    config = load_arborescence_config()

    with pytest.raises(KeyError, match="Unknown category"):
        config.get_category_path("invalid_category")


def test_get_category_path_unknown_subcategory_raises():
    """Test sous-catégorie inconnue lève KeyError."""
    config = load_arborescence_config()

    with pytest.raises(KeyError, match="Unknown subcategory"):
        config.get_category_path("finance", "invalid_perimeter")


def test_validate_finance_perimeter_valid():
    """Test validation périmètre finance valide."""
    config = load_arborescence_config()

    assert config.validate_finance_perimeter("selarl") is True
    assert config.validate_finance_perimeter("scm") is True
    assert config.validate_finance_perimeter("sci_ravas") is True
    assert config.validate_finance_perimeter("sci_malbosc") is True
    assert config.validate_finance_perimeter("personal") is True


def test_validate_finance_perimeter_invalid_raises():
    """Test validation périmètre finance invalide lève ValueError."""
    config = load_arborescence_config()

    with pytest.raises(ValueError, match="Invalid financial perimeter"):
        config.validate_finance_perimeter("invalid_perimeter")


def test_anti_contamination_enabled():
    """Test que l'anti-contamination est activée."""
    config = load_arborescence_config()

    assert config.anti_contamination["enabled"] is True


def test_validation_max_depth():
    """Test profondeur maximale définie."""
    config = load_arborescence_config()

    assert config.validation["max_depth"] == 6


def test_validation_forbidden_names():
    """Test noms interdits Windows."""
    config = load_arborescence_config()

    forbidden = config.validation["forbidden_names"]
    assert "CON" in forbidden
    assert "PRN" in forbidden
    assert "AUX" in forbidden


def test_validation_forbidden_chars():
    """Test caractères interdits."""
    config = load_arborescence_config()

    forbidden_chars = config.validation["forbidden_chars"]
    assert "<" in forbidden_chars
    assert ">" in forbidden_chars
    assert ":" in forbidden_chars
    assert '"' in forbidden_chars


def test_singleton_get_arborescence_config():
    """Test singleton retourne toujours même instance."""
    config1 = get_arborescence_config()
    config2 = get_arborescence_config()

    assert config1 is config2  # Même instance en mémoire


def test_arborescence_config_root_path_not_empty():
    """Test root_path ne peut pas être vide."""
    with pytest.raises(ValidationError, match="root_path cannot be empty"):
        ArborescenceConfig(
            root_path="", transit_paths={}, categories={}, validation={}, anti_contamination={}
        )


def test_arborescence_config_missing_category_raises():
    """Test configuration avec catégorie manquante lève ValidationError."""
    with pytest.raises(ValidationError, match="Categories must be exactly"):
        ArborescenceConfig(
            root_path="/path",
            transit_paths={},
            categories={
                "pro": {},
                "finance": {},
                # Manque: universite, recherche, perso
            },
            validation={},
            anti_contamination={},
        )


def test_arborescence_config_missing_finance_perimeter_raises():
    """Test configuration finance avec périmètre manquant lève ValidationError."""
    with pytest.raises(ValidationError, match="Finance subcategories must be exactly"):
        ArborescenceConfig(
            root_path="/path",
            transit_paths={},
            categories={
                "pro": {},
                "finance": {
                    "subcategories": {
                        "selarl": {},
                        # Manque: scm, sci_ravas, sci_malbosc, personal
                    }
                },
                "universite": {},
                "recherche": {},
                "perso": {},
            },
            validation={},
            anti_contamination={},
        )


def test_arborescence_config_extra_category_raises():
    """Test configuration avec catégorie supplémentaire lève ValidationError."""
    with pytest.raises(ValidationError, match="Categories must be exactly"):
        ArborescenceConfig(
            root_path="/path",
            transit_paths={},
            categories={
                "pro": {},
                "finance": {
                    "subcategories": {
                        "selarl": {},
                        "scm": {},
                        "sci_ravas": {},
                        "sci_malbosc": {},
                        "personal": {},
                    }
                },
                "universite": {},
                "recherche": {},
                "perso": {},
                "extra_category": {},  # Catégorie non autorisée
            },
            validation={},
            anti_contamination={},
        )
