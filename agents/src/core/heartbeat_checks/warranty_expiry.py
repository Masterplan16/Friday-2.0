"""
Heartbeat Check - Expiration Garanties (Story 3.4 AC3)

Check quotidien expirations + notifications proactives.
Schedule: Daily 02:00 UTC (cron via nightly.py)

Alertes :
- 60 jours → Priority MEDIUM, message informatif
- 30 jours → Priority HIGH, message action recommandée
- 7 jours → Priority CRITICAL, notification push (ignore quiet hours)
- Expiré → Status 'expired' automatiquement

Anti-spam : warranty_alerts table (unique warranty_id + alert_type)
Quiet hours : 22h-8h (skip sauf CRITICAL <7 jours)
"""

import os
from datetime import datetime, time
from typing import Any, Dict, List, Optional

import asyncpg
import structlog

from agents.src.agents.archiviste.warranty_db import (
    check_alert_sent,
    get_expiring_warranties,
    mark_warranty_expired,
    record_alert_sent,
)
from agents.src.core.heartbeat_models import CheckPriority, CheckResult

logger = structlog.get_logger(__name__)


async def check_warranty_expiry(
    context: Dict[str, Any],
    db_pool: Optional[asyncpg.Pool] = None,
) -> CheckResult:
    """
    Heartbeat check : Alertes expiration garanties (AC3).

    Schedule: Daily 02:00 UTC (cron)
    Priority: MEDIUM/HIGH/CRITICAL selon days_remaining
    Quiet hours: 22h-8h (skip sauf CRITICAL <7 jours)

    Args:
        context: Contexte Heartbeat (hour, day, quiet_hours)
        db_pool: Pool PostgreSQL (optionnel, créé si None)

    Returns:
        CheckResult avec notify=True si alertes envoyées
    """
    try:
        # 1. Créer pool si nécessaire
        pool_created = False
        if db_pool is None:
            database_url = os.getenv("DATABASE_URL")
            if not database_url:
                logger.error("DATABASE_URL envvar manquante")
                return CheckResult(
                    notify=False,
                    error="DATABASE_URL envvar manquante",
                )
            db_pool = await asyncpg.create_pool(database_url)
            pool_created = True

        try:
            # 2. Récupérer garanties expirant dans 60 jours
            warranties_60d = await get_expiring_warranties(db_pool, days_threshold=60)

            # 3. Identifier expirées (days_remaining <= 0)
            expired = [w for w in warranties_60d if w.get("days_remaining", 999) <= 0]
            warranties_7d = [w for w in warranties_60d if 0 < w.get("days_remaining", 999) <= 7]
            warranties_30d = [w for w in warranties_60d if 7 < w.get("days_remaining", 999) <= 30]
            warranties_60d_only = [
                w for w in warranties_60d if 30 < w.get("days_remaining", 999) <= 60
            ]

            # 4. Marquer expirées
            for w in expired:
                warranty_id = str(w["id"])
                await mark_warranty_expired(db_pool, warranty_id)
                if not await check_alert_sent(db_pool, warranty_id, "expired"):
                    await record_alert_sent(db_pool, warranty_id, "expired")

            # 5. Envoyer alertes (vérifier anti-spam + quiet hours)
            alerts_sent = []
            is_quiet_hours = _is_quiet_hours(context)

            # CRITICAL : 7 jours (ignore quiet hours)
            for w in warranties_7d:
                warranty_id = str(w["id"])
                if not await check_alert_sent(db_pool, warranty_id, "7_days"):
                    await record_alert_sent(db_pool, warranty_id, "7_days")
                    alerts_sent.append(
                        {
                            "item": w["item_name"],
                            "days": w["days_remaining"],
                            "priority": CheckPriority.CRITICAL,
                            "alert_type": "7_days",
                        }
                    )

            # HIGH : 30 jours (respect quiet hours)
            if not is_quiet_hours:
                for w in warranties_30d:
                    warranty_id = str(w["id"])
                    if not await check_alert_sent(db_pool, warranty_id, "30_days"):
                        await record_alert_sent(db_pool, warranty_id, "30_days")
                        alerts_sent.append(
                            {
                                "item": w["item_name"],
                                "days": w["days_remaining"],
                                "priority": CheckPriority.HIGH,
                                "alert_type": "30_days",
                            }
                        )

            # MEDIUM : 60 jours (respect quiet hours)
            if not is_quiet_hours:
                for w in warranties_60d_only:
                    warranty_id = str(w["id"])
                    if not await check_alert_sent(db_pool, warranty_id, "60_days"):
                        await record_alert_sent(db_pool, warranty_id, "60_days")
                        alerts_sent.append(
                            {
                                "item": w["item_name"],
                                "days": w["days_remaining"],
                                "priority": CheckPriority.MEDIUM,
                                "alert_type": "60_days",
                            }
                        )

            # 6. Construire message
            if not alerts_sent and not expired:
                logger.debug(
                    "heartbeat_warranty_check_ok",
                    total_warranties=len(warranties_60d),
                )
                return CheckResult(notify=False, message="")

            message = _build_alert_message(alerts_sent, expired)

            logger.info(
                "heartbeat_warranty_check_alerts",
                alerts_count=len(alerts_sent),
                expired_count=len(expired),
            )

            return CheckResult(
                notify=True,
                message=message,
                action="view_warranties",
                payload={
                    "alerts_sent": alerts_sent,
                    "expired_count": len(expired),
                },
            )

        finally:
            if pool_created and db_pool:
                await db_pool.close()

    except Exception as e:
        logger.error("heartbeat_warranty_check_error", error=str(e))
        return CheckResult(
            notify=False,
            error=f"Warranty check failed: {e}",
        )


def _is_quiet_hours(context: Dict[str, Any]) -> bool:
    """Check if current time is in quiet hours (22h-8h)."""
    hour = context.get("hour", datetime.now().hour)
    return hour >= 22 or hour < 8


def _build_alert_message(
    alerts: List[Dict[str, Any]],
    expired: List[Dict[str, Any]],
) -> str:
    """Build Telegram notification message for warranty alerts."""
    lines = []

    if expired:
        lines.append(f"📋 <b>{len(expired)} garantie(s) expirée(s)</b>")
        for w in expired[:5]:
            lines.append(f"  • {w.get('item_name', '?')} - expirée")
        lines.append("")

    # Group alerts by priority
    critical = [a for a in alerts if a["alert_type"] == "7_days"]
    high = [a for a in alerts if a["alert_type"] == "30_days"]
    medium = [a for a in alerts if a["alert_type"] == "60_days"]

    if critical:
        lines.append(f"🚨 <b>URGENT - {len(critical)} garantie(s) expirent dans &lt;7 jours</b>")
        for a in critical:
            lines.append(f"  • {a['item']} - dans {a['days']} jours")
        lines.append("")

    if high:
        lines.append(f"⚠️ <b>{len(high)} garantie(s) expirent dans &lt;30 jours</b>")
        for a in high:
            lines.append(f"  • {a['item']} - dans {a['days']} jours")
        lines.append("")

    if medium:
        lines.append(f"ℹ️ <b>{len(medium)} garantie(s) expirent dans &lt;60 jours</b>")
        for a in medium:
            lines.append(f"  • {a['item']} - dans {a['days']} jours")

    return "\n".join(lines) if lines else ""
