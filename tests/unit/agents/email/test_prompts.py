"""
Tests unitaires pour agents/email/prompts.py

Vérifie la construction des prompts de classification.
"""

import pytest

from agents.src.agents.email.prompts import (
    CATEGORY_DESCRIPTIONS,
    build_classification_prompt,
    validate_classification_response,
)
from agents.src.middleware.models import CorrectionRule


# ==========================================
# Tests build_classification_prompt
# ==========================================


def test_build_classification_prompt_basic():
    """Test construction prompt basique sans règles de correction."""
    email_text = (
        "From: [EMAIL_1]\n"
        "Subject: Cotisations SELARL Q4 2025\n"
        "Body: Voici le montant des cotisations..."
    )

    system_prompt, user_prompt = build_classification_prompt(
        email_text=email_text,
        correction_rules=None,
    )

    # System prompt doit contenir contexte utilisateur
    assert "médecin français" in system_prompt.lower()
    assert "SELARL" in system_prompt

    # System prompt doit contenir toutes les catégories
    for category in CATEGORY_DESCRIPTIONS:
        assert category in system_prompt

    # System prompt doit contenir format JSON attendu
    assert "category" in system_prompt
    assert "confidence" in system_prompt
    assert "reasoning" in system_prompt
    assert "keywords" in system_prompt
    assert "suggested_priority" in system_prompt

    # User prompt doit contenir l'email
    assert email_text in user_prompt
    assert "Classifie cet email" in user_prompt


def test_build_classification_prompt_with_correction_rules():
    """Test injection des règles de correction dans le prompt."""
    email_text = "Test email"

    rules = [
        CorrectionRule(
            module="email",
            action_type="classify",
            priority=10,
            conditions={"from": "@urssaf.fr"},
            output={"category": "finance"},
            scope="classification",
        ),
        CorrectionRule(
            module="email",
            action_type="classify",
            priority=20,
            conditions={"subject": "thèse"},
            output={"category": "research"},
            scope="classification",
        ),
    ]

    system_prompt, user_prompt = build_classification_prompt(
        email_text=email_text,
        correction_rules=rules,
    )

    # System prompt doit contenir section règles de correction
    assert "RÈGLES DE CORRECTION PRIORITAIRES" in system_prompt
    assert "Règle 1:" in system_prompt
    assert "Règle 2:" in system_prompt
    assert "priorité 10" in system_prompt
    assert "priorité 20" in system_prompt


def test_build_classification_prompt_max_50_rules():
    """Test limitation à 50 règles de correction."""
    email_text = "Test email"

    # Créer 60 règles
    rules = [
        CorrectionRule(
            module="email",
            action_type="classify",
            priority=i,
            conditions={"test": f"condition-{i}"},
            output={"category": "medical"},
            scope="classification",
        )
        for i in range(1, 61)
    ]

    system_prompt, user_prompt = build_classification_prompt(
        email_text=email_text,
        correction_rules=rules,
    )

    # System prompt doit contenir max 50 règles
    assert "Règle 1:" in system_prompt
    assert "Règle 50:" in system_prompt
    assert "Règle 51:" not in system_prompt

    # Doit contenir avertissement >50 règles
    assert "60 règles actives au total" in system_prompt
    assert "seules les 50 plus prioritaires" in system_prompt


def test_build_classification_prompt_empty_rules():
    """Test comportement avec liste vide de règles."""
    email_text = "Test email"

    system_prompt, user_prompt = build_classification_prompt(
        email_text=email_text,
        correction_rules=[],
    )

    # Pas de section règles de correction
    assert "RÈGLES DE CORRECTION PRIORITAIRES" not in system_prompt


def test_build_classification_prompt_all_categories_present():
    """Test que toutes les 8 catégories sont présentes dans le prompt."""
    email_text = "Test email"

    system_prompt, user_prompt = build_classification_prompt(
        email_text=email_text,
    )

    expected_categories = [
        "medical",
        "finance",
        "faculty",
        "research",
        "personnel",
        "urgent",
        "spam",
        "unknown",
    ]

    for category in expected_categories:
        assert f"`{category}`" in system_prompt


def test_build_classification_prompt_format_instructions():
    """Test que les instructions de format JSON sont présentes."""
    email_text = "Test email"

    system_prompt, user_prompt = build_classification_prompt(
        email_text=email_text,
    )

    # Instructions format JSON
    assert "JSON valide" in system_prompt
    assert "sans texte avant ou après" in system_prompt
    assert "Pas de markdown" in system_prompt
    assert "SEULEMENT le JSON" in system_prompt

    # Règles strictes
    assert "doute → category='unknown'" in system_prompt
    assert "Reasoning doit expliquer" in system_prompt
    assert "JAMAIS de commentaires hors JSON" in system_prompt


def test_build_classification_prompt_user_context():
    """Test que le contexte utilisateur (médecin multi-casquettes) est présent."""
    email_text = "Test email"

    system_prompt, user_prompt = build_classification_prompt(
        email_text=email_text,
    )

    # Contexte multi-casquettes
    assert "Médecin libéral" in system_prompt
    assert "Enseignant universitaire" in system_prompt
    assert "Directeur de thèses" in system_prompt
    assert "Investisseur immobilier" in system_prompt


# ==========================================
# Tests validate_classification_response
# ==========================================


def test_validate_classification_response_valid_json():
    """Test validation JSON de classification valide."""
    valid_json = """
    {
        "category": "medical",
        "confidence": 0.92,
        "reasoning": "Email from URSSAF about SELARL contributions",
        "keywords": ["SELARL", "cotisations"],
        "suggested_priority": "high"
    }
    """

    assert validate_classification_response(valid_json) is True


def test_validate_classification_response_missing_keys():
    """Test validation JSON avec clés manquantes."""
    # Manque "reasoning"
    invalid_json = """
    {
        "category": "medical",
        "confidence": 0.92
    }
    """

    assert validate_classification_response(invalid_json) is False


def test_validate_classification_response_not_json():
    """Test validation texte non-JSON."""
    not_json = "This is not JSON at all, just plain text."

    assert validate_classification_response(not_json) is False


def test_validate_classification_response_with_markdown():
    """Test validation JSON entouré de markdown (invalide)."""
    markdown_json = """
    ```json
    {
        "category": "medical",
        "confidence": 0.92,
        "reasoning": "Test",
        "keywords": []
    }
    ```
    """

    # Devrait être invalide car commence par ```json, pas {
    assert validate_classification_response(markdown_json) is False


def test_validate_classification_response_empty_string():
    """Test validation chaîne vide."""
    assert validate_classification_response("") is False


def test_validate_classification_response_whitespace():
    """Test validation avec espaces autour du JSON."""
    valid_json_with_whitespace = """

    {
        "category": "finance",
        "confidence": 0.88,
        "reasoning": "Banking email"
    }

    """

    assert validate_classification_response(valid_json_with_whitespace) is True
