"""
Factory helper pour créer des ActionResult valides dans les tests.

Évite la duplication de code et garantit le respect des contraintes Pydantic.
"""

from agents.src.middleware.models import ActionResult


def create_valid_action_result(
    input_summary: str = "Test input document for validation",
    output_summary: str = "Successfully processed test document",
    confidence: float = 0.95,
    reasoning: str = "Test reasoning with sufficient length to meet Pydantic constraints (20+ chars)",
    **kwargs,
) -> ActionResult:
    """
    Crée un ActionResult valide pour les tests.

    Args:
        input_summary: Résumé entrée (min 10 chars)
        output_summary: Résumé sortie (min 10 chars)
        confidence: Confiance 0.0-1.0
        reasoning: Explication (min 20 chars)
        **kwargs: Champs additionnels (payload, steps, etc.)

    Returns:
        ActionResult valide respectant toutes les contraintes Pydantic
    """
    return ActionResult(
        input_summary=input_summary,
        output_summary=output_summary,
        confidence=confidence,
        reasoning=reasoning,
        **kwargs,
    )
