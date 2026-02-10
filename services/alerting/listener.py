"""
Service d'alerting pour Friday 2.0.

Écoute les événements Redis Streams et envoie des alertes Telegram selon :
- Événements critiques (service down, erreurs pipeline, etc.)
- Alertes système (RAM >85%, disk >80%, etc.)
- Notifications trust (validation requise, correction appliquée)
"""

import asyncio
import json
import logging
import os
from typing import Any

import redis.asyncio as aioredis
import structlog
from telegram import Bot
from telegram.error import TelegramError

# Configuration structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

logger = structlog.get_logger()


class AlertingListener:
    """Listener Redis Streams pour alertes Telegram."""

    def __init__(self):
        """Initialise le listener d'alerting."""
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not self.telegram_token or not self.telegram_chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

        self.redis_client: aioredis.Redis | None = None
        self.telegram_bot = Bot(token=self.telegram_token)
        self.consumer_group = "alerting-service"
        self.consumer_name = f"alerting-{os.getpid()}"

        # Streams à écouter (événements critiques uniquement)
        self.streams = [
            "friday:events:service.down",
            "friday:events:pipeline.error",
            "friday:events:trust.level.changed",
            "friday:events:action.corrected",
            "friday:events:action.validated",
            "friday:events:system.alert",
        ]

    async def connect(self) -> None:
        """Connecte à Redis et crée les consumer groups."""
        self.redis_client = await aioredis.from_url(self.redis_url, decode_responses=True)
        logger.info("Connected to Redis", redis_url=self.redis_url)

        # Créer consumer groups si nécessaire
        for stream in self.streams:
            try:
                await self.redis_client.xgroup_create(
                    stream, self.consumer_group, id="0", mkstream=True
                )
                logger.info("Created consumer group", stream=stream)
            except aioredis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise
                logger.debug("Consumer group already exists", stream=stream)

    async def send_telegram_alert(self, message: str, parse_mode: str = "Markdown") -> None:
        """
        Envoie une alerte Telegram.

        Args:
            message: Message à envoyer
            parse_mode: Mode de formatage (Markdown ou HTML)
        """
        try:
            await self.telegram_bot.send_message(
                chat_id=self.telegram_chat_id,
                text=message,
                parse_mode=parse_mode,
            )
            logger.info("Telegram alert sent", message_preview=message[:50])
        except TelegramError as e:
            logger.error("Failed to send Telegram alert", error=str(e))

    async def process_event(self, stream: str, event_id: str, data: dict[str, Any]) -> None:
        """
        Traite un événement Redis et envoie une alerte si nécessaire.

        Args:
            stream: Nom du stream
            event_id: ID de l'événement
            data: Données de l'événement
        """
        event_type = stream.split(":")[-1]  # Ex: "service.down"

        logger.info("Processing event", event_type=event_type, event_id=event_id)

        # Formater le message selon le type d'événement
        if event_type == "service.down":
            service_name = data.get("service", "unknown")
            message = f"🔴 **Service Down** : {service_name}\n\nVérifier immédiatement !"
        elif event_type == "pipeline.error":
            pipeline = data.get("pipeline", "unknown")
            error = data.get("error", "no details")
            message = f"⚠️ **Pipeline Error** : {pipeline}\n\n`{error[:200]}`"
        elif event_type == "trust.level.changed":
            module = data.get("module", "unknown")
            action = data.get("action", "unknown")
            old_level = data.get("old_level", "unknown")
            new_level = data.get("new_level", "unknown")
            message = (
                f"🔄 **Trust Level Changed**\n\n"
                f"Module : {module}.{action}\n"
                f"{old_level} → {new_level}"
            )
        elif event_type == "action.validated":
            module = data.get("module", "unknown")
            action = data.get("action", "unknown")
            validated_by = data.get("validated_by", "owner")
            message = f"✅ **Action Validated**\n\n" f"{module}.{action} validé par {validated_by}"
        elif event_type == "system.alert":
            alert_type = data.get("alert_type", "unknown")
            threshold = data.get("threshold", "unknown")
            current = data.get("current", "unknown")
            message = (
                f"🚨 **System Alert** : {alert_type}\n\n"
                f"Seuil : {threshold}\n"
                f"Actuel : {current}"
            )
        else:
            # Événement générique
            message = f"ℹ️ **Event** : {event_type}\n\n{json.dumps(data, indent=2)[:300]}"

        await self.send_telegram_alert(message)

        # Acknowledger l'événement
        if self.redis_client:
            await self.redis_client.xack(stream, self.consumer_group, event_id)
            logger.info("Event acknowledged", event_id=event_id)

    async def listen(self) -> None:
        """Boucle principale d'écoute des événements."""
        if not self.redis_client:
            raise RuntimeError("Not connected to Redis")

        logger.info("Starting alerting listener", streams=self.streams)

        # Construire dict pour XREADGROUP
        streams_dict = {stream: ">" for stream in self.streams}

        while True:
            try:
                # Lire les nouveaux événements
                events = await self.redis_client.xreadgroup(
                    self.consumer_group,
                    self.consumer_name,
                    streams_dict,
                    count=10,
                    block=5000,  # 5 secondes
                )

                if events:
                    for stream, messages in events:
                        for event_id, data in messages:
                            await self.process_event(stream, event_id, data)
                else:
                    # Aucun événement, continuer
                    logger.debug("No new events")

            except Exception as e:
                logger.error("Error in listen loop", error=str(e), exc_info=True)
                await asyncio.sleep(5)  # Pause avant retry

    async def run(self) -> None:
        """Lance le service d'alerting."""
        await self.connect()
        await self.listen()


async def main() -> None:
    """Point d'entrée principal."""
    listener = AlertingListener()
    await listener.run()


if __name__ == "__main__":
    asyncio.run(main())
