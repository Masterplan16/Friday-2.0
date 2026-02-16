"""
Modèles Pydantic pour détection VIP et urgence (Story 2.3).

Schémas de validation pour VIP senders et résultats de détection urgence.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class VIPSender(BaseModel):
    """
    Expéditeur VIP stocké avec anonymisation RGPD.

    Utilisé pour lookup rapide via hash SHA256 sans accès à la PII originale.

    Attributes:
        id: Identifiant unique UUID
        email_anon: Email anonymisé via Presidio (ex: [EMAIL_123])
        email_hash: SHA256(email_original.lower().strip()) pour lookup
        label: Label optionnel (ex: "Doyen", "Comptable")
        priority_override: Force priorité si défini (high/urgent)
        designation_source: Source: manual (/vip add) ou learned (auto)
        added_by: User ID Telegram qui a ajouté ce VIP
        emails_received_count: Nombre d'emails reçus de ce VIP
        active: Soft delete (False = VIP retiré)
    """

    id: Optional[UUID] = Field(
        default=None,
        description="Identifiant unique UUID (None avant insertion)",
    )
    email_anon: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Email anonymisé via Presidio (ex: [EMAIL_123])",
    )
    email_hash: str = Field(
        ...,
        pattern=r"^[a-f0-9]{64}$",
        description="SHA256 hexdigest (64 caractères hex)",
    )
    label: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Label optionnel (ex: 'Doyen', 'Comptable')",
    )
    priority_override: Optional[str] = Field(
        default=None,
        pattern=r"^(high|urgent)$",
        description="Force priorité si défini",
    )
    designation_source: str = Field(
        default="manual",
        pattern=r"^(manual|learned)$",
        description="Source: manual (/vip add) ou learned (apprentissage)",
    )
    added_by: Optional[UUID] = Field(
        default=None,
        description="User ID Telegram qui a ajouté ce VIP",
    )
    emails_received_count: int = Field(
        default=0,
        ge=0,
        description="Nombre d'emails reçus de ce VIP",
    )
    active: bool = Field(
        default=True,
        description="Soft delete (False = VIP retiré)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "email_anon": "[EMAIL_VIP_DOYEN_123]",
                    "email_hash": "a" * 64,
                    "label": "Doyen Faculté Médecine",
                    "priority_override": "urgent",
                    "designation_source": "manual",
                    "added_by": "987e6543-e21b-98d7-b654-321098765432",
                    "emails_received_count": 42,
                    "active": True,
                },
                {
                    "id": "234e5678-e89b-12d3-a456-426614174111",
                    "email_anon": "[EMAIL_COMPTABLE_456]",
                    "email_hash": "b" * 64,
                    "label": "Comptable SCM",
                    "priority_override": None,
                    "designation_source": "manual",
                    "added_by": "987e6543-e21b-98d7-b654-321098765432",
                    "emails_received_count": 15,
                    "active": True,
                },
            ]
        }
    }


class UrgencyResult(BaseModel):
    """
    Résultat de détection urgence multi-facteurs.

    Algorithme: urgency_score = 0.5*VIP + 0.3*keywords + 0.2*deadline
    Seuil: is_urgent = urgency_score >= 0.6

    Attributes:
        is_urgent: True si email détecté comme urgent (score >= 0.6)
        confidence: Score de confiance/urgence (0.0-1.0)
        reasoning: Explication de la décision (minimum 10 caractères)
        factors: Dictionnaire des facteurs détectés (vip, keywords, deadline)
    """

    is_urgent: bool = Field(
        ...,
        description="True si email détecté comme urgent (score >= 0.6)",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score de confiance/urgence (0.0-1.0)",
    )
    reasoning: str = Field(
        ...,
        min_length=10,
        description="Explication de la décision (minimum 10 caractères)",
    )
    factors: dict = Field(
        default_factory=dict,
        description="Facteurs détectés (vip: bool, keywords: list, deadline: dict)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "is_urgent": True,
                    "confidence": 0.8,
                    "reasoning": "Email VIP + keyword 'deadline' détecté -> score 0.8",
                    "factors": {
                        "vip": True,
                        "keywords": ["deadline", "urgent"],
                        "deadline": {
                            "pattern": "avant demain",
                            "context": "Réponse avant demain 17h",
                        },
                    },
                },
                {
                    "is_urgent": False,
                    "confidence": 0.5,
                    "reasoning": "VIP seul sans keywords urgence -> score 0.5 (sous seuil 0.6)",
                    "factors": {
                        "vip": True,
                        "keywords": [],
                        "deadline": None,
                    },
                },
                {
                    "is_urgent": True,
                    "confidence": 0.7,
                    "reasoning": "Keywords urgence multiples détectés -> score 0.7",
                    "factors": {
                        "vip": False,
                        "keywords": ["URGENT", "immédiat", "deadline"],
                        "deadline": {"pattern": "ce soir", "context": "Réponse attendue ce soir"},
                    },
                },
            ]
        }
    }
