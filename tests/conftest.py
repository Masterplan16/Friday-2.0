"""
Friday 2.0 - Configuration pytest globale.

Fixtures partagees entre tous les tests (unit, integration, e2e).
"""

import pytest


@pytest.fixture
def sample_email_text() -> str:
    """Texte email avec PII pour tests anonymisation."""
    return (
        "Bonjour Dr. Martin,\n"
        "Je suis Antonio Lopez, numero de telephone 06 12 34 56 78.\n"
        "Mon adresse email est antonio@example.com.\n"
        "Rendez-vous le 15 mars 2026 a 14h au cabinet.\n"
        "Cordialement"
    )


@pytest.fixture
def sample_action_result_data() -> dict:
    """Donnees pour creer un ActionResult de test."""
    return {
        "module": "email",
        "action": "classify",
        "input_summary": "Email de dr.martin@hopital.fr: Resultats labo",
        "output_summary": "Classe: medical/admin, Priorite: normal",
        "confidence": 0.87,
        "reasoning": "Mots-cles detectes: resultats, labo. Expediteur connu comme VIP.",
        "trust_level": "propose",
        "status": "pending",
    }
