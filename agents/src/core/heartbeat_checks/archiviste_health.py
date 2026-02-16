"""
Heartbeat Check - Santé Pipeline Archiviste

Check périodique santé composants archiviste :
- Surya OCR responsive
- Watchdog observer actif (Story 3.5)
- Pipeline traitement documents fonctionnel

Priority: HIGH (alerte si pipeline bloqué >24h)
Quiet hours: Non (système critique)
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import asyncpg
import httpx
import structlog
from agents.src.core.heartbeat_models import CheckPriority, CheckResult
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


# ============================================================================
# CHECK FUNCTION
# ============================================================================


async def check_archiviste_health(
    context: Dict[str, Any],
    db_pool: Optional[asyncpg.Pool] = None,
    redis_client: Optional[Redis] = None,
) -> CheckResult:
    """
    Check Heartbeat : Santé pipeline archiviste

    Vérifie 3 composants critiques :
    1. Surya OCR responsive (simple health ping)
    2. Watchdog observer actif (Redis heartbeat)
    3. Pipeline documents fonctionnel (dernière action <24h)

    Args:
        context: Contexte Heartbeat (time, hour, etc.)
        db_pool: Pool PostgreSQL (optionnel, créé si None)
        redis_client: Redis client (optionnel, créé si None)

    Returns:
        CheckResult avec notify=True si anomalie détectée

    Epic 3 - Archiviste Health Monitoring
    """
    pool_created = False
    redis_created = False
    issues = []

    try:
        # 1. Vérifier Surya OCR responsive
        ocr_issue = await _check_surya_ocr()
        if ocr_issue:
            issues.append(ocr_issue)

        # 2. Vérifier Watchdog observer actif (Redis heartbeat)
        if redis_client is None:
            import os

            redis_url = os.getenv("REDIS_URL")
            if redis_url:
                redis_client = Redis.from_url(redis_url)
                redis_created = True

        if redis_client:
            watchdog_issue = await _check_watchdog_observer(redis_client)
            if watchdog_issue:
                issues.append(watchdog_issue)

        # 3. Vérifier pipeline documents fonctionnel (dernière action <24h)
        if db_pool is None:
            import os

            database_url = os.getenv("DATABASE_URL")
            if not database_url:
                logger.error("DATABASE_URL envvar manquante")
                return CheckResult(notify=False, error="DATABASE_URL envvar manquante")

            db_pool = await asyncpg.create_pool(database_url)
            pool_created = True

        pipeline_issue = await _check_pipeline_activity(db_pool)
        if pipeline_issue:
            issues.append(pipeline_issue)

        # 4. Formater résultat
        if not issues:
            logger.debug("heartbeat_check_archiviste_ok")
            return CheckResult(notify=False, message="")

        # Notifier si anomalies détectées
        logger.warning(
            "heartbeat_check_archiviste_issues_found", issue_count=len(issues), issues=issues
        )

        message = _format_health_notification(issues, context)

        return CheckResult(
            notify=True,
            message=message,
            action="check_archiviste",
            payload={"issues": issues, "severity": "high" if len(issues) >= 2 else "medium"},
        )

    except Exception as e:
        logger.error("heartbeat_check_archiviste_error", error=str(e), exc_info=True)
        return CheckResult(notify=False, error=str(e))
    finally:
        # Cleanup resources si créés localement
        if pool_created and db_pool:
            await db_pool.close()
        if redis_created and redis_client:
            await redis_client.close()


# ============================================================================
# HELPERS - Health Checks
# ============================================================================


async def _check_surya_ocr() -> Optional[str]:
    """
    Vérifie si Surya OCR responsive via simple health ping

    Returns:
        None si OK, message erreur sinon

    Story 3.1 - OCR renommage intelligent
    """
    import os

    surya_url = os.getenv("SURYA_OCR_URL", "http://localhost:8765")
    health_endpoint = f"{surya_url}/health"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(health_endpoint)

            if response.status_code == 200:
                logger.debug("surya_ocr_health_ok", url=surya_url)
                return None

            logger.warning(
                "surya_ocr_health_bad_status",
                url=surya_url,
                status_code=response.status_code,
            )
            return f"Surya OCR unhealthy (HTTP {response.status_code})"

    except httpx.TimeoutException:
        logger.warning("surya_ocr_health_timeout", url=surya_url)
        return "Surya OCR timeout (>5s)"
    except Exception as e:
        logger.warning("surya_ocr_health_error", url=surya_url, error=str(e))
        return f"Surya OCR inaccessible ({str(e)[:50]})"


async def _check_watchdog_observer(redis_client: Redis) -> Optional[str]:
    """
    Vérifie si Watchdog observer actif via Redis heartbeat

    Le watchdog observer publie un heartbeat toutes les 60s dans Redis
    key: watchdog:heartbeat, TTL: 120s

    Returns:
        None si OK, message erreur sinon

    Story 3.5 - Détection nouveaux fichiers
    """
    try:
        heartbeat_key = "watchdog:heartbeat"
        last_heartbeat = await redis_client.get(heartbeat_key)

        if last_heartbeat:
            logger.debug("watchdog_observer_active")
            return None

        # Pas de heartbeat détecté
        logger.warning("watchdog_observer_no_heartbeat")
        return "Watchdog observer inactif (pas de heartbeat Redis)"

    except Exception as e:
        logger.warning("watchdog_observer_check_error", error=str(e))
        return f"Watchdog observer check failed ({str(e)[:50]})"


async def _check_pipeline_activity(db_pool: asyncpg.Pool) -> Optional[str]:
    """
    Vérifie activité pipeline documents via dernière action archiviste

    Règle : Si zone transit non-vide ET aucun document traité depuis >24h
    → Alerte pipeline bloqué

    Returns:
        None si OK, message erreur sinon

    Epic 3 - Pipeline archiviste
    """
    try:
        # 1. Vérifier dernière action archiviste dans core.action_receipts
        async with db_pool.acquire() as conn:
            last_action = await conn.fetchrow(
                """
                SELECT created_at
                FROM core.action_receipts
                WHERE module = 'archiviste'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )

            if not last_action:
                logger.debug("archiviste_pipeline_no_history")
                return None  # Pas d'historique = système neuf, OK

            last_action_time = last_action["created_at"]
            time_since_last = datetime.now() - last_action_time

            # 2. Si dernière action <24h, pipeline OK
            if time_since_last < timedelta(hours=24):
                logger.debug(
                    "archiviste_pipeline_active",
                    last_action_hours_ago=time_since_last.total_seconds() / 3600,
                )
                return None

            # 3. Dernière action >24h : Vérifier si zone transit vide
            # (Si transit vide = pas de documents à traiter = OK)
            import os

            transit_path = os.getenv("TRANSIT_ATTACHMENTS_PATH", "/var/friday/transit/attachments")

            # Note : Cette vérification nécessite accès filesystem VPS
            # Day 1 : Skip filesystem check, alerte basée uniquement sur last_action >24h
            # TODO : Implémenter check filesystem transit via agent local ou SSH

            logger.warning(
                "archiviste_pipeline_inactive",
                last_action_hours_ago=time_since_last.total_seconds() / 3600,
            )

            hours_ago = int(time_since_last.total_seconds() / 3600)
            return f"Pipeline archiviste inactif (dernière action il y a {hours_ago}h)"

    except Exception as e:
        logger.warning("archiviste_pipeline_check_error", error=str(e))
        return f"Pipeline check failed ({str(e)[:50]})"


