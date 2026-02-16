"""
Check Executor - Story 4.1 Task 5

Exécute les checks Heartbeat avec isolation et circuit breaker.

Features:
    - Isolation : 1 check crash n'arrête pas les autres
    - Circuit breaker : 3 échecs consécutifs → disable 1h + alerte System
    - Intégration @friday_action : chaque check génère receipt

Usage:
    executor = CheckExecutor(db_pool, redis_client, check_registry)
    result = await executor.execute_check("check_urgent_emails")
"""

import asyncpg
import structlog
from redis.asyncio import Redis

from agents.src.core.check_registry import CheckRegistry
from agents.src.core.heartbeat_models import CheckResult

logger = structlog.get_logger(__name__)


class CheckExecutor:
    """
    Exécuteur de checks Heartbeat avec isolation et circuit breaker (AC6, Task 5).
    """

    # Circuit breaker config
    CIRCUIT_BREAKER_THRESHOLD = 3  # 3 échecs consécutifs
    CIRCUIT_BREAKER_TIMEOUT = 3600  # 1 heure

    def __init__(self, db_pool: asyncpg.Pool, redis_client: Redis, check_registry: CheckRegistry):
        """
        Initialize Check Executor.

        Args:
            db_pool: Pool PostgreSQL (passé aux checks)
            redis_client: Redis client pour circuit breaker
            check_registry: CheckRegistry singleton
        """
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.check_registry = check_registry

        logger.info("CheckExecutor initialized")

    async def execute_check(self, check_id: str) -> CheckResult:
        """
        Exécute un check par son ID (Task 5.2).

        Features:
            - Isolation : try/except autour du check (Task 5.3)
            - Circuit breaker : vérifie si check disabled (Task 5.4)
            - Intégration @friday_action : génère receipt (Task 5.5)

        Args:
            check_id: Identifiant check à exécuter

        Returns:
            CheckResult avec notify/message/error
        """
        # Vérifier si check existe
        check = self.check_registry.get_check(check_id)
        if check is None:
            logger.error("Check not found", check_id=check_id)
            return CheckResult(notify=False, error=f"Check '{check_id}' not found in registry")

        # Vérifier circuit breaker (Task 5.4)
        circuit_breaker_key = f"check:disabled:{check_id}"
        is_disabled = await self.redis_client.get(circuit_breaker_key)

        if is_disabled:
            logger.warning("Check disabled by circuit breaker", check_id=check_id)
            return CheckResult(
                notify=False, error=f"Check '{check_id}' disabled by circuit breaker"
            )

        # Exécuter check avec isolation (Task 5.3)
        try:
            logger.debug("Executing check", check_id=check_id, priority=check.priority)

            # Appeler fonction check (passe db_pool)
            # Note: Les checks Day 1 (Task 6) utilisent @friday_action pour
            # générer des receipts dans core.action_receipts. Le décorateur
            # est appliqué sur la fonction check elle-même, pas ici.
            result: CheckResult = await check.execute(self.db_pool)

            # Succès → reset compteur failures
            failures_key = f"check:failures:{check_id}"
            await self.redis_client.delete(failures_key)

            logger.info("Check executed successfully", check_id=check_id, notify=result.notify)

            return result

        except Exception as e:
            # Isolation : log error mais continue (Task 5.3)
            logger.error(
                "Check execution failed",
                check_id=check_id,
                error=str(e),
                error_type=type(e).__name__,
            )

            # Incrémenter compteur failures (Task 5.4)
            await self._increment_failures(check_id)

            # Retourner CheckResult avec erreur
            return CheckResult(notify=False, error=f"Check execution failed: {str(e)}")

    async def _increment_failures(self, check_id: str) -> None:
        """
        Incrémente compteur échecs + ouvre circuit breaker si seuil atteint (Task 5.4).

        Args:
            check_id: Identifiant check
        """
        failures_key = f"check:failures:{check_id}"
        disabled_key = f"check:disabled:{check_id}"

        # Incrémenter compteur
        failures = await self.redis_client.incr(failures_key)

        # Expiration courte pour reset si succès
        await self.redis_client.expire(failures_key, 300)  # 5 min

        if failures >= self.CIRCUIT_BREAKER_THRESHOLD:
            # Ouvrir circuit breaker : disable check 1h
            await self.redis_client.setex(disabled_key, self.CIRCUIT_BREAKER_TIMEOUT, "1")

            logger.error(
                "Check circuit breaker opened",
                check_id=check_id,
                failures=failures,
                timeout_seconds=self.CIRCUIT_BREAKER_TIMEOUT,
            )

            # Envoyer alerte System (Task 5.4)
            await send_alert_system(f"⚠️ Check '{check_id}' disabled for 1h ({failures} failures)")


# ============================================================================
# Helper Functions
# ============================================================================


async def send_alert_system(message: str) -> None:
    """
    Envoie alerte Telegram Topic System & Alerts (Task 7).

    Args:
        message: Message alerte
    """
    from agents.src.core.telegram_helper import send_to_system_alerts

    # Envoyer alerte au topic System
    sent = await send_to_system_alerts(message=message, parse_mode="HTML")

    if sent:
        logger.info("System alert sent", alert_preview=message[:50])
    else:
        logger.warning("System alert not sent (bot unavailable)", alert=message)
