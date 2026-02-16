"""
Check Registry - Story 4.1 Task 2

Registry singleton pour enregistrer et récupérer les checks Heartbeat.

Pattern singleton global permettant à tous les modules d'enregistrer
leurs checks dans un registry centralisé.

Usage:
    from agents.src.core.check_registry import CheckRegistry, get_check_registry
    from agents.src.core.heartbeat_models import Check, CheckResult, CheckPriority

    # Enregistrer un check
    registry = get_check_registry()
    registry.register_check(
        check_id="check_urgent_emails",
        priority=CheckPriority.HIGH,
        description="Emails urgents non lus",
        execute_fn=check_urgent_emails_fn
    )

    # Récupérer checks par priorité
    high_checks = registry.get_checks_by_priority(CheckPriority.HIGH)
"""

from typing import List, Optional

import structlog
from agents.src.core.heartbeat_models import Check

logger = structlog.get_logger(__name__)


class CheckRegistry:
    """
    Registry singleton pour checks Heartbeat (AC3, Task 2).

    Permet à tous les modules d'enregistrer leurs checks dans un
    registry global accessible partout dans l'application.
    """

    _instance: Optional["CheckRegistry"] = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._checks: dict[str, Check] = {}
            cls._instance._initialized = True
            logger.info("CheckRegistry singleton initialized")
        return cls._instance

    def register_check(self, check_id: str, priority: str, description: str, execute_fn) -> None:
        """
        Enregistre un check dans le registry (Task 2.2).

        Args:
            check_id: Identifiant unique check (ex: "check_urgent_emails")
            priority: Priorité check (CheckPriority.CRITICAL/HIGH/MEDIUM/LOW)
            description: Description check pour LLM décideur
            execute_fn: Fonction async à exécuter (signature: async def(db_pool) -> CheckResult)

        Raises:
            ValueError: Si check_id déjà enregistré
        """
        if check_id in self._checks:
            raise ValueError(f"Check '{check_id}' is already registered")

        check = Check(
            check_id=check_id, priority=priority, description=description, execute_fn=execute_fn
        )

        self._checks[check_id] = check

        logger.info(
            "Check registered", check_id=check_id, priority=priority, total_checks=len(self._checks)
        )

    def get_check(self, check_id: str) -> Optional[Check]:
        """
        Récupère un check par son ID.

        Args:
            check_id: Identifiant check

        Returns:
            Check si trouvé, None sinon
        """
        return self._checks.get(check_id)

    def get_checks_by_priority(self, priority: str) -> List[Check]:
        """
        Récupère tous les checks d'une priorité donnée (Task 2.3).

        Args:
            priority: Priorité check (CheckPriority.CRITICAL/HIGH/MEDIUM/LOW)

        Returns:
            Liste checks de cette priorité
        """
        return [check for check in self._checks.values() if check.priority == priority]

    def get_all_checks(self) -> List[Check]:
        """
        Récupère tous les checks enregistrés (Task 2.4).

        Returns:
            Liste de tous les checks
        """
        return list(self._checks.values())

    def clear(self) -> None:
        """
        Vide le registry (utile pour tests).

        WARNING: À utiliser UNIQUEMENT dans les tests !
        """
        self._checks.clear()
        logger.warning("CheckRegistry cleared")


# ============================================================================
# Helper Functions
# ============================================================================


def get_check_registry() -> CheckRegistry:
    """
    Retourne l'instance singleton du CheckRegistry.

    Returns:
        CheckRegistry singleton
    """
    return CheckRegistry()
