"""
Tests unitaires pour models/email_classification.py

Vérifie la validation Pydantic du schema EmailClassification.
"""

import pytest
from agents.src.models.email_classification import EmailClassification
from pydantic import ValidationError

# ==========================================
# Tests Valid Inputs
# ==========================================


def test_email_classification_valid_pro():
    """Test création avec données valides pour category pro."""
    data = {
        "category": "pro",
        "confidence": 0.92,
        "reasoning": "Expéditeur URSSAF, mentions cotisations SELARL",
        "keywords": ["SELARL", "cotisations", "URSSAF"],
        "suggested_priority": "high",
    }

    classification = EmailClassification(**data)

    assert classification.category == "pro"
    assert classification.confidence == 0.92
    assert classification.reasoning == "Expéditeur URSSAF, mentions cotisations SELARL"
    assert classification.keywords == ["SELARL", "cotisations", "URSSAF"]
    assert classification.suggested_priority == "high"


def test_email_classification_valid_all_categories():
    """Test que toutes les catégories valides sont acceptées."""
    valid_categories = [
        "pro",
        "finance",
        "universite",
        "recherche",
        "perso",
        "urgent",
        "spam",
        "inconnu",
    ]

    for category in valid_categories:
        classification = EmailClassification(
            category=category,
            confidence=0.85,
            reasoning="Test reasoning for category",
            keywords=["test"],
            suggested_priority="normal",
        )
        assert classification.category == category


def test_email_classification_valid_all_priorities():
    """Test que toutes les priorités valides sont acceptées."""
    valid_priorities = ["low", "normal", "high", "urgent"]

    for priority in valid_priorities:
        classification = EmailClassification(
            category="pro",
            confidence=0.85,
            reasoning="Email classification test with valid reasoning content",
            suggested_priority=priority,
        )
        assert classification.suggested_priority == priority


def test_email_classification_default_values():
    """Test valeurs par défaut (keywords vide, priority normal)."""
    # Sans keywords ni priority
    classification = EmailClassification(
        category="pro",
        confidence=0.85,
        reasoning="Test reasoning minimum fields",
    )

    assert classification.keywords == []
    assert classification.suggested_priority == "normal"


def test_email_classification_confidence_boundaries():
    """Test valeurs limites de confidence (0.0 et 1.0)."""
    # Confidence 0.0
    low_conf = EmailClassification(
        category="inconnu",
        confidence=0.0,
        reasoning="No confidence at all",
    )
    assert low_conf.confidence == 0.0

    # Confidence 1.0
    high_conf = EmailClassification(
        category="pro",
        confidence=1.0,
        reasoning="Email content clearly indicates high certainty classification result",
    )
    assert high_conf.confidence == 1.0


# ==========================================
# Tests Invalid Inputs
# ==========================================


def test_email_classification_invalid_category():
    """Test que catégorie invalide est rejetée."""
    with pytest.raises(ValidationError) as exc_info:
        EmailClassification(
            category="invalid_category",
            confidence=0.85,
            reasoning="Valid reasoning text here",
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("category",)
    assert "pattern" in errors[0]["type"] or "string_pattern_mismatch" in errors[0]["type"]


def test_email_classification_confidence_out_of_range_low():
    """Test que confidence < 0.0 est rejetée."""
    with pytest.raises(ValidationError) as exc_info:
        EmailClassification(
            category="pro",
            confidence=-0.1,
            reasoning="Valid reasoning text here",
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("confidence",)
    assert "greater_than_equal" in errors[0]["type"]


def test_email_classification_confidence_out_of_range_high():
    """Test que confidence > 1.0 est rejetée."""
    with pytest.raises(ValidationError) as exc_info:
        EmailClassification(
            category="pro",
            confidence=1.5,
            reasoning="Valid reasoning text here",
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("confidence",)
    assert "less_than_equal" in errors[0]["type"]


def test_email_classification_reasoning_too_short():
    """Test que reasoning < 10 caractères est rejeté."""
    with pytest.raises(ValidationError) as exc_info:
        EmailClassification(
            category="pro",
            confidence=0.85,
            reasoning="Short",  # Seulement 5 caractères
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("reasoning",)
    assert "string_too_short" in errors[0]["type"]


def test_email_classification_invalid_priority():
    """Test que priorité invalide est rejetée."""
    with pytest.raises(ValidationError) as exc_info:
        EmailClassification(
            category="pro",
            confidence=0.85,
            reasoning="Email classification test with valid reasoning content",
            suggested_priority="invalid_priority",
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("suggested_priority",)
    assert "pattern" in errors[0]["type"] or "string_pattern_mismatch" in errors[0]["type"]


def test_email_classification_missing_required_fields():
    """Test que les champs requis manquants génèrent des erreurs."""
    # Manque category, confidence, reasoning
    with pytest.raises(ValidationError) as exc_info:
        EmailClassification()

    errors = exc_info.value.errors()
    missing_fields = {err["loc"][0] for err in errors}

    assert "category" in missing_fields
    assert "confidence" in missing_fields
    assert "reasoning" in missing_fields


# ==========================================
# Tests JSON Serialization
# ==========================================


def test_email_classification_to_dict():
    """Test sérialisation en dict."""
    classification = EmailClassification(
        category="pro",
        confidence=0.92,
        reasoning="Email classification test with valid reasoning content",
        keywords=["test"],
        suggested_priority="high",
    )

    data = classification.model_dump()

    assert data["category"] == "pro"
    assert data["confidence"] == 0.92
    assert data["reasoning"] == "Test reasoning"
    assert data["keywords"] == ["test"]
    assert data["suggested_priority"] == "high"


def test_email_classification_to_json():
    """Test sérialisation en JSON."""
    classification = EmailClassification(
        category="finance",
        confidence=0.88,
        reasoning="Banking email detected",
        keywords=["bank", "account"],
        suggested_priority="normal",
    )

    json_str = classification.model_dump_json()

    assert "finance" in json_str
    assert "0.88" in json_str
    assert "Banking email detected" in json_str


def test_email_classification_from_json():
    """Test désérialisation depuis JSON."""
    json_data = """
    {
        "category": "recherche",
        "confidence": 0.95,
        "reasoning": "Thesis defense invitation",
        "keywords": ["thesis", "defense", "PhD"],
        "suggested_priority": "urgent"
    }
    """

    classification = EmailClassification.model_validate_json(json_data)

    assert classification.category == "recherche"
    assert classification.confidence == 0.95
    assert "thesis" in classification.keywords
