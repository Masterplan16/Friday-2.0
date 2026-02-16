#!/usr/bin/env python3
"""
Friday 2.0 - Desktop Search Consumer (Story 3.3 - Task 6.2, 6.5)

Consumer Redis Streams pour recherche desktop via Claude Code CLI.

Architecture (D23):
    Telegram /search -> VPS -> Redis Streams search.requested ->
    PC Mainteneur -> Claude Code CLI (prompt mode) ->
    Redis Streams search.completed -> Telegram response

Ce consumer tourne sur le PC Mainteneur (Phase 1).
Il necessite Redis accessible via Tailscale (VPS).

Usage:
    python -m agents.src.tools.desktop_search_consumer

Date: 2026-02-16
Story: 3.3 - Task 6.2, 6.5
"""

import asyncio
import json
import os
from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog

from agents.src.tools.desktop_search_wrapper import search_desktop

logger = structlog.get_logger(__name__)

# ============================================================
# Constants
# ============================================================

REDIS_STREAM_INPUT = "search.requested"
REDIS_STREAM_OUTPUT = "search.completed"
CONSUMER_GROUP = "desktop-search"
CONSUMER_NAME = os.getenv("DESKTOP_SEARCH_CONSUMER_NAME", "desktop-worker-1")

BLOCK_TIMEOUT_MS = 5000  # 5s block on XREADGROUP
BATCH_SIZE = 5  # Max messages per batch
ALERT_THRESHOLD_FAILURES = 3  # Alert after N consecutive failures


# ============================================================
# Desktop Search Consumer
# ============================================================


class DesktopSearchConsumer:
    """
    Consumer Redis Streams pour desktop search via Claude CLI (Task 6.2, 6.5).

    Tourne sur PC Mainteneur. Consomme search.requested, invoque
    Claude Code CLI, publie search.completed.
    """

    def __init__(self, redis_client: aioredis.Redis):
        """
        Initialise DesktopSearchConsumer.

        Args:
            redis_client: Client Redis (connexion VPS via Tailscale)
        """
        self.redis_client = redis_client
        self.running = False
        self.consecutive_failures = 0

        logger.info(
            "DesktopSearchConsumer initialized",
            input_stream=REDIS_STREAM_INPUT,
            output_stream=REDIS_STREAM_OUTPUT,
            consumer=CONSUMER_NAME,
        )

    async def start(self) -> None:
        """
        Demarre le consumer (boucle infinie).

        Cree consumer group si necessaire, puis consume en continu.
        """
        # Creer consumer group si n'existe pas
        try:
            await self.redis_client.xgroup_create(
                name=REDIS_STREAM_INPUT,
                groupname=CONSUMER_GROUP,
                id="0",
                mkstream=True,
            )
            logger.info("Consumer group created", group=CONSUMER_GROUP)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug("Consumer group already exists", group=CONSUMER_GROUP)
            else:
                raise

        self.running = True
        logger.info("DesktopSearchConsumer started", consumer=CONSUMER_NAME)

        while self.running:
            try:
                await self._consume_batch()
            except Exception as e:
                logger.error("Consumer loop error", error=str(e))
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Arrete le consumer gracefully."""
        self.running = False
        logger.info("DesktopSearchConsumer stopped")

    async def _consume_batch(self) -> None:
        """Consume un batch d'events search.requested."""
        events = await self.redis_client.xreadgroup(
            groupname=CONSUMER_GROUP,
            consumername=CONSUMER_NAME,
            streams={REDIS_STREAM_INPUT: ">"},
            count=BATCH_SIZE,
            block=BLOCK_TIMEOUT_MS,
        )

        if not events:
            return

        for stream_name, messages in events:
            for message_id, data in messages:
                await self._process_search_request(
                    message_id=message_id.decode() if isinstance(message_id, bytes) else message_id,
                    data=data,
                )

    async def _process_search_request(
        self,
        message_id: str,
        data: dict,
    ) -> None:
        """
        Traite une requete search.requested (Task 6.2).

        Pipeline:
        1. Extract query + filters depuis event
        2. Invoke Claude CLI via desktop_search_wrapper
        3. Publish search.completed avec resultats (Task 6.5)
        4. ACK message Redis

        Args:
            message_id: ID message Redis Streams
            data: Event data (bytes dict)
        """
        try:
            # Decoder data (bytes -> str)
            event_data = {
                (k.decode() if isinstance(k, bytes) else k): (
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in data.items()
            }
            query = event_data.get("query")
            request_id = event_data.get("request_id", message_id)
            max_results = int(event_data.get("max_results", "5"))

            if not query:
                logger.warning(
                    "Missing query in search.requested event",
                    message_id=message_id,
                    event_data=event_data,
                )
                await self._ack_message(message_id)
                return

            logger.info(
                "Processing search.requested",
                message_id=message_id,
                request_id=request_id,
                query_length=len(query),
            )

            # Invoke Claude CLI desktop search (Task 6.3)
            try:
                results = await search_desktop(
                    query=query,
                    max_results=max_results,
                )
            except (FileNotFoundError, TimeoutError) as e:
                # Claude CLI indisponible ou timeout -> publier resultat vide (Task 6.6)
                logger.warning(
                    "Desktop search unavailable, publishing empty results",
                    error=str(e),
                )
                results = []

            # Publish search.completed (Task 6.5)
            await self._publish_search_completed(
                request_id=request_id,
                query=query,
                results=results,
            )

            # ACK message
            await self._ack_message(message_id)

            # Reset failures
            self.consecutive_failures = 0

            logger.info(
                "Desktop search completed",
                request_id=request_id,
                results_count=len(results),
            )

        except Exception as e:
            self.consecutive_failures += 1
            logger.error(
                "Desktop search request failed",
                message_id=message_id,
                error=str(e),
                consecutive_failures=self.consecutive_failures,
            )

            if self.consecutive_failures >= ALERT_THRESHOLD_FAILURES:
                logger.error(
                    "TELEGRAM ALERT: Desktop search consumer failing",
                    consecutive_failures=self.consecutive_failures,
                    error=str(e),
                )

    async def _publish_search_completed(
        self,
        request_id: str,
        query: str,
        results: list[dict],
    ) -> None:
        """
        Publie search.completed dans Redis Streams (Task 6.5).

        Args:
            request_id: ID requete originale (pour correlation)
            query: Query originale
            results: Liste resultats desktop search
        """
        event_data = {
            "request_id": request_id,
            "query": query,
            "results": json.dumps(results),
            "results_count": str(len(results)),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "source": "desktop_claude_cli",
        }

        message_id = await self.redis_client.xadd(
            name=REDIS_STREAM_OUTPUT,
            fields=event_data,
        )

        logger.debug(
            "Published search.completed",
            request_id=request_id,
            message_id=message_id.decode() if isinstance(message_id, bytes) else message_id,
            results_count=len(results),
        )

    async def _ack_message(self, message_id: str) -> None:
        """ACK message Redis Streams."""
        await self.redis_client.xack(
            name=REDIS_STREAM_INPUT,
            groupname=CONSUMER_GROUP,
            id=message_id,
        )


# ============================================================
# Main Entry Point
# ============================================================


async def main():
    """Point d'entree consumer desktop search (PC Mainteneur)."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    redis_client = await aioredis.from_url(redis_url, decode_responses=False)
    logger.info("Redis connected", redis_url=redis_url)

    consumer = DesktopSearchConsumer(redis_client=redis_client)

    try:
        await consumer.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Received shutdown signal")
    finally:
        await consumer.stop()
        await redis_client.close()
        logger.info("Desktop search consumer shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
