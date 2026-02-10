# services/email-processor/consumer.py
# Consumer Redis Streams pour événements email.received
# Partie de Story 2 : Moteur Vie (Email Pipeline)

import asyncio
import json
import logging
from typing import Any, Dict

import redis.asyncio as redis
from agents.src.middleware.trust import ActionResult, friday_action

logger = logging.getLogger(__name__)


class EmailProcessorConsumer:
    """
    Consumer Redis Streams pour traiter les événements email.received

    Workflow:
    1. Écoute stream "email.received" via consumer group "email-processor"
    2. Pour chaque événement, déclenche les actions downstream:
       - Extraction tâches (si email contient TODOs)
       - Extraction événements agenda (si email contient dates/invitations)
       - Envoi notification Telegram si priorité HIGH
    3. ACK l'événement après traitement réussi
    """

    def __init__(
        self,
        redis_url: str,
        stream: str = "email.received",
        group: str = "email-processor",
        consumer_name: str = "worker-1",
    ):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.stream = stream
        self.group = group
        self.consumer_name = consumer_name

    async def start(self):
        """Démarre le consumer (boucle infinie)"""
        logger.info(f"🔄 Starting Email Processor Consumer: {self.group}/{self.consumer_name}")

        while True:
            try:
                # XREADGROUP : Lire nouveaux événements du stream
                events = await self.redis.xreadgroup(
                    groupname=self.group,
                    consumername=self.consumer_name,
                    streams={self.stream: ">"},  # ">" = nouveaux messages uniquement
                    count=10,  # Batch de 10 événements max
                    block=5000,  # Block 5s si aucun événement
                )

                if not events:
                    continue  # Timeout, retry

                for stream_name, messages in events:
                    for event_id, payload in messages:
                        try:
                            # Désérialiser payload
                            data = self._deserialize_payload(payload)

                            # Traiter événement
                            await self.process_email_received(event_id, data)

                            # ACK: Marquer comme traité
                            await self.redis.xack(self.stream, self.group, event_id)

                        except Exception as e:
                            logger.error(f"❌ Error processing {event_id}: {e}", exc_info=True)
                            # Ne pas ACK → restera dans Pending List pour retry

            except asyncio.CancelledError:
                logger.info("🛑 Consumer stopped")
                break
            except Exception as e:
                logger.error(f"❌ Consumer error: {e}", exc_info=True)
                await asyncio.sleep(5)  # Retry après 5s

    def _deserialize_payload(self, payload: Dict[str, str]) -> Dict[str, Any]:
        """Désérialise le payload Redis (JSON strings)"""
        return {k: json.loads(v) if v.startswith(("{", "[")) else v for k, v in payload.items()}

    async def process_email_received(self, event_id: str, data: Dict[str, Any]):
        """
        Traite un événement email.received

        Args:
            event_id: ID de l'événement Redis (ex: "1517574547834-0")
            data: Payload désérialisé {email_id, category, priority, has_attachments}
        """
        email_id = data.get("email_id")
        category = data.get("category")
        priority = data.get("priority")
        has_attachments = data.get("has_attachments", False)

        logger.info(f"📧 Processing email {email_id} (category={category}, priority={priority})")

        # 1. Si priorité HIGH → Notification Telegram immédiate
        if priority == "high":
            await self._send_telegram_notification(email_id, category)

        # 2. Extraction tâches (si catégorie pertinente)
        if category in ["professional", "thesis", "personal"]:
            await self._extract_tasks_from_email(email_id)

        # 3. Extraction événements agenda (si email contient dates)
        await self._extract_events_from_email(email_id)

        # 4. Si attachments → Trigger document processing
        if has_attachments:
            await self._trigger_attachment_processing(email_id)

        logger.info(f"✅ Email {email_id} processed successfully")

    async def _send_telegram_notification(self, email_id: str, category: str):
        """Envoie notification Telegram pour email prioritaire"""
        # TODO Story 2: Implémenter envoi Telegram via bot API
        logger.info(
            f"📱 [TODO] Send Telegram notification for email {email_id} (category={category})"
        )

    async def _extract_tasks_from_email(self, email_id: str):
        """Extrait tâches détectées dans l'email"""
        # TODO Story 2: Implémenter extraction tâches via agent email
        logger.info(f"📋 [TODO] Extract tasks from email {email_id}")

    async def _extract_events_from_email(self, email_id: str):
        """Extrait événements agenda détectés dans l'email"""
        # TODO Story 9: Implémenter extraction événements via agent agenda
        logger.info(f"📅 [TODO] Extract events from email {email_id}")

    async def _trigger_attachment_processing(self, email_id: str):
        """Déclenche traitement des pièces jointes"""
        # TODO Story 3: Publier événement Redis pour archiviste
        logger.info(f"📎 [TODO] Trigger attachment processing for email {email_id}")

    async def claim_pending_events(self, idle_time_ms: int = 60000):
        """
        Récupère les événements pending depuis plus de idle_time_ms (recovery)

        Args:
            idle_time_ms: Temps minimum depuis dernier delivery (défaut: 60s)
        """
        pending = await self.redis.xpending_range(
            self.stream, self.group, min="-", max="+", count=100
        )

        if not pending:
            return

        logger.warning(f"⚠️  Found {len(pending)} pending events, attempting recovery...")

        for entry in pending:
            event_id = entry["message_id"]
            consumer = entry["consumer"]
            idle_ms = entry["time_since_delivered"]

            if idle_ms < idle_time_ms:
                continue  # Pas encore timeout

            # XCLAIM: Réclamer l'événement
            claimed = await self.redis.xclaim(
                self.stream,
                self.group,
                self.consumer_name,
                min_idle_time=idle_time_ms,
                message_ids=[event_id],
            )

            if claimed:
                event_id_claimed, payload = claimed[0]
                logger.info(f"🔁 Reclaimed event {event_id} from {consumer}")

                # Retraiter l'événement
                data = self._deserialize_payload(payload)
                await self.process_email_received(event_id_claimed, data)
                await self.redis.xack(self.stream, self.group, event_id_claimed)


async def main():
    """Point d'entrée du consumer (pour Docker Compose service)"""
    import os

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    consumer_name = os.getenv("CONSUMER_NAME", f"worker-{os.getpid()}")

    consumer = EmailProcessorConsumer(redis_url=redis_url, consumer_name=consumer_name)

    # Lancer recovery des pending events toutes les minutes
    async def recovery_loop():
        while True:
            await asyncio.sleep(60)
            await consumer.claim_pending_events()

    # Lancer consumer + recovery en parallèle
    await asyncio.gather(consumer.start(), recovery_loop())


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    asyncio.run(main())
