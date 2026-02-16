"""Daemon de synchronisation Google Calendar."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from agents.src.integrations.google_calendar.sync_manager import GoogleCalendarSync

logger = logging.getLogger(__name__)


async def send_telegram_alert(message: str, topic: str = "system"):
    """Envoie une alerte Telegram au topic spécifié.

    Args:
        message: Contenu de l'alerte
        topic: Topic Telegram (default: system)

    Note:
        Cette fonction sera intégrée avec le bot Telegram dans Story 1.9.
        Pour l'instant, elle log simplement le message.
    """
    logger.error(f"[TELEGRAM ALERT {topic.upper()}] {message}")
    # TODO Story 1.9: Intégrer avec le bot Telegram pour envoyer réellement l'alerte


class CalendarSyncWorker:
    """Worker daemon pour synchronisation Google Calendar automatique.

    Fonctionnalités:
    - Sync bidirectionnelle toutes les N minutes (configurable)
    - Healthcheck Redis (calendar:last_sync TTL 1h)
    - Compteur échecs avec alerte System après 3 échecs consécutifs
    - Arrêt gracieux (SIGTERM)
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
    ):
        """Initialise le worker.

        Args:
            sync_manager: Instance de GoogleCalendarSync
            redis_client: Client Redis asyncio
            config: Configuration complète (doit contenir google_calendar.sync_interval_minutes)
        """
        self.sync_manager = sync_manager
        self.redis = redis_client
        self.config = config
        self.sync_interval = (
            config["google_calendar"]["sync_interval_minutes"] * 60
        )  # Convert to seconds

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
            # Execute bidirectional sync
            result = await self.sync_manager.sync_bidirectional()

            if result.errors:
                logger.warning(
                    f"Sync completed with errors: {len(result.errors)} errors"
                )
                for error in result.errors:
                    logger.error(f"  - {error}")

            # Update healthcheck Redis key
            healthcheck_data = {
                "timestamp": datetime.now().isoformat(),
                "events_created": result.events_created,
                "events_updated": result.events_updated,
                "errors_count": len(result.errors),
            }

            await self.redis.set(
                self.HEALTHCHECK_KEY,
                json.dumps(healthcheck_data),
                ex=self.HEALTHCHECK_TTL,
            )

            # Reset failure counter on success
            await self.redis.delete(self.FAILURE_COUNTER_KEY)

            logger.info(
                f"Sync successful: {result.events_created} created, "
                f"{result.events_updated} updated"
            )
            return True

        except Exception as e:
            logger.error(f"Sync failed: {str(e)}", exc_info=True)

            # Increment failure counter
            failure_count = await self.redis.incr(self.FAILURE_COUNTER_KEY)

            # Send alert after MAX_CONSECUTIVE_FAILURES
            if failure_count >= self.MAX_CONSECUTIVE_FAILURES:
                await send_telegram_alert(
                    message=(
                        f"🚨 Google Calendar sync: {failure_count} échecs consécutifs\n"
                        f"Dernière erreur: {str(e)}\n"
                        f"Vérifiez les credentials OAuth2 et la config."
                    ),
                    topic="system",
                )

            return False

    async def run(self):
        """Boucle principale du daemon.

        Exécute sync_bidirectional() toutes les sync_interval_minutes.
        Gère gracieusement SIGTERM/CancelledError.
        """
        logger.info(
            f"Calendar sync worker started (interval: {self.sync_interval}s = "
            f"{self.sync_interval // 60} min)"
        )

        try:
            while True:
                # Execute sync
                await self.sync_once()

                # Wait for next sync
                logger.debug(f"Waiting {self.sync_interval}s until next sync...")
                await asyncio.sleep(self.sync_interval)

        except asyncio.CancelledError:
            logger.info("Calendar sync worker shutting down gracefully...")
            raise  # Re-raise to allow proper cleanup

    async def start(self):
        """Démarre le worker (alias pour run)."""
        await self.run()