# ============================================================================
# HELPERS - Notification Formatting
# ============================================================================


def _format_health_notification(issues: list[str], context: Dict[str, Any]) -> str:
    """
    Formate message notification Telegram santé archiviste

    Format :
    🚨 Problèmes détectés pipeline archiviste

    ❌ Surya OCR unhealthy (HTTP 503)
    ❌ Watchdog observer inactif
    ❌ Pipeline inactif (dernière action 36h)

    Vérifiez services via /status

    Args:
        issues: Liste messages erreurs détectées
        context: Contexte Heartbeat

    Returns:
        Message HTML formaté pour Telegram
    """
    count = len(issues)

    lines = [
        f"🚨 <b>{count} problème{'s' if count > 1 else ''} détecté{'s' if count > 1 else ''} pipeline archiviste</b>",
        "",
    ]

    # Lister problèmes
    for issue in issues:
        lines.append(f"❌ {issue}")

    lines.append("")
    lines.append("<i>Vérifiez services via /status</i>")

    return "\n".join(lines)


# ============================================================================
# METADATA (pour enregistrement Heartbeat Engine)
# ============================================================================

CHECK_METADATA = {
    "name": "archiviste_health",
    "priority": CheckPriority.HIGH,
    "description": "Vérifie santé pipeline archiviste (OCR, Watchdog, activité)",
    "function": check_archiviste_health,
    "epic": "3",
    "phase": 2,  # Heartbeat Phase 2 (checks santé système)
}
