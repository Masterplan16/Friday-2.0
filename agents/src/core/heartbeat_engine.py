"""
Heartbeat Engine - Story 4.1 Task 1

Moteur Heartbeat context-aware qui orchestre l'exécution intelligente
des checks périodiques via LLM décideur.

Architecture:
    1. Context Provider → récupère contexte actuel (casquette, calendrier, quiet hours)
    2. LLM Décideur → sélectionne checks pertinents selon contexte
    3. Check Executor → exécute checks sélectionnés avec isolation/circuit breaker
    4. Notifications → envoie résultats Telegram si notify=True

Modes:
    - daemon: Boucle infinie avec sleep interval (production)
    - one-shot: Cycle unique puis exit (cron n8n)

Usage:
    # Daemon mode (production)
    engine = HeartbeatEngine(db_pool, redis_client, context_provider, ...)
    await engine.run_heartbeat_cycle(mode="daemon", interval_minutes=30)

    # One-shot mode (n8n cron)
    result = await engine.run_heartbeat_cycle(mode="one-shot")
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
import structlog
from agents.src.core.check_registry import CheckRegistry
from agents.src.core.context_provider import ContextProvider
from agents.src.core.heartbeat_models import Check, CheckPriority, CheckResult, HeartbeatContext
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


class HeartbeatEngine:
    """
    Heartbeat Engine Core (AC1, Task 1).

    Orchestre l'exécution intelligente des checks périodiques selon contexte.
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        redis_client: Redis,
        context_provider: ContextProvider,
        check_registry: CheckRegistry,
        llm_decider,  # Type: LLMDecider (forward reference, créé Task 4)
        check_executor,  # Type: CheckExecutor (forward reference, créé Task 5)
    ):
        """
        Initialize Heartbeat Engine.

        Args:
            db_pool: Pool PostgreSQL pour metrics persistence
            redis_client: Redis client pour circuit breakers
            context_provider: ContextProvider (Task 3)
            check_registry: CheckRegistry singleton (Task 2)
            llm_decider: LLM Décideur pour sélection checks (Task 4)
            check_executor: Executor pour exécution checks (Task 5)
        """
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.context_provider = context_provider
        self.check_registry = check_registry
        self.llm_decider = llm_decider
        self.check_executor = check_executor

        logger.info("HeartbeatEngine initialized")

    async def run_heartbeat_cycle(
        self, mode: str = "one-shot", interval_minutes: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Exécute cycle(s) Heartbeat (Task 1.2).

        Args:
            mode: "one-shot" (1 cycle) ou "daemon" (boucle infinie)
            interval_minutes: Interval entre cycles (mode daemon uniquement)

        Returns:
            Dict avec status, checks_executed, checks_notified, etc.

        Raises:
            KeyboardInterrupt: Si daemon stoppé par signal
        """
        if mode == "one-shot":
            # Mode one-shot : exécute 1 cycle puis retourne
            return await self._execute_single_cycle()

        elif mode == "daemon":
            # Mode daemon : boucle infinie avec interval
            interval_minutes = interval_minutes or int(
                os.getenv("HEARTBEAT_INTERVAL_MINUTES", "30")
            )
            interval_seconds = interval_minutes * 60

            logger.info("Starting Heartbeat daemon", interval_minutes=interval_minutes)

            try:
                while True:
                    # Exécuter cycle
                    result = await self._execute_single_cycle()

                    logger.info(
                        "Heartbeat cycle completed",
                        status=result["status"],
                        checks_executed=result.get("checks_executed", 0),
                        checks_notified=result.get("checks_notified", 0),
                    )

                    # Attendre avant prochain cycle
                    await asyncio.sleep(interval_seconds)

            except KeyboardInterrupt:
                logger.info("Heartbeat daemon stopped by user")
                raise

        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'one-shot' or 'daemon'")

    async def _execute_single_cycle(self) -> Dict[str, Any]:
        """
        Exécute UN cycle Heartbeat complet (Task 1.2, AC1).

        Flow:
            1. Context Provider → HeartbeatContext
            2. Quiet hours check → CRITICAL only OU LLM décideur
            3. Check Executor → exécute checks sélectionnés
            4. Notifications → envoie résultats Telegram
            5. Metrics → log + save DB

        Returns:
            Dict avec status, checks_executed, checks_notified, duration_ms, etc.
        """
        cycle_start = datetime.now(timezone.utc)
        checks_executed = 0
        checks_notified = 0
        selected_check_ids: List[str] = []
        llm_reasoning = ""
        error_message: Optional[str] = None

        try:
            # 1. Récupérer contexte actuel
            context = await self.context_provider.get_current_context()

            logger.info(
                "Heartbeat cycle started",
                current_time=context.current_time.isoformat(),
                is_quiet_hours=context.is_quiet_hours,
                casquette=context.current_casquette,
            )

            # 2. Sélectionner checks à exécuter
            if context.is_quiet_hours:
                # Quiet hours (22h-8h) → CRITICAL checks seulement (AC1, Task 1.3)
                logger.info("Quiet hours detected, executing CRITICAL checks only")
                checks_to_run = self.check_registry.get_checks_by_priority(CheckPriority.CRITICAL)
                selected_check_ids = [check.check_id for check in checks_to_run]
                llm_reasoning = "Quiet hours: CRITICAL checks only"

            else:
                # Hors quiet hours → LLM décideur (AC2, Task 1.3)
                try:
                    decision = await self.llm_decider.decide_checks(
                        context=context, available_checks=self.check_registry.get_all_checks()
                    )
                    selected_check_ids = decision.get("checks_to_run", [])
                    llm_reasoning = decision.get("reasoning", "")

                    checks_to_run = [
                        self.check_registry.get_check(check_id)
                        for check_id in selected_check_ids
                        if self.check_registry.get_check(check_id) is not None
                    ]

                    logger.info(
                        "LLM decider selected checks",
                        checks_count=len(checks_to_run),
                        check_ids=selected_check_ids,
                    )

                except Exception as e:
                    # Fallback si LLM crash → HIGH checks (AC2)
                    logger.error("LLM decider failed, fallback to HIGH checks", error=str(e))
                    checks_to_run = self.check_registry.get_checks_by_priority(CheckPriority.HIGH)
                    selected_check_ids = [check.check_id for check in checks_to_run]
                    llm_reasoning = f"LLM fallback (error: {str(e)})"

            # 3. Exécuter checks sélectionnés (AC6, Task 5)
            for check in checks_to_run:
                try:
                    result: CheckResult = await self.check_executor.execute_check(
                        check_id=check.check_id
                    )

                    checks_executed += 1

                    # 4. Envoyer notification si nécessaire (AC5)
                    if result.notify:
                        await self._send_notification(result, context)
                        checks_notified += 1

                except Exception as e:
                    # Isolation : 1 check crash n'arrête pas les autres (AC6)
                    logger.error("Check execution failed", check_id=check.check_id, error=str(e))
                    continue

            # 5. Sauvegarder metrics (AC4, AC6, Task 8)
            cycle_duration_ms = int(
                (datetime.now(timezone.utc) - cycle_start).total_seconds() * 1000
            )

            await self._save_metrics(
                cycle_timestamp=cycle_start,
                checks_selected=selected_check_ids,
                checks_executed=checks_executed,
                checks_notified=checks_notified,
                llm_decision_reasoning=llm_reasoning,
                duration_ms=cycle_duration_ms,
                error=None,
            )

            logger.info(
                "Heartbeat cycle completed successfully",
                checks_executed=checks_executed,
                checks_notified=checks_notified,
                duration_ms=cycle_duration_ms,
            )

            return {
                "status": "success",
                "checks_executed": checks_executed,
                "checks_notified": checks_notified,
                "duration_ms": cycle_duration_ms,
                "selected_checks": selected_check_ids,
                "llm_reasoning": llm_reasoning,
            }

        except Exception as e:
            # Erreur critique cycle complet (AC6, Task 1.5)
            logger.error("Heartbeat cycle failed", error=str(e), error_type=type(e).__name__)

            error_message = str(e)

            # Sauvegarder metrics avec erreur
            cycle_duration_ms = int(
                (datetime.now(timezone.utc) - cycle_start).total_seconds() * 1000
            )

            await self._save_metrics(
                cycle_timestamp=cycle_start,
                checks_selected=selected_check_ids,
                checks_executed=checks_executed,
                checks_notified=checks_notified,
                llm_decision_reasoning=llm_reasoning,
                duration_ms=cycle_duration_ms,
                error=error_message,
            )

            # Envoyer alerte System (AC6)
            await self._send_alert_system(f"⚠️ Heartbeat cycle failed: {error_message}")

            return {
                "status": "error" if checks_executed == 0 else "partial_success",
                "checks_executed": checks_executed,
                "checks_notified": checks_notified,
                "error": error_message,
            }

    async def _send_notification(self, result: CheckResult, context: HeartbeatContext) -> None:
        """
        Envoie notification Telegram Topic Chat & Proactive (AC5, Task 7).

        Args:
            result: CheckResult avec message et action
            context: HeartbeatContext pour respect quiet hours
        """
        # Note: Pendant quiet hours, seuls les checks CRITICAL sont exécutés
        # par l'engine. Leurs notifications DOIVENT passer (AC5 "sauf CRITICAL").
        # On ne bloque PAS les notifications ici — le filtrage est déjà fait upstream.

        # Si pas de message, skip
        if not result.message:
            logger.debug("No message in CheckResult - notification skipped")
            return

        # Importer helper Telegram
        from agents.src.core.telegram_helper import (
            create_action_keyboard,
            format_heartbeat_message,
            send_to_chat_proactive,
        )

        # Extraire check_id depuis payload (si disponible)
        check_id = result.payload.get("check_id", "unknown") if result.payload else "unknown"

        # Formater message
        formatted_message = format_heartbeat_message(
            check_id=check_id, message=result.message, emoji="🔔"
        )

        # Créer inline keyboard si action définie
        keyboard = None
        if result.action:
            keyboard = create_action_keyboard(result.action, check_id)

        # Envoyer notification
        sent = await send_to_chat_proactive(
            message=formatted_message, keyboard=keyboard, parse_mode="HTML"
        )

        if sent:
            logger.info("Heartbeat notification sent", check_id=check_id, action=result.action)
        else:
            logger.warning("Failed to send Heartbeat notification", check_id=check_id)

    async def _save_metrics(
        self,
        cycle_timestamp: datetime,
        checks_selected: List[str],
        checks_executed: int,
        checks_notified: int,
        llm_decision_reasoning: str,
        duration_ms: int,
        error: Optional[str],
    ) -> None:
        """
        Sauvegarde metrics cycle dans core.heartbeat_metrics (AC4, AC6, Task 8).

        Args:
            cycle_timestamp: Timestamp début cycle
            checks_selected: Liste IDs checks sélectionnés
            checks_executed: Nombre checks exécutés
            checks_notified: Nombre notifications envoyées
            llm_decision_reasoning: Reasoning LLM décideur
            duration_ms: Durée cycle en millisecondes
            error: Message erreur si cycle crash
        """
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO core.heartbeat_metrics (
                        cycle_timestamp,
                        checks_selected,
                        checks_executed,
                        checks_notified,
                        llm_decision_reasoning,
                        duration_ms,
                        error
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    cycle_timestamp,
                    checks_selected,
                    checks_executed,
                    checks_notified,
                    llm_decision_reasoning,
                    duration_ms,
                    error,
                )

            logger.debug(
                "Heartbeat metrics saved",
                checks_executed=checks_executed,
                checks_notified=checks_notified,
            )

        except Exception as e:
            # Ne pas crash si sauvegarde metrics échoue
            logger.error("Failed to save heartbeat metrics", error=str(e))

    async def _send_alert_system(self, message: str) -> None:
        """
        Envoie alerte Telegram Topic System & Alerts (AC6, Task 7).

        Args:
            message: Message alerte
        """
        from agents.src.core.telegram_helper import send_to_system_alerts

        # Envoyer alerte au topic System
        sent = await send_to_system_alerts(message=message, parse_mode="HTML")

        if sent:
            logger.info("Heartbeat system alert sent", alert_preview=message[:50])
        else:
            logger.warning("Failed to send system alert", alert=message)


# Note: Pour alertes système depuis d'autres modules, utiliser
# agents.src.core.check_executor.send_alert_system() (source unique DRY)
