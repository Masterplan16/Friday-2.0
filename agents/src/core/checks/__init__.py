"""
Checks Heartbeat Day 1 - Story 4.1 Task 6

Checks Day 1 enregistrés dans CheckRegistry :
    - check_urgent_emails (HIGH) : Emails urgents non lus
    - check_financial_alerts (MEDIUM) : Échéances cotisations <7j
    - check_thesis_reminders (LOW) : Relances thésards
    - check_calendar_conflicts (MEDIUM) : Conflits calendrier 7j (Story 7.3)
    - check_warranty_expiry (CRITICAL <7j, HIGH <30j) : Garanties expirant (Story 3.4)

Usage:
    from agents.src.core.checks import register_all_checks

    # Enregistrer tous les checks Day 1
    register_all_checks(check_registry)
"""

from agents.src.core.check_registry import CheckRegistry
from agents.src.core.heartbeat_models import CheckPriority

from .urgent_emails import check_urgent_emails
from .financial_alerts import check_financial_alerts
from .thesis_reminders import check_thesis_reminders


def register_all_checks(registry: CheckRegistry) -> None:
    """
    Enregistre tous les checks Day 1 dans le registry.

    Args:
        registry: CheckRegistry singleton
    """
    # Check 1: Emails urgents non lus (HIGH)
    registry.register_check(
        check_id="check_urgent_emails",
        priority=CheckPriority.HIGH,
        description="Emails urgents non lus",
        execute_fn=check_urgent_emails,
    )

    # Check 2: Alertes financières (MEDIUM)
    registry.register_check(
        check_id="check_financial_alerts",
        priority=CheckPriority.MEDIUM,
        description="Échéances cotisations <7j",
        execute_fn=check_financial_alerts,
    )

    # Check 3: Rappels thèses (LOW)
    registry.register_check(
        check_id="check_thesis_reminders",
        priority=CheckPriority.LOW,
        description="Relances thésards",
        execute_fn=check_thesis_reminders,
    )

    # TODO Task 6.4: Intégrer check_calendar_conflicts (Story 7.3)
    # TODO Task 6.5: Intégrer check_warranty_expiry (Story 3.4)
