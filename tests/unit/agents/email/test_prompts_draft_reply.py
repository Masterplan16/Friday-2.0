"""
Tests unitaires pour agents.email.prompts_draft_reply

Tests la construction des prompts LLM pour génération brouillons emails
avec few-shot learning, correction rules, et user preferences.

Story: 2.5 Brouillon Réponse Email
"""

import pytest
from agents.src.agents.email.prompts_draft_reply import (
    _format_correction_rules,
    _format_user_preferences,
    _format_writing_examples,
    build_draft_reply_prompt,
    estimate_prompt_tokens,
    validate_prompt_length,
)


@pytest.fixture
def sample_email_text():
    """Email de test anonymisé"""
    return "Dear Dr. [NAME_1],\n\nCan I reschedule my [MEDICAL_TERM_1] for next week?\n\nBest regards,\n[NAME_2]"


@pytest.fixture
def sample_writing_examples():
    """Exemples de style rédactionnel"""
    return [
        {
            "subject": "Re: Request for information",
            "body": "Bonjour,\n\nVoici les informations demandées.\n\nBien cordialement,\nDr. Antonio Lopez",
        },
        {
            "subject": "Re: Meeting confirmation",
            "body": "Bonjour,\n\nJe confirme notre rendez-vous.\n\nCordialement,\nDr. Antonio Lopez",
        },
        {
            "subject": "Re: Question about treatment",
            "body": "Bonjour,\n\nVoici ma réponse à votre question.\n\nBien à vous,\nDr. Antonio Lopez",
        },
    ]


@pytest.fixture
def sample_correction_rules():
    """Règles de correction"""
    return [
        {
            "conditions": 'Remplacer "Bien à vous"',
            "output": 'Utiliser "Cordialement"',
            "priority": 1,
        },
        {
            "conditions": "Toujours inclure signature complète",
            "output": "Dr. Antonio Lopez\nMédecin",
            "priority": 2,
        },
    ]


@pytest.fixture
def sample_user_preferences():
    """Préférences utilisateur"""
    return {"tone": "formal", "tutoiement": False, "verbosity": "concise"}


# ============================================================================
# Tests build_draft_reply_prompt (main function)
# ============================================================================


def test_build_draft_reply_prompt_returns_tuple(sample_email_text):
    """
    Test: build_draft_reply_prompt retourne un tuple (system, user)
    """
    system, user = build_draft_reply_prompt(
        email_text=sample_email_text,
        email_type="professional",
        correction_rules=[],
        writing_examples=[],
        user_preferences=None,
    )

    assert isinstance(system, str)
    assert isinstance(user, str)
    assert len(system) > 0
    assert len(user) > 0


def test_build_draft_reply_prompt_with_zero_examples(sample_email_text):
    """
    Test 1: Prompt généré avec 0 exemples (Day 1, style générique)

    Vérifie que le prompt fonctionne sans exemples
    """
    system, user = build_draft_reply_prompt(
        email_text=sample_email_text,
        email_type="professional",
        correction_rules=[],
        writing_examples=[],  # Pas d'exemples
        user_preferences=None,
    )

    # Vérifier structure system prompt
    assert "Friday" in system
    assert "Antonio Lopez" in system
    assert "Pas d'exemples disponibles" in system or "Day 1" in system

    # Vérifier que pas d'exemples injectés
    assert "Exemple 1" not in system

    # Vérifier user prompt
    assert "reschedule" in user
    assert "professional" in user


def test_build_draft_reply_prompt_with_three_examples(sample_email_text, sample_writing_examples):
    """
    Test 2: Prompt généré avec 3 exemples (injection few-shot)

    Vérifie que les exemples sont correctement injectés dans le system prompt
    """
    system, user = build_draft_reply_prompt(
        email_text=sample_email_text,
        email_type="professional",
        correction_rules=[],
        writing_examples=sample_writing_examples[:3],  # 3 exemples
        user_preferences=None,
    )

    # Vérifier injection few-shot
    assert "Exemples du style Mainteneur" in system
    assert "Exemple 1" in system
    assert "Exemple 2" in system
    assert "Exemple 3" in system

    # Vérifier contenu exemples
    assert "Request for information" in system
    assert "Meeting confirmation" in system
    assert "Question about treatment" in system

    # Vérifier bodies injectés
    assert "Voici les informations demandées" in system
    assert "Je confirme notre rendez-vous" in system


def test_build_draft_reply_prompt_correction_rules_injected(
    sample_email_text, sample_correction_rules
):
    """
    Test 3: Correction rules injectées correctement

    Vérifie que les règles actives sont injectées dans le system prompt
    """
    system, user = build_draft_reply_prompt(
        email_text=sample_email_text,
        email_type="professional",
        correction_rules=sample_correction_rules,  # 2 règles
        writing_examples=[],
        user_preferences=None,
    )

    # Vérifier injection rules
    assert "Règles de correction prioritaires" in system
    assert "1." in system
    assert "2." in system

    # Vérifier contenu rules
    assert 'Remplacer "Bien à vous"' in system
    assert 'Utiliser "Cordialement"' in system
    assert "signature complète" in system


