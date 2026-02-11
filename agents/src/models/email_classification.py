"""
Modèles Pydantic pour classification d'emails (Story 2.2).

Schémas de validation pour les résultats de classification LLM Claude Sonnet 4.5.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmailClassification(BaseModel):
    """
    Résultat de classification d'un email par Claude Sonnet 4.5.

    Utilisé pour parser et valider le JSON retourné par le LLM.

    Attributes:
        category: Catégorie de l'email parmi les 8 catégories supportées
        confidence: Score de confiance entre 0.0 (aucune confiance) et 1.0 (certitude absolue)
        reasoning: Explication textuelle de la décision (minimum 10 caractères)
        keywords: Liste des mots-clés identifiés qui ont influencé la classification
        suggested_priority: Priorité suggérée parmi low/normal/high/urgent
    """

    category: str = Field(
        ...,
        pattern=r"^(medical|finance|faculty|research|personnel|urgent|spam|unknown)$",
        description="Catégorie de l'email",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score de confiance de la classification (0.0-1.0)",
    )
    reasoning: str = Field(
        ...,
        min_length=10,
        description="Explication de la classification (minimum 10 caractères)",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Liste des mots-clés identifiés",
    )
    suggested_priority: str = Field(
        default="normal",
        pattern=r"^(low|normal|high|urgent)$",
        description="Priorité suggérée pour l'email",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "category": "medical",
                    "confidence": 0.92,
                    "reasoning": "Email du cabinet SELARL, contient mentions patients et CPAM",
                    "keywords": ["SELARL", "patients", "CPAM", "consultation"],
                    "suggested_priority": "high",
                },
                {
                    "category": "finance",
                    "confidence": 0.88,
                    "reasoning": "Email banque professionnelle avec montant et compte",
                    "keywords": ["banque", "virement", "compte pro"],
                    "suggested_priority": "normal",
                },
                {
                    "category": "research",
                    "confidence": 0.95,
                    "reasoning": "Invitation soutenance thèse, mention doctorat",
                    "keywords": ["thèse", "soutenance", "doctorat", "jury"],
                    "suggested_priority": "urgent",
                },
            ]
        }
    }
