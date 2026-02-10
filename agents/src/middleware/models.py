"""
Modèles Pydantic pour le Trust Layer de Friday 2.0.

Ce module définit les modèles de données standardisés pour le système d'observabilité
et de confiance (Trust Layer). Chaque action de module doit retourner un ActionResult.
"""

from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class StepDetail(BaseModel):
    """Détail d'une étape dans l'exécution d'une action."""

    step_number: int = Field(..., description="Numéro de l'étape (1, 2, 3...)")
    description: str = Field(..., description="Description de l'étape")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence de cette étape (0.0-1.0)"
    )
    duration_ms: Optional[int] = Field(None, description="Durée d'exécution en millisecondes")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Métadonnées supplémentaires"
    )

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Valide que la confidence est entre 0.0 et 1.0."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v


class ActionResult(BaseModel):
    """
    Résultat standardisé d'une action de module.

    Chaque action décorée avec @friday_action doit retourner un ActionResult.
    Ce modèle garantit une traçabilité complète et permet le feedback loop.
    """

    # Identifiants
    action_id: UUID = Field(default_factory=uuid4, description="ID unique de l'action")

    # Contexte de l'action (rempli par @friday_action)
    module: Optional[str] = Field(None, description="Module source (rempli par @friday_action)")
    action_type: Optional[str] = Field(
        None, description="Nom de l'action (rempli par @friday_action)"
    )

    # Résumés obligatoires
    input_summary: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Résumé de ce qui est entré (10-500 chars)",
    )
    output_summary: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Résumé de ce qui a été fait (10-500 chars)",
    )

    # Métriques de confiance
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence globale (MIN de tous les steps, 0.0-1.0)",
    )
    reasoning: str = Field(
        ...,
        min_length=20,
        max_length=2000,
        description="Explication du raisonnement (20-2000 chars)",
    )

    # Données optionnelles
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Données techniques optionnelles (non affichées à l'utilisateur)",
    )
    steps: list[StepDetail] = Field(default_factory=list, description="Détails des sous-étapes")

    # Métadonnées de traçabilité
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp UTC de l'action"
    )
    duration_ms: Optional[int] = Field(
        None, description="Durée totale d'exécution en millisecondes"
    )

    # Trust level appliqué (rempli par @friday_action)
    trust_level: Optional[str] = Field(
        None, description="Trust level appliqué (rempli par @friday_action)"
    )
    status: Optional[str] = Field(
        None, description="Statut de l'action (rempli par @friday_action)"
    )

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Valide que la confidence est entre 0.0 et 1.0."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v

    @field_validator("trust_level")
    @classmethod
    def validate_trust_level(cls, v: Optional[str]) -> Optional[str]:
        """Valide que trust_level est valide."""
        if v is None:
            return v
        valid_levels = {"auto", "propose", "blocked"}
        if v not in valid_levels:
            raise ValueError(f"trust_level must be one of {valid_levels}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        """Valide que status est valide."""
        if v is None:
            return v
        valid_statuses = {"auto", "pending", "approved", "rejected", "corrected", "expired", "error", "executed"}
        if v not in valid_statuses:
            raise ValueError(f"status must be one of {valid_statuses}")
        return v

    def model_dump_receipt(self) -> dict[str, Any]:
        """
        Export formaté pour stockage dans core.action_receipts.

        Retourne un dict compatible avec la structure de la table SQL.
        Les steps sont fusionnés dans payload (JSONB), pas un champ séparé.

        Raises:
            ValueError: Si module ou action_type sont None (doivent être remplis par @friday_action)
        """
        # Validation obligatoire : module et action_type NOT NULL en SQL
        if self.module is None or self.action_type is None:
            raise ValueError(
                "module and action_type must be set by @friday_action before creating receipt"
            )

        # Fusionner steps dans payload (pas un champ séparé en SQL)
        payload_with_steps = {**self.payload}
        if self.steps:
            payload_with_steps["steps"] = [step.model_dump() for step in self.steps]

        return {
            "id": str(self.action_id),
            "module": self.module,
            "action_type": self.action_type,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "payload": payload_with_steps,  # JSONB avec steps inclus
            "duration_ms": self.duration_ms,
            "trust_level": self.trust_level,
            "status": self.status,
        }


class CorrectionRule(BaseModel):
    """
    Règle de correction explicite pour le feedback loop.

    Les règles sont stockées dans core.correction_rules et injectées
    dans les prompts LLM pour garantir la répétabilité des corrections.
    """

    id: UUID = Field(default_factory=uuid4, description="ID unique de la règle")
    module: str = Field(..., description="Module concerné (ex: 'email')")
    action_type: Optional[str] = Field(
        None, description="Action spécifique (None = toutes actions du module)"
    )
    scope: str = Field(..., description="Portée de la règle (ex: 'classification', 'drafting')")
    priority: int = Field(..., ge=1, le=100, description="Priorité (1=max, 100=min)")
    conditions: dict[str, Any] = Field(..., description="Conditions d'application (format JSON)")
    output: dict[str, Any] = Field(..., description="Correction à appliquer (format JSON)")
    source_receipts: list[str] = Field(
        default_factory=list,
        description="IDs des receipts ayant généré cette règle",
    )
    hit_count: int = Field(default=0, description="Nombre de fois où la règle a été appliquée")
    active: bool = Field(default=True, description="Règle active ou non")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Date de création"
    )
    created_by: str = Field(default="owner", description="Créateur de la règle")

    def format_for_prompt(self) -> str:
        """
        Formate la règle pour injection dans un prompt LLM.

        Retourne une string lisible pour le LLM décrivant la règle.
        """
        rule_str = f"[Règle priorité {self.priority}] {self.scope}: "
        rule_str += f"SI {self.conditions} ALORS {self.output}"
        if self.hit_count > 0:
            rule_str += f" (appliquée {self.hit_count}× avec succès)"
        return rule_str


class TrustMetric(BaseModel):
    """
    Métrique hebdomadaire de trust pour un module/action.

    Utilisé pour la promotion/rétrogradation automatique des trust levels.
    """

    module: str = Field(..., description="Module concerné")
    action_type: str = Field(..., description="Action concernée")
    week_start: datetime = Field(..., description="Début de la semaine (lundi 00:00)")
    total_actions: int = Field(..., ge=0, description="Nombre total d'actions cette semaine")
    corrected_actions: int = Field(..., ge=0, description="Nombre d'actions corrigées")
    accuracy: float = Field(..., ge=0.0, le=1.0, description="Accuracy = 1 - (corrected / total)")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence moyenne")
    current_trust_level: str = Field(..., description="Trust level actuel (auto/propose/blocked)")
    recommended_trust_level: Optional[str] = Field(
        None, description="Trust level recommandé basé sur accuracy"
    )

    @field_validator("accuracy", "avg_confidence")
    @classmethod
    def validate_percentage(cls, v: float) -> float:
        """Valide que le pourcentage est entre 0.0 et 1.0."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Percentage must be between 0.0 and 1.0")
        return v

    def should_retrogradation(self) -> bool:
        """
        Détermine si une rétrogradation est nécessaire.

        Règle : accuracy <90% sur 1 semaine + échantillon >=10 actions
        """
        return (
            self.total_actions >= 10 and self.accuracy < 0.90 and self.current_trust_level == "auto"
        )

    def can_promotion(self) -> bool:
        """
        Détermine si une promotion est possible (pas automatique).

        Règle : accuracy >=95% sur 3 semaines + validation manuelle owner
        Note : La vérification "3 semaines" se fait au niveau DB.
        """
        return (
            self.total_actions >= 10
            and self.accuracy >= 0.95
            and self.current_trust_level == "propose"
        )
