"""
Check Urgent Emails - Story 4.1 Task 6.1

Check emails urgents non lus (priorité HIGH).

Requête : ingestion.emails WHERE priority='urgent' AND read=false

Trust level : auto (notification seule, pas d'action).
"""

import asyncpg
import structlog
from agents.src.core.heartbeat_models import CheckResult
from agents.src.middleware.trust import friday_action

logger = structlog.get_logger(__name__)


@friday_action(module="heartbeat", action="check_urgent_emails", trust_default="auto")
async def check_urgent_emails(db_pool: asyncpg.Pool, **kwargs) -> CheckResult:
    """
    Check emails urgents non lus (AC3, Task 6.1).

    Priority: HIGH
    Trust: auto (notification seule)

    Returns:
        CheckResult avec notify=True si emails urgents trouvés
    """
    try:
        async with db_pool.acquire() as conn:
            # Query emails urgents non lus
            urgent_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM ingestion.emails
                WHERE priority = 'urgent'
                  AND read = false
                """
            )

            # Query détails pour message
            urgent_emails = await conn.fetch(
                """
                SELECT sender, subject
                FROM ingestion.emails
                WHERE priority = 'urgent'
                  AND read = false
                ORDER BY received_at DESC
                LIMIT 3
                """
            )

        if urgent_count == 0:
            # Silence = bon comportement (AC4)
            return CheckResult(notify=False)

        # Formater message avec détails
        message = f"📬 <b>{urgent_count} email(s) urgent(s) non lu(s)</b>\n\n"

        for email in urgent_emails:
            sender = email["sender"]
            subject = email["subject"][:50]  # Tronquer
            message += f"• {sender}: {subject}...\n"

        if urgent_count > 3:
            message += f"\n... et {urgent_count - 3} autre(s)"

        logger.info("Urgent emails detected", count=urgent_count)

        return CheckResult(
            notify=True,
            message=message,
            action="view_urgent_emails",
            payload={"check_id": "check_urgent_emails", "count": urgent_count},
        )

    except Exception as e:
        logger.error("check_urgent_emails failed", error=str(e))
        return CheckResult(notify=False, error=f"Failed to check urgent emails: {str(e)}")
