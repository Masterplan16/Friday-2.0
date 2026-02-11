"""
Pydantic models for email processing

Story 2.7: Email task extraction models
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class TaskDetected(BaseModel):
    """
    Représente une tâche détectée dans un email

    Story 2.7 AC1: Détection automatique tâches implicites
    """

    description: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Description de la tâche extraite"
    )
    priority: str = Field(
        ...,
        pattern="^(high|normal|low)$",
        description="Priorité de la tâche (high/normal/low)"
    )
    due_date: Optional[datetime] = Field(
        None,
        description="Date d'échéance si détectée (ISO 8601)"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confiance de la détection (0.0-1.0)"
    )
    context: str = Field(
        ...,
        max_length=1000,
        description="Contexte d'extraction (extrait email)"
    )
    priority_keywords: Optional[List[str]] = Field(
        None,
        description="Mots-clés ayant justifié la priorité (AC7)"
    )

    @field_validator("description")
    @classmethod
    def validate_description_not_empty(cls, v: str) -> str:
        """Valider que description n'est pas vide après strip"""
        if not v.strip():
            raise ValueError("Description cannot be empty or whitespace")
        return v.strip()

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        """Valider que priority est lowercase"""
        return v.lower()


class TaskExtractionResult(BaseModel):
    """
    Résultat complet de l'extraction de tâches depuis un email

    Story 2.7 AC1: Format extraction JSON structuré
    """

    tasks_detected: List[TaskDetected] = Field(
        default_factory=list,
        description="Liste des tâches détectées (peut être vide)"
    )
    confidence_overall: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confiance globale de l'extraction"
    )

    @field_validator("tasks_detected")
    @classmethod
    def validate_tasks_confidence(cls, v: List[TaskDetected]) -> List[TaskDetected]:
        """
        Valider que si tasks_detected est non-vide,
        tous ont confidence >= 0.0
        """
        for task in v:
            if task.confidence < 0.0 or task.confidence > 1.0:
                raise ValueError(
                    f"Task confidence must be 0.0-1.0, got {task.confidence}"
                )
        return v

    @field_validator("confidence_overall")
    @classmethod
    def validate_confidence_overall(cls, v: float) -> float:
        """Valider confidence_overall >= 0.0"""
        if v < 0.0 or v > 1.0:
            raise ValueError(f"Confidence overall must be 0.0-1.0, got {v}")
        return v
