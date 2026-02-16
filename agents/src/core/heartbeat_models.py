"""
Heartbeat Models - Story 4.1 Heartbeat Engine Core

Story 7.3 Task 7: Créé en avance pour check calendar_conflicts (CheckResult, CheckPriority)
Story 4.1: Implémentation complète Heartbeat Engine (HeartbeatContext, Check)
"""

from datetime import datetime
from typing import Optional, Dict, Any, Callable, Awaitable
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

    notify: bool = Field(..., description="Si True, Heartbeat envoie notification Telegram")

    message: str = Field(default="", description="Message formaté pour Telegram (HTML autorisé)")

    action: Optional[str] = Field(
        None, description="Action suggérée (ex: 'view_conflicts', 'open_agenda')"
    )

    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Données additionnelles (ex: liste conflits, IDs événements)",
    )

    error: Optional[str] = Field(None, description="Message d'erreur si check échoué")

    class Config:
        json_schema_extra = {
            "example": {
                "notify": True,
                "message": "⚠️ 2 conflits calendrier détectés demain",
                "action": "view_conflicts",
                "payload": {"conflict_ids": ["uuid1", "uuid2"], "date": "2026-02-18"},
            }
        }


class CheckPriority:
    """
    Priorités check Heartbeat (Story 4.1)

    - CRITICAL: TOUJOURS exécuté (même quiet hours) - pannes critiques, garanties <7j
    - HIGH: Toujours exécuté (emails urgents, pannes)
    - MEDIUM: Exécuté si pertinent selon contexte (conflits calendrier, cotisations proches échéance)
    - LOW: Exécuté si temps disponible (stats générales, veille technologique)

    Story 7.3: calendar_conflicts = MEDIUM priority
    Story 3.4: warranty_expiry CRITICAL for <7 days
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ============================================================================
# Story 4.1: Heartbeat Context Model (AC2, Task 3.3)
# ============================================================================


class HeartbeatContext(BaseModel):
    """
    Contexte complet pour LLM Décideur Heartbeat (AC2).

    Fournit toutes les informations nécessaires pour décider intelligemment
    quels checks exécuter selon le contexte actuel.

    Attributes:
        current_time: Timestamp UTC actuel
        day_of_week: Jour semaine (Monday, Tuesday, ...)
        is_weekend: True si samedi/dimanche
        is_quiet_hours: True si 22h-8h (skip checks non-CRITICAL)
        current_casquette: Casquette active via Story 7.3 ContextManager
        next_calendar_event: Prochain événement calendrier (si <24h)
        last_activity_mainteneur: Timestamp dernière activité Mainteneur
    """

    current_time: datetime = Field(..., description="Timestamp UTC actuel")

    day_of_week: str = Field(..., description="Jour semaine (Monday, Tuesday, Wednesday, ...)")

    is_weekend: bool = Field(..., description="True si samedi/dimanche")

    is_quiet_hours: bool = Field(..., description="True si 22h-8h (skip checks non-CRITICAL)")

    current_casquette: Optional[str] = Field(
        None, description="Casquette active (medecin/enseignant/chercheur/personnel) via Story 7.3"
    )

    next_calendar_event: Optional[Dict[str, Any]] = Field(
        None, description="Prochain événement calendrier dans <24h (title, start_time, casquette)"
    )

    last_activity_mainteneur: Optional[datetime] = Field(
        None, description="Timestamp dernière activité Mainteneur (email lu, commande Telegram)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "current_time": "2026-02-17T14:30:00Z",
                "day_of_week": "Monday",
                "is_weekend": False,
                "is_quiet_hours": False,
                "current_casquette": "medecin",
                "next_calendar_event": {
                    "title": "Consultation M. Dupont",
                    "start_time": "2026-02-17T15:00:00Z",
                    "casquette": "medecin",
                },
                "last_activity_mainteneur": "2026-02-17T14:15:00Z",
            }
        }


# ============================================================================
# Story 4.1: Check Model (AC3, Task 2)
# ============================================================================


class Check(BaseModel):
    """
    Modèle d'un check Heartbeat enregistré dans CheckRegistry (AC3).

    Attributes:
        check_id: Identifiant unique check (ex: "check_urgent_emails")
        priority: Priorité check (CRITICAL/HIGH/MEDIUM/LOW)
        description: Description check pour LLM décideur
        execute_fn: Fonction async à exécuter (retourne CheckResult)
    """

    check_id: str = Field(..., description="Identifiant unique check")

    priority: str = Field(..., description="Priorité check (critical/high/medium/low)")

    description: str = Field(..., description="Description check pour LLM décideur")

    # Note: execute_fn ne peut pas être sérialisé JSON (fonction)
    # On le stocke comme attribut Python mais pas dans model Pydantic
    class Config:
        # Permettre attributs non-Pydantic
        arbitrary_types_allowed = True

    def __init__(self, **data):
        """
        Init avec support execute_fn (Callable).

        execute_fn doit être signature: async def(db_pool) -> CheckResult
        """
        # Extract execute_fn avant validation Pydantic
        execute_fn = data.pop("execute_fn", None)
        super().__init__(**data)

        # Stocker execute_fn comme attribut instance
        self._execute_fn: Optional[Callable[..., Awaitable[CheckResult]]] = execute_fn

    async def execute(self, *args, **kwargs) -> CheckResult:
        """
        Exécute le check avec les arguments fournis.

        Returns:
            CheckResult avec notify/message/action/payload
        """
        if not self._execute_fn:
            return CheckResult(notify=False, error=f"Check {self.check_id} has no execute_fn")

        return await self._execute_fn(*args, **kwargs)
