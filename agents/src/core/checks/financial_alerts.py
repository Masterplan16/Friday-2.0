"""
Check Financial Alerts - Story 4.1 Task 6.2

Check échéances cotisations <7j (priorité MEDIUM).

Requête : knowledge.entities type=COTISATION WHERE due_date < NOW() + INTERVAL '7 days'

Trust level : auto (notification seule).
"""

import asyncpg
import structlog

from agents.src.middleware.trust import friday_action
from agents.src.core.heartbeat_models import CheckResult

logger = structlog.get_logger(__name__)


@friday_action(module="heartbeat", action="check_financial_alerts", trust_default="auto")
async def check_financial_alerts(db_pool: asyncpg.Pool) -> CheckResult:
    """
    Check échéances financières proches (AC3, Task 6.2).

    Priority: MEDIUM
    Trust: auto (notification seule)

    Returns:
        CheckResult avec notify=True si échéances <7j trouvées
    """
    try:
        async with db_pool.acquire() as conn:
            # Query cotisations échéance <7j
            alerts = await conn.fetch(
                """
                SELECT
                    entity_id,
                    name,
                    metadata->>'due_date' as due_date,
                    metadata->>'amount' as amount,
                    metadata->>'account_type' as account_type
                FROM knowledge.entities
                WHERE entity_type = 'COTISATION'
                  AND (metadata->>'due_date')::date < NOW() + INTERVAL '7 days'
                  AND (metadata->>'due_date')::date >= NOW()
                ORDER BY (metadata->>'due_date')::date ASC
                """
            )

        if not alerts:
            # Silence = bon comportement (AC4)
            return CheckResult(notify=False)

        # Formater message avec détails
        message = f"💰 <b>{len(alerts)} échéance(s) financière(s) &lt;7j</b>\n\n"

        for alert in alerts[:3]:  # Max 3 pour concision
            name = alert["name"]
            due_date = alert["due_date"]
            amount = alert["amount"] or "?"
            account = alert["account_type"] or "Unknown"

            message += f"• {name} ({account}): {amount} € - échéance {due_date}\n"

        if len(alerts) > 3:
            message += f"\n... et {len(alerts) - 3} autre(s)"

        logger.info(
            "Financial alerts detected",
            count=len(alerts)
        )

        return CheckResult(
            notify=True,
            message=message,
            action="view_financial_alerts",
            payload={
                "check_id": "check_financial_alerts",
                "count": len(alerts),
                "alert_ids": [a["entity_id"] for a in alerts]
            }
        )

    except Exception as e:
        logger.error("check_financial_alerts failed", error=str(e))
        return CheckResult(
            notify=False,
            error=f"Failed to check financial alerts: {str(e)}"
        )
