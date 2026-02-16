"""
Pydantic models pour detection evenements

Story 7.1 AC1-AC7: Models Event, EventDetectionResult
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime
from enum import Enum


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


class Casquette(str, Enum):
    """
    Casquettes multi-roles Mainteneur (FR42)
    """
    MEDECIN = "medecin"
    ENSEIGNANT = "enseignant"
    CHERCHEUR = "chercheur"
    PERSONNEL = "personnel"


class EventStatus(str, Enum):
    """
    Status evenement (AC2)
    """
    PROPOSED = "proposed"      # Detecte, en attente validation
    CONFIRMED = "confirmed"    # Valide par Mainteneur
    CANCELLED = "cancelled"    # Rejete/annule


class Event(BaseModel):
    """
    Model Pydantic Event extrait depuis email

    Story 7.1 AC1: Structure JSON evenement detecte par Claude
    """
    title: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Titre evenement (max 500 chars)"
    )

    start_datetime: datetime = Field(
        ...,
        description="Date/heure debut (ISO 8601, AC4: dates relatives converties en absolues)"
    )

    end_datetime: Optional[datetime] = Field(
        None,
        description="Date/heure fin (optionnel, infere si absent)"
    )

    location: Optional[str] = Field(
        None,
        max_length=500,
        description="Lieu evenement (AC6: NER extraction)"
    )

    participants: List[str] = Field(
        default_factory=list,
        description="Liste participants (AC6: NER extraction, anonymises Presidio)"
    )

    event_type: EventType = Field(
        EventType.OTHER,
        description="Type evenement (medical, meeting, deadline, conference, personal)"
    )

    casquette: Casquette = Field(
        ...,
        description="Classification multi-casquettes (AC5: medecin|enseignant|chercheur|personnel)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confiance extraction LLM (0.0-1.0, seuil AC1: >=0.75)"
    )

    context: Optional[str] = Field(
        None,
        max_length=1000,
        description="Contexte extraction (snippet email source)"
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
        default_factory=list,
        description="Liste evenements detectes (peut etre vide si aucun)"
    )

    confidence_overall: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confiance globale extraction (min de tous events.confidence)"
    )

    email_id: Optional[str] = Field(
        None,
        description="UUID email source (ingestion.emails_raw.id)"
    )

    processing_time_ms: Optional[int] = Field(
        None,
        ge=0,
        description="Temps traitement LLM en millisecondes (monitoring)"
    )

    model_used: str = Field(
        default="claude-sonnet-4-5-20250929",
        description="Model LLM utilise (Decision D17)"
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


class EventExtractionError(Exception):
    """
    Exception levee lors d'erreur extraction evenement

    Usage: erreurs parsing JSON Claude, RateLimitError retry epuise, circuit breaker
    """
    pass


class EventValidationError(Exception):
    """
    Exception levee lors d'erreur validation Pydantic Event

    Usage: start_datetime invalide, confidence hors range, casquette invalide
    """
    pass
