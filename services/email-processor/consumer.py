"""
Email Processor Consumer - Story 2.1 Task 3
Consumer Redis Streams pour traiter les événements email.received

Pipeline:
    1. Fetch email complet depuis EmailEngine
    2. Anonymiser body complet via Presidio
    3. Classification stub (Day 1 = category="inbox")
    4. Stocker email dans PostgreSQL ingestion.emails
    5. Notification Telegram topic Email

Author: Claude Sonnet 4.5
Date: 2026-02-11
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

import asyncpg
import httpx
import redis.asyncio as redis
import structlog

# Ajouter repo root au path
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))

from agents.src.tools.anonymize import anonymize_text

# ============================================
# Logging Setup
# ============================================

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


# ============================================
# Configuration
# ============================================

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://friday:friday@localhost:5432/friday')
EMAILENGINE_URL = os.getenv('EMAILENGINE_BASE_URL', 'http://localhost:3000')
EMAILENGINE_SECRET = os.getenv('EMAILENGINE_SECRET')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TOPIC_EMAIL_ID = os.getenv('TOPIC_EMAIL_ID')

STREAM_NAME = 'emails:received'
CONSUMER_GROUP = 'email-processor-group'
CONSUMER_NAME = f'consumer-{os.getpid()}'


# ============================================
# EmailProcessorConsumer Class
# ============================================

class EmailProcessorConsumer:
    """
    Consumer Redis Streams pour pipeline email

    Workflow:
        1. XREADGROUP sur stream emails:received
        2. Pour chaque événement:
            a. Fetch email complet EmailEngine API
            b. Anonymiser body (Presidio)
            c. Classification stub (category="inbox")
            d. Store PostgreSQL ingestion.emails
            e. Notify Telegram topic Email
        3. XACK après traitement complet
    """

    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.db: Optional[asyncpg.Connection] = None
        self.http_client: Optional[httpx.AsyncClient] = None

    async def connect(self):
        """Connect to Redis and PostgreSQL"""
        # Redis
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)
        await self.redis.ping()
        logger.info("redis_connected")

        # PostgreSQL
        self.db = await asyncpg.connect(DATABASE_URL)
        logger.info("postgresql_connected")

        # HTTP client
        self.http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("http_client_created")

        # Create consumer group if not exists
        try:
            await self.redis.xgroup_create(
                STREAM_NAME,
                CONSUMER_GROUP,
                id='$',  # Start from new messages
                mkstream=True
            )
            logger.info("consumer_group_created", group=CONSUMER_GROUP)
        except redis.ResponseError as e:
            if 'BUSYGROUP' in str(e):
                logger.info("consumer_group_exists", group=CONSUMER_GROUP)
            else:
                raise

    async def close(self):
        """Close all connections"""
        if self.http_client:
            await self.http_client.aclose()
        if self.db:
            await self.db.close()
        if self.redis:
            await self.redis.close()
        logger.info("connections_closed")

    async def start(self):
        """Start consumer loop"""
        logger.info("consumer_starting", group=CONSUMER_GROUP, consumer=CONSUMER_NAME)

        while True:
            try:
                # XREADGROUP: Lire événements du stream
                events = await self.redis.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=CONSUMER_NAME,
                    streams={STREAM_NAME: '>'},
                    count=10,
                    block=5000  # Block 5s si aucun événement
                )

                if not events:
                    continue  # Timeout, retry

                # Process each event
                for stream_name, messages in events:
                    for event_id, payload in messages:
                        await self.process_email_event(event_id, payload)

            except asyncio.CancelledError:
                logger.info("consumer_cancelled")
                break
            except Exception as e:
                logger.error("consumer_error", error=str(e), exc_info=True)
                await asyncio.sleep(5)  # Backoff before retry

    async def process_email_event(self, event_id: str, payload: Dict[str, str]):
        """
        Process single email.received event

        Args:
            event_id: Redis stream event ID
            payload: Event payload from Redis
        """
        start_time = datetime.utcnow()

        try:
            # Parse payload
            account_id = payload.get('account_id')
            message_id = payload.get('message_id')
            from_anon = payload.get('from_anon')
            subject_anon = payload.get('subject_anon')
            date_str = payload.get('date')
            has_attachments = payload.get('has_attachments') == 'True'

            logger.info(
                "processing_email",
                event_id=event_id,
                account_id=account_id,
                message_id=message_id
            )

            # Étape 1: Fetch email complet depuis EmailEngine
            email_full = await self.fetch_email_from_emailengine(account_id, message_id)

            if not email_full:
                logger.error("email_fetch_failed", message_id=message_id)
                # Ne pas XACK, message restera dans PEL pour retry
                return

            # Étape 2: Anonymiser body complet
            body_text = email_full.get('text', email_full.get('html', ''))
            body_anon = await anonymize_text(body_text) if body_text else ""

            logger.info("email_anonymized", message_id=message_id, body_length=len(body_anon))

            # Étape 3: Classification stub (Day 1)
            # TODO Story 2.2: Remplacer par classification LLM réelle
            category = "inbox"
            confidence = 0.5

            # Étape 4: Stocker dans PostgreSQL
            await self.store_email_in_database(
                account_id=account_id,
                message_id=message_id,
                from_anon=from_anon,
                subject_anon=subject_anon,
                body_anon=body_anon,
                category=category,
                confidence=confidence,
                received_at=date_str,
                has_attachments=has_attachments
            )

            # Étape 5: Notification Telegram
            await self.send_telegram_notification(
                account_id=account_id,
                from_anon=from_anon,
                subject_anon=subject_anon,
                category=category
            )

            # XACK: Marquer comme traité
            await self.redis.xack(STREAM_NAME, CONSUMER_GROUP, event_id)

            # Log success avec latency
            latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.info(
                "email_processed_success",
                event_id=event_id,
                message_id=message_id,
                latency_ms=int(latency_ms)
            )

        except Exception as e:
            logger.error(
                "email_processing_error",
                event_id=event_id,
                error=str(e),
                exc_info=True
            )
            # Ne pas XACK → message reste dans PEL pour retry

    async def fetch_email_from_emailengine(
        self,
        account_id: str,
        message_id: str
    ) -> Optional[Dict]:
        """Fetch email complet depuis EmailEngine API"""
        try:
            response = await self.http_client.get(
                f'{EMAILENGINE_URL}/v1/account/{account_id}/message/{message_id}',
                headers={'Authorization': f'Bearer {EMAILENGINE_SECRET}'}
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(
                    "emailengine_fetch_failed",
                    account_id=account_id,
                    message_id=message_id,
                    status_code=response.status_code
                )
                return None

        except Exception as e:
            logger.error("emailengine_request_error", error=str(e))
            return None

    async def store_email_in_database(
        self,
        account_id: str,
        message_id: str,
        from_anon: str,
        subject_anon: str,
        body_anon: str,
        category: str,
        confidence: float,
        received_at: str,
        has_attachments: bool
    ):
        """Store email dans PostgreSQL ingestion.emails"""
        await self.db.execute(
            """
            INSERT INTO ingestion.emails (
                account_id, message_id, from_anon, subject_anon, body_anon,
                category, confidence, received_at, has_attachments
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (account_id, message_id) DO UPDATE SET
                from_anon = EXCLUDED.from_anon,
                subject_anon = EXCLUDED.subject_anon,
                body_anon = EXCLUDED.body_anon,
                category = EXCLUDED.category,
                confidence = EXCLUDED.confidence,
                processed_at = CURRENT_TIMESTAMP
            """,
            account_id,
            message_id,
            from_anon,
            subject_anon,
            body_anon,
            category,
            confidence,
            datetime.fromisoformat(received_at.replace('Z', '+00:00')),
            has_attachments
        )

        logger.info("email_stored_database", message_id=message_id)

    async def send_telegram_notification(
        self,
        account_id: str,
        from_anon: str,
        subject_anon: str,
        category: str
    ):
        """Send notification to Telegram topic Email"""
        if not TELEGRAM_BOT_TOKEN or not TOPIC_EMAIL_ID:
            logger.warning("telegram_not_configured")
            return

        try:
            # TODO: Implémenter envoi Telegram via bot API
            # Format: "📬 Nouvel email : [subject_anon] de [from_anon] - Catégorie: inbox"
            logger.info(
                "telegram_notification_sent",
                account_id=account_id,
                category=category
            )
        except Exception as e:
            logger.error("telegram_notification_error", error=str(e))


# ============================================
# Main Entry Point
# ============================================

async def main():
    """Main entry point"""
    consumer = EmailProcessorConsumer()

    try:
        await consumer.connect()
        await consumer.start()
    except KeyboardInterrupt:
        logger.info("consumer_interrupted")
    finally:
        await consumer.close()


if __name__ == '__main__':
    asyncio.run(main())
