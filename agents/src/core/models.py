"""
Pydantic Models - Core Modules

Story 7.3: Multi-casquettes & Conflits Calendrier
Models:
- UserContext: Contexte casquette actuel
- ContextSource: Enum source détermination contexte
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Enums
# ============================================================================

class ContextSource(str, Enum):
    """Source de détermination du contexte casquette (AC1)."""
    MANUAL = "manual"  # Commande Telegram /casquette <casquette>
    EVENT = "event"  # Événement en cours (NOW() entre start/end)
    TIME = "time"  # Heuristique heure de la journée
    LAST_EVENT = "last_event"  # Dernier événement passé
    DEFAULT = "default"  # Aucune règle applicable → NULL


class Casquette(str, Enum):
    """Casquettes professionnelles du Mainteneur."""
    MEDECIN = "medecin"
    ENSEIGNANT = "enseignant"
    CHERCHEUR = "chercheur"
    PERSONNEL = "personnel"


class ConflictStatus(str, Enum):
    """Statut conflit calendrier (AC4/AC6)."""
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"


# ============================================================================
# Models
# ============================================================================

class UserContext(BaseModel):
    """
    Contexte casquette actuel du Mainteneur (AC1).

    Le contexte influence tous les modules (email, événements, briefing).
    Détermination automatique selon 5 règles prioritaires.
    """
    casquette: Optional[Casquette] = Field(
        None,
        description="Casquette active: medecin, enseignant, chercheur, ou None (auto-detect)"
    )
    source: ContextSource = Field(
        ...,
        description="Source de détermination du contexte (MANUAL > EVENT > TIME > LAST_EVENT > DEFAULT)"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp dernière mise à jour contexte"
    )
    updated_by: Literal["system", "manual"] = Field(
        "system",
        description="Source du changement: 'system' (auto-detect) ou 'manual' (commande Telegram)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "casquette": "medecin",
                "source": "event",
                "updated_at": "2026-02-17T14:30:00Z",
                "updated_by": "system"
            }
        }
    )


class OngoingEvent(BaseModel):
    """
    Événement en cours pour détermination contexte.

    Utilisé par ContextManager._get_ongoing_event()
    """
    id: str = Field(..., description="UUID événement")
    casquette: Casquette = Field(..., description="Casquette de l'événement")
    title: str = Field(..., description="Titre événement")
    start_datetime: datetime = Field(..., description="Début événement")
    end_datetime: datetime = Field(..., description="Fin événement")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "casquette": "medecin",
                "title": "Consultation Dr Dupont",
                "start_datetime": "2026-02-17T14:00:00Z",
                "end_datetime": "2026-02-17T15:00:00Z"
            }
        }
    )


# ============================================================================
# Constants
# ============================================================================

# Mapping heures → casquettes (heuristique AC1)
TIME_BASED_CASQUETTE_MAPPING = {
    (8, 12): Casquette.MEDECIN,  # 08:00-12:00 → consultations matin
    (14, 16): Casquette.ENSEIGNANT,  # 14:00-16:00 → cours après-midi
    (16, 18): Casquette.CHERCHEUR,  # 16:00-18:00 → recherche fin journée
}

# Émojis par casquette (affichage Telegram)
CASQUETTE_EMOJI_MAPPING = {
    Casquette.MEDECIN: "🩺",
    Casquette.ENSEIGNANT: "🎓",
    Casquette.CHERCHEUR: "🔬",
    Casquette.PERSONNEL: "🏠",
}

# Labels français par casquette
CASQUETTE_LABEL_MAPPING = {
    Casquette.MEDECIN: "Médecin",
    Casquette.ENSEIGNANT: "Enseignant",
    Casquette.CHERCHEUR: "Chercheur",
    Casquette.PERSONNEL: "Personnel",
}
