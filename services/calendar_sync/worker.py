"""Daemon de synchronisation Google Calendar."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
import structlog
from agents.src.integrations.google_calendar.sync_manager import GoogleCalendarSync

logger = structlog.get_logger(__name__)


async def send_telegram_alert(message: str, topic: str = "system"):
    """Envoie une alerte Telegram au topic spécifié.

    Args:
        message: Contenu de l'alerte
        topic: Topic Telegram (default: system)

    Note:
        Cette fonction sera intégrée avec le bot Telegram dans Story 1.9.
        Pour l'instant, elle log simplement le message.
    """
    # M1 fix: use structlog instead of f-string logging
    logger.error(
        "Telegram alert stub",
        topic=topic,
        message=message,
    )
    # TODO Story 1.9: Intégrer avec le bot Telegram pour envoyer réellement l'alerte


class CalendarSyncWorker:
    """Worker daemon pour synchronisation Google Calendar automatique.

    Fonctionnalités:
    - Sync bidirectionnelle toutes les N minutes (configurable)
    - Healthcheck Redis (calendar:last_sync TTL 1h)
    - Compteur échecs avec alerte System après 3 échecs consécutifs
    - Arrêt gracieux via shutdown_event (SIGTERM)
    """

    HEALTHCHECK_KEY = "calendar:last_sync"
    HEALTHCHECK_TTL = 3600  # 1 heure
    FAILURE_COUNTER_KEY = "calendar:sync_failures"
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(
        self,
        sync_manager: GoogleCalendarSync,
        redis_client: aioredis.Redis,
        config: dict,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        """Initialise le worker.

        Args:
            sync_manager: Instance de GoogleCalendarSync
            redis_client: Client Redis asyncio
            config: Configuration complète (doit contenir google_calendar.sync_interval_minutes)
            shutdown_event: Event pour arrêt gracieux (M2 fix)
        """
        self.sync_manager = sync_manager
        self.redis = redis_client
        self.config = config
        self.sync_interval = (
            config["google_calendar"]["sync_interval_minutes"] * 60
        )  # Convert to seconds
        self.shutdown_event = shutdown_event or asyncio.Event()

    async def sync_once(self) -> bool:
        """Exécute une synchronisation unique.

        Returns:
            True si succès, False si échec

        Side effects:
            - Met à jour calendar:last_sync (healthcheck)
            - Incrémente calendar:sync_failures si échec
            - Reset calendar:sync_failures si succès
            - Envoie alerte Telegram après 3 échecs consécutifs
        """
        try:
            result = await self.sync_manager.sync_bidirectional()

            if result.errors:
                logger.warning(
                    "Sync completed with errors",
                    error_count=len(result.errors),
                    errors=result.errors,
                )

            # H4 fix: use timezone-aware datetime
            healthcheck_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "events_created": result.events_created,
                "events_updated": result.events_updated,
                "errors_count": len(result.errors),
            }

            await self.redis.set(
                self.HEALTHCHECK_KEY,
                json.dumps(healthcheck_data),
                ex=self.HEALTHCHECK_TTL,
            )

            await self.redis.delete(self.FAILURE_COUNTER_KEY)

            logger.info(
                "Sync successful",
                events_created=result.events_created,
                events_updated=result.events_updated,
            )
            return True

        except Exception as e:
            logger.error("Sync failed", error=str(e), exc_info=True)

            failure_count = await self.redis.incr(self.FAILURE_COUNTER_KEY)

            if failure_count >= self.MAX_CONSECUTIVE_FAILURES:
                await send_telegram_alert(
                    message=(
                        "Google Calendar sync: %d echecs consecutifs. "
                        "Derniere erreur: %s. "
                        "Verifiez les credentials OAuth2 et la config." % (failure_count, str(e))
                    ),
                    topic="system",
                )

            return False

    async def run(self):
        """Boucle principale du daemon.

        Exécute sync_bidirectional() toutes les sync_interval_minutes.
        M2 fix: vérifie shutdown_event pour arrêt gracieux.
        """
        logger.info(
            "Calendar sync worker started",
            interval_s=self.sync_interval,
            interval_min=self.sync_interval // 60,
        )

        try:
            while not self.shutdown_event.is_set():
                await self.sync_once()

                # M2 fix: use wait with timeout instead of sleep
                # This allows shutdown_event to interrupt the wait
                try:
                    await asyncio.wait_for(
                        self.shutdown_event.wait(),
                        timeout=self.sync_interval,
                    )
                    # If we get here, shutdown was requested
                    break
                except asyncio.TimeoutError:
                    # Normal: timeout expired, loop continues
                    pass

        except asyncio.CancelledError:
            logger.info("Calendar sync worker shutting down gracefully")
            raise

    async def start(self):
        """Démarre le worker (alias pour run)."""
        await self.run()
