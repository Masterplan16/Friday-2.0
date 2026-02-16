"""
Heartbeat Models - Stub pour Story 4.1

Story 7.3 Task 7: Créé en avance pour check calendar_conflicts
Story 4.1: Implémentation complète Heartbeat Engine future
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class CheckResult(BaseModel):
    """
    Résultat d'un check heartbeat (Story 4.1)

    Le check retourne ce résultat pour indiquer :
    - notify: Si notification Telegram nécessaire
    - message: Message formaté pour Telegram (si notify=True)
    - action: Action suggérée (optionnel)
    - payload: Données additionnelles (optionnel)
    - error: Message d'erreur si check échoué (optionnel)

    Story 7.3 Task 7: Utilisé par check calendar_conflicts
    """
    notify: bool = Field(
        ...,
        description="Si True, Heartbeat envoie notification Telegram"
    )

    message: str = Field(
        default="",
        description="Message formaté pour Telegram (HTML autorisé)"
    )

    action: Optional[str] = Field(
        None,
        description="Action suggérée (ex: 'view_conflicts', 'open_agenda')"
    )

    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Données additionnelles (ex: liste conflits, IDs événements)"
    )

    error: Optional[str] = Field(
        None,
        description="Message d'erreur si check échoué"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "notify": True,
                "message": "⚠️ 2 conflits calendrier détectés demain",
                "action": "view_conflicts",
                "payload": {
                    "conflict_ids": ["uuid1", "uuid2"],
                    "date": "2026-02-18"
                }
            }
        }


class CheckPriority:
    """
    Priorités check Heartbeat (Story 4.1)

    - HIGH: Toujours exécuté (emails urgents, pannes critiques)
    - MEDIUM: Exécuté si pertinent selon contexte (conflits calendrier, cotisations proches échéance)
    - LOW: Exécuté si temps disponible (stats générales, veille technologique)

    Story 7.3: calendar_conflicts = MEDIUM priority
    Story 3.4: warranty_expiry CRITICAL for <7 days
    """
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
