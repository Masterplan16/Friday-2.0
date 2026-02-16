"""
Check Thesis Reminders - Story 4.1 Task 6.3

Check relances thésards (priorité LOW).

Requête : knowledge.entities type=STUDENT WHERE last_contact < NOW() - INTERVAL '14 days'

Trust level : auto (notification seule).
"""

import asyncpg
import structlog

from agents.src.middleware.trust import friday_action
from agents.src.core.heartbeat_models import CheckResult

logger = structlog.get_logger(__name__)


@friday_action(module="heartbeat", action="check_thesis_reminders", trust_default="auto")
async def check_thesis_reminders(db_pool: asyncpg.Pool) -> CheckResult:
    """
    Check relances thésards sans contact depuis 14j (AC3, Task 6.3).

    Priority: LOW
    Trust: auto (notification seule)

    Returns:
        CheckResult avec notify=True si étudiants à relancer trouvés
    """
    try:
        async with db_pool.acquire() as conn:
            # Query étudiants sans contact depuis 14j
            students = await conn.fetch(
                """
                SELECT
                    entity_id,
                    name,
                    metadata->>'last_contact' as last_contact,
                    metadata->>'thesis_subject' as thesis_subject
                FROM knowledge.entities
                WHERE entity_type = 'STUDENT'
                  AND (metadata->>'last_contact')::date < NOW() - INTERVAL '14 days'
                ORDER BY (metadata->>'last_contact')::date ASC
                """
            )

        if not students:
            # Silence = bon comportement (AC4)
            return CheckResult(notify=False)

        # Formater message avec détails
        message = f"🎓 <b>{len(students)} thésard(s) à relancer</b> (sans contact depuis 14j)\n\n"

        for student in students[:3]:  # Max 3 pour concision
            name = student["name"]
            last_contact = student["last_contact"] or "Inconnu"
            thesis = student["thesis_subject"] or "Sujet inconnu"

            message += f"• {name}: {thesis[:40]}... (dernier contact: {last_contact})\n"

        if len(students) > 3:
            message += f"\n... et {len(students) - 3} autre(s)"

        logger.info(
            "Thesis reminders detected",
            count=len(students)
        )

        return CheckResult(
            notify=True,
            message=message,
            action="view_thesis_reminders",
            payload={
                "check_id": "check_thesis_reminders",
                "count": len(students),
                "student_ids": [s["entity_id"] for s in students]
            }
        )

    except Exception as e:
        logger.error("check_thesis_reminders failed", error=str(e))
        return CheckResult(
            notify=False,
            error=f"Failed to check thesis reminders: {str(e)}"
        )
