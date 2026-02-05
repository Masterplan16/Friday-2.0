# services/document-indexer/consumer.py
# Consumer Redis Streams pour événements document.processed
# Partie de Story 3 : Archiviste (OCR + Renommage)

import asyncio
import json
import logging
from typing import Dict, Any

import redis.asyncio as redis

logger = logging.getLogger(__name__)

class DocumentIndexerConsumer:
    """
    Consumer Redis Streams pour indexer les documents traités

    Workflow:
    1. Écoute stream "document.processed" via consumer group "document-indexer"
    2. Pour chaque événement, indexe le document dans:
       - Qdrant (embeddings pour recherche sémantique)
       - PostgreSQL knowledge.* (métadonnées + graphe)
    3. ACK l'événement après indexation réussie
    """

    def __init__(
        self,
        redis_url: str,
        stream: str = "document.processed",
        group: str = "document-indexer",
        consumer_name: str = "worker-1"
    ):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.stream = stream
        self.group = group
        self.consumer_name = consumer_name

    async def start(self):
        """Démarre le consumer (boucle infinie)"""
        logger.info(f"🔄 Starting Document Indexer Consumer: {self.group}/{self.consumer_name}")

        while True:
            try:
                events = await self.redis.xreadgroup(
                    groupname=self.group,
                    consumername=self.consumer_name,
                    streams={self.stream: ">"},
                    count=10,
                    block=5000
                )

                if not events:
                    continue

                for stream_name, messages in events:
                    for event_id, payload in messages:
                        try:
                            data = self._deserialize_payload(payload)
                            await self.process_document(event_id, data)
                            await self.redis.xack(self.stream, self.group, event_id)

                        except Exception as e:
                            logger.error(f"❌ Error processing {event_id}: {e}", exc_info=True)

            except asyncio.CancelledError:
                logger.info("🛑 Consumer stopped")
                break
            except Exception as e:
                logger.error(f"❌ Consumer error: {e}", exc_info=True)
                await asyncio.sleep(5)

    def _deserialize_payload(self, payload: Dict[str, str]) -> Dict[str, Any]:
        """Désérialise le payload Redis (JSON strings)"""
        return {
            k: json.loads(v) if v.startswith(("{", "[")) else v
            for k, v in payload.items()
        }

    async def process_document(self, event_id: str, data: Dict[str, Any]):
        """
        Indexe un document traité dans Qdrant + PostgreSQL knowledge

        Args:
            event_id: ID de l'événement Redis
            data: {document_id, filename, doc_type, category, ocr_text}
        """
        document_id = data.get("document_id")
        filename = data.get("filename")
        doc_type = data.get("doc_type")
        ocr_text = data.get("ocr_text", "")

        logger.info(f"📄 Indexing document {document_id} ({doc_type})")

        # 1. Générer embeddings du texte OCR
        await self._generate_embeddings(document_id, ocr_text)

        # 2. Indexer dans Qdrant pour recherche sémantique
        await self._index_to_qdrant(document_id, ocr_text)

        # 3. Extraire entités et relations pour graphe de connaissances
        await self._extract_entities_and_relations(document_id, ocr_text, doc_type)

        logger.info(f"✅ Document {document_id} indexed successfully")

    async def _generate_embeddings(self, document_id: str, text: str):
        """Génère embeddings via Mistral Embed API"""
        # TODO Story 3: Implémenter génération embeddings
        logger.info(f"🧠 [TODO] Generate embeddings for document {document_id}")

    async def _index_to_qdrant(self, document_id: str, text: str):
        """Indexe document dans Qdrant pour recherche sémantique"""
        # TODO Story 3: Implémenter indexation Qdrant
        logger.info(f"🔍 [TODO] Index document {document_id} to Qdrant")

    async def _extract_entities_and_relations(self, document_id: str, text: str, doc_type: str):
        """Extrait entités (NER) et relations pour graphe de connaissances"""
        # TODO Story 3: Implémenter extraction entités + insertion knowledge.*
        logger.info(f"🕸️ [TODO] Extract entities from document {document_id}")

    async def claim_pending_events(self, idle_time_ms: int = 60000):
        """Recovery des événements pending (cf email-processor)"""
        pending = await self.redis.xpending_range(
            self.stream,
            self.group,
            min="-",
            max="+",
            count=100
        )

        if not pending:
            return

        logger.warning(f"⚠️  Found {len(pending)} pending events, attempting recovery...")

        for entry in pending:
            event_id = entry['message_id']
            idle_ms = entry['time_since_delivered']

            if idle_ms < idle_time_ms:
                continue

            claimed = await self.redis.xclaim(
                self.stream,
                self.group,
                self.consumer_name,
                min_idle_time=idle_time_ms,
                message_ids=[event_id]
            )

            if claimed:
                event_id_claimed, payload = claimed[0]
                logger.info(f"🔁 Reclaimed event {event_id} from previous consumer")
                data = self._deserialize_payload(payload)
                await self.process_document(event_id_claimed, data)
                await self.redis.xack(self.stream, self.group, event_id_claimed)


async def main():
    """Point d'entrée du consumer"""
    import os

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    consumer_name = os.getenv("CONSUMER_NAME", f"worker-{os.getpid()}")

    consumer = DocumentIndexerConsumer(
        redis_url=redis_url,
        consumer_name=consumer_name
    )

    async def recovery_loop():
        while True:
            await asyncio.sleep(60)
            await consumer.claim_pending_events()

    await asyncio.gather(
        consumer.start(),
        recovery_loop()
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(main())