def test_build_draft_reply_prompt_user_preferences_injected(
    sample_email_text, sample_user_preferences
):
    """
    Test 4: User preferences injectées (tone, tutoiement, verbosity)

    Vérifie que les préférences utilisateur sont injectées dans le system prompt
    """
    system, user = build_draft_reply_prompt(
        email_text=sample_email_text,
        email_type="professional",
        correction_rules=[],
        writing_examples=[],
        user_preferences=sample_user_preferences,
    )

    # Vérifier injection preferences
    assert "Ton : formel" in system or "formal" in system
    assert "Tutoiement : Non" in system or "tutoiement" in system.lower()
    assert "concis" in system or "concise" in system


def test_build_draft_reply_prompt_length_reasonable(
    sample_email_text, sample_writing_examples, sample_correction_rules
):
    """
    Test 5: Longueur totale prompt < 8000 tokens (limite raisonnable)

    Vérifie que même avec max exemples + règles, le prompt reste raisonnable
    """
    system, user = build_draft_reply_prompt(
        email_text=sample_email_text,
        email_type="professional",
        correction_rules=sample_correction_rules,
        writing_examples=sample_writing_examples,  # 3 exemples
        user_preferences=None,
    )

    # Vérifier longueur raisonnable
    total_chars = len(system) + len(user)
    assert total_chars < 50000, f"Prompt trop long: {total_chars} chars"

    # Vérifier estimation tokens
    estimated_tokens = estimate_prompt_tokens(system, user)
    assert estimated_tokens < 8000, f"Prompt trop long: ~{estimated_tokens} tokens"

    # Vérifier validation length
    assert validate_prompt_length(system, user, max_tokens=8000)


# ============================================================================
# Tests formatters (helpers internes)
# ============================================================================


def test_format_user_preferences_formal():
    """
    Test: _format_user_preferences avec style formel
    """
    prefs = {"tone": "formal", "tutoiement": False, "verbosity": "concise"}
    text = _format_user_preferences(prefs)

    assert "formel" in text or "formal" in text
    assert "Non" in text or "false" in text.lower()
    assert "concis" in text or "concise" in text


def test_format_user_preferences_informal():
    """
    Test: _format_user_preferences avec style informel
    """
    prefs = {"tone": "informal", "tutoiement": True, "verbosity": "detailed"}
    text = _format_user_preferences(prefs)

    assert "informel" in text or "informal" in text
    assert "Oui" in text or "true" in text.lower()
    assert "détaillé" in text or "detailed" in text


def test_format_writing_examples_empty():
    """
    Test: _format_writing_examples avec liste vide retourne ""
    """
    text = _format_writing_examples([])
    assert text == ""


def test_format_writing_examples_non_empty(sample_writing_examples):
    """
    Test: _format_writing_examples avec exemples retourne texte formaté
    """
    text = _format_writing_examples(sample_writing_examples)

    assert "Exemples du style Mainteneur" in text
    assert "Exemple 1" in text
    assert "Exemple 2" in text
    assert "Request for information" in text
    assert "Voici les informations demandées" in text


def test_format_correction_rules_empty():
    """
    Test: _format_correction_rules avec liste vide retourne ""
    """
    text = _format_correction_rules([])
    assert text == ""


def test_format_correction_rules_non_empty(sample_correction_rules):
    """
    Test: _format_correction_rules avec règles retourne texte formaté
    """
    text = _format_correction_rules(sample_correction_rules)

    assert "Règles de correction prioritaires" in text
    assert "1." in text
    assert "2." in text
    assert 'Remplacer "Bien à vous"' in text
    assert 'Utiliser "Cordialement"' in text


# ============================================================================
# Tests utilities
# ============================================================================


def test_estimate_prompt_tokens_short():
    """
    Test: estimate_prompt_tokens avec prompts courts
    """
    system = "Tu es Friday, assistant."
    user = "Email court."

    tokens = estimate_prompt_tokens(system, user)

    assert tokens > 0
    assert tokens < 100  # Prompts très courts


def test_estimate_prompt_tokens_long(sample_email_text, sample_writing_examples):
    """
    Test: estimate_prompt_tokens avec prompts longs (exemples + règles)
    """
    system, user = build_draft_reply_prompt(
        email_text=sample_email_text,
        email_type="professional",
        correction_rules=[],
        writing_examples=sample_writing_examples,
        user_preferences=None,
    )

    tokens = estimate_prompt_tokens(system, user)

    assert tokens > 100  # Prompts avec exemples
    assert tokens < 8000  # Mais raisonnables


def test_validate_prompt_length_ok():
    """
    Test: validate_prompt_length avec prompts OK
    """
    system = "Short system prompt" * 10
    user = "Short user prompt" * 10

    assert validate_prompt_length(system, user, max_tokens=8000)


def test_validate_prompt_length_too_long():
    """
    Test: validate_prompt_length avec prompts trop longs
    """
    # Générer prompt très long (>8000 tokens ≈ >10000 mots)
    system = "Very long system prompt " * 5000
    user = "Very long user prompt " * 5000

    assert not validate_prompt_length(system, user, max_tokens=8000)
