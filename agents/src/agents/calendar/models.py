"""
Pydantic models pour detection evenements

Story 7.1 AC1-AC7: Models Event, EventDetectionResult
"""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from agents.src.core.models import Casquette
from pydantic import BaseModel, Field, field_validator, model_validator

from config.exceptions import AgentError, PipelineError


class EventType(str, Enum):
    """
    Types d'evenements supportes
    """

    MEDICAL = "medical"
    MEETING = "meeting"
    DEADLINE = "deadline"
    CONFERENCE = "conference"
    PERSONAL = "personal"
    OTHER = "other"


class EventStatus(str, Enum):
    """
    Status evenement (AC2)
    """

    PROPOSED = "proposed"  # Detecte, en attente validation
    CONFIRMED = "confirmed"  # Valide par Mainteneur
    CANCELLED = "cancelled"  # Rejete/annule


class Event(BaseModel):
    """
    Model Pydantic Event extrait depuis email

    Story 7.1 AC1: Structure JSON evenement detecte par Claude
    """

    title: str = Field(
        ..., min_length=1, max_length=500, description="Titre evenement (max 500 chars)"
    )

    start_datetime: datetime = Field(
        ..., description="Date/heure debut (ISO 8601, AC4: dates relatives converties en absolues)"
    )

    end_datetime: Optional[datetime] = Field(
        None, description="Date/heure fin (optionnel, infere si absent)"
    )

    location: Optional[str] = Field(
        None, max_length=500, description="Lieu evenement (AC6: NER extraction)"
    )

    participants: List[str] = Field(
        default_factory=list,
        description="Liste participants (AC6: NER extraction, anonymises Presidio)",
    )

    event_type: EventType = Field(
        EventType.OTHER,
        description="Type evenement (medical, meeting, deadline, conference, personal)",
    )

    casquette: Casquette = Field(
        ...,
        description="Classification multi-casquettes (AC5: medecin|enseignant|chercheur|personnel)",
    )

    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confiance extraction LLM (0.0-1.0, seuil AC1: >=0.75)"
    )

    context: Optional[str] = Field(
        None, max_length=1000, description="Contexte extraction (snippet email source)"
    )

    @field_validator("end_datetime")
    @classmethod
    def end_after_start(cls, v: Optional[datetime], info) -> Optional[datetime]:
        """
        Valide que end_datetime > start_datetime (si fourni)
        """
        if v is not None:
            start = info.data.get("start_datetime")
            if start and v <= start:
                raise ValueError("end_datetime doit etre apres start_datetime")
        return v

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        """
        Valide que title n'est pas vide ou whitespace uniquement
        """
        if not v.strip():
            raise ValueError("title ne peut pas etre vide")
        return v.strip()


class EventDetectionResult(BaseModel):
    """
    Resultat complet extraction evenements depuis email

    Story 7.1 AC1: Reponse Claude Sonnet 4.5 parsee
    """

    events_detected: List[Event] = Field(
        default_factory=list, description="Liste evenements detectes (peut etre vide si aucun)"
    )

    confidence_overall: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confiance globale extraction (min de tous events.confidence)",
    )

    email_id: Optional[str] = Field(None, description="UUID email source (ingestion.emails_raw.id)")

    processing_time_ms: Optional[int] = Field(
        None, ge=0, description="Temps traitement LLM en millisecondes (monitoring)"
    )

    model_used: str = Field(
        default="claude-sonnet-4-5-20250929", description="Model LLM utilise (Decision D17)"
    )

    @field_validator("confidence_overall")
    @classmethod
    def confidence_matches_min_event(cls, v: float, info) -> float:
        """
        Valide que confidence_overall = min(events.confidence)
        """
        events = info.data.get("events_detected", [])
        if events:
            min_confidence = min(event.confidence for event in events)
            if abs(v - min_confidence) > 0.01:  # Tolerance 0.01 pour float
                raise ValueError(
                    f"confidence_overall ({v}) doit etre min(events.confidence) = {min_confidence}"
                )
        return v


class EventExtractionError(AgentError):
    """
    Exception levee lors d'erreur extraction evenement

    Usage: erreurs parsing JSON Claude, RateLimitError retry epuise, circuit breaker
    """

    pass


class EventValidationError(PipelineError):
    """
    Exception levee lors d'erreur validation Pydantic Event

    Usage: start_datetime invalide, confidence hors range, casquette invalide
    """

    pass


# ============================================================================
# Story 7.3: Multi-casquettes & Conflits (AC4, AC6)
# ============================================================================


class ResolutionAction(str, Enum):
    """Action de résolution conflit (AC6)."""

    CANCEL = "cancel"  # Annuler événement
    MOVE = "move"  # Déplacer événement
    IGNORE = "ignore"  # Ignorer conflit


class CalendarEvent(BaseModel):
    """
    Événement calendrier simplifié pour détection conflits.

    Utilisé par conflict_detector pour représenter événements.
    Version simplifiée de Event (Story 7.1) avec seulement champs nécessaires.
    """

    id: str = Field(..., description="UUID événement (string)")
    title: str = Field(..., description="Titre événement")
    casquette: Casquette = Field(..., description="Casquette (médecin/enseignant/chercheur)")
    start_datetime: datetime = Field(..., description="Début événement")
    end_datetime: datetime = Field(..., description="Fin événement")
    status: EventStatus = Field(default=EventStatus.CONFIRMED, description="Statut événement")


class CalendarConflict(BaseModel):
    """
    Conflit entre 2 événements calendrier (AC4).

    Conflit = 2 événements chevauchent temporellement avec casquettes différentes.
    """

    event1: CalendarEvent = Field(..., description="Premier événement en conflit")
    event2: CalendarEvent = Field(..., description="Second événement en conflit")
    overlap_minutes: int = Field(..., gt=0, description="Durée chevauchement en minutes")
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp détection conflit",
    )


class ConflictResolution(BaseModel):
    """
    Action de résolution conflit (AC6).

    Utilisé par callbacks Telegram pour résoudre conflits.
    """

    action: ResolutionAction = Field(..., description="Action: cancel, move, ignore")
    event_id: str = Field(..., description="UUID événement concerné (string)")
    new_datetime: Optional[datetime] = Field(None, description="Nouvelle date/heure si action=move")
    reason: Optional[str] = Field(None, description="Raison résolution (optionnel)")

    @model_validator(mode="after")
    def move_requires_new_datetime(self) -> "ConflictResolution":
        if self.action == ResolutionAction.MOVE and self.new_datetime is None:
            raise ValueError("new_datetime est requis quand action=move")
        return self
