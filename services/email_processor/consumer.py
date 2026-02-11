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
import time

import asyncpg
import httpx
import redis.asyncio as redis
import structlog

# Ajouter repo root au path
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))

from agents.src.tools.anonymize import anonymize_text
from agents.src.agents.email.vip_detector import (
    compute_email_hash,
    detect_vip_sender,
    update_vip_email_stats,
)
from agents.src.agents.email.urgency_detector import detect_urgency
from agents.src.agents.email.attachment_extractor import extract_attachments
from agents.src.middleware.trust import init_trust_manager

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
TELEGRAM_SUPERGROUP_ID = os.getenv('TELEGRAM_SUPERGROUP_ID')
TOPIC_EMAIL_ID = os.getenv('TOPIC_EMAIL_ID')
TOPIC_ACTIONS_ID = os.getenv('TOPIC_ACTIONS_ID')
EMAILENGINE_ENCRYPTION_KEY = os.getenv('EMAILENGINE_ENCRYPTION_KEY')

STREAM_NAME = 'emails:received'
STREAM_DLQ = 'emails:failed'
CONSUMER_GROUP = 'email-processor-group'
CONSUMER_NAME = f'consumer-{os.getpid()}'


# ============================================
# EmailEngine Client Wrapper (Story 2.4)
# ============================================

class EmailEngineClient:
    """
    Wrapper simple pour EmailEngine API (Story 2.4).

    Expose méthodes requises par extract_attachments():
    - get_message(email_id)
    - download_attachment(email_id, attachment_id)
    """

    def __init__(self, http_client: httpx.AsyncClient, base_url: str, secret: str):
        self.http_client = http_client
        self.base_url = base_url
        self.secret = secret

    async def get_message(self, message_id: str) -> Dict:
        """
        Récupère email complet via EmailEngine API.

        Args:
            message_id: ID message EmailEngine

        Returns:
            Dict avec email data + attachments list

        Raises:
            Exception si fetch échoue
        """
        # Extract account_id from message_id format (account_id/message_id)
        # NOTE: En production, passer account_id explicitement
        # Pour MVP, assume format "account/message"
        if '/' in message_id:
            account_id, msg_id = message_id.split('/', 1)
        else:
            # Fallback: utiliser env var ou premier compte
            account_id = "main"  # TODO: Config
            msg_id = message_id

        response = await self.http_client.get(
            f'{self.base_url}/v1/account/{account_id}/message/{msg_id}',
            headers={'Authorization': f'Bearer {self.secret}'},
            timeout=30.0
        )

        if response.status_code != 200:
            raise Exception(f"EmailEngine get_message failed: {response.status_code} - {response.text[:200]}")

        return response.json()

    async def download_attachment(self, email_id: str, attachment_id: str) -> bytes:
        """
        Télécharge pièce jointe via EmailEngine API.

        Args:
            email_id: ID email source
            attachment_id: ID attachment

        Returns:
            Bytes du fichier

        Raises:
            Exception si download échoue
        """
        # Extract account_id (voir get_message())
        if '/' in email_id:
            account_id, msg_id = email_id.split('/', 1)
        else:
            account_id = "main"  # TODO: Config
            msg_id = email_id

        response = await self.http_client.get(
            f'{self.base_url}/v1/account/{account_id}/attachment/{attachment_id}',
            headers={'Authorization': f'Bearer {self.secret}'},
            timeout=60.0  # Timeout plus long pour download
        )

        if response.status_code != 200:
            raise Exception(f"EmailEngine download_attachment failed: {response.status_code}")

        return response.content


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
        self.db_pool: Optional[asyncpg.Pool] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.emailengine_client: Optional[EmailEngineClient] = None

    async def connect(self):
        """Connect to Redis and PostgreSQL"""
        # Redis
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)
        await self.redis.ping()
        logger.info("redis_connected")

        # PostgreSQL Pool (pour @friday_action + detect_vip/urgency)
        self.db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=5,
            max_size=20
        )
        logger.info("postgresql_pool_created", min_size=5, max_size=20)

        # Initialiser TrustManager avec le pool (requis pour @friday_action)
        init_trust_manager(db_pool=self.db_pool)
        logger.info("trust_manager_initialized")

        # HTTP client
        self.http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("http_client_created")

        # EmailEngine client wrapper (Story 2.4)
        self.emailengine_client = EmailEngineClient(
            http_client=self.http_client,
            base_url=EMAILENGINE_URL,
            secret=EMAILENGINE_SECRET
        )
        logger.info("emailengine_client_initialized")

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
        if self.db_pool:
            await self.db_pool.close()
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

            # Étape 1: Fetch email complet depuis EmailEngine (avec retry backoff)
            email_full = await self.fetch_email_from_emailengine(account_id, message_id, max_retries=6)

            if not email_full:
                logger.error("email_fetch_failed_max_retries", message_id=message_id)
                # Publier dans DLQ emails:failed
                await self.send_to_dlq(event_id, payload, error="EmailEngine fetch failed after 6 retries")
                # XACK pour retirer du PEL (échec définitif, en DLQ maintenant)
                await self.redis.xack(STREAM_NAME, CONSUMER_GROUP, event_id)
                return

            # Extraire données raw (AVANT anonymisation, pour stockage chiffré)
            from_raw = email_full.get('from', {}).get('address', 'unknown')
            from_name = email_full.get('from', {}).get('name', '')
            to_raw = ', '.join([addr.get('address', '') for addr in email_full.get('to', [])])
            subject_raw = email_full.get('subject', '(no subject)')
            body_text_raw = email_full.get('text', email_full.get('html', ''))

            # Étape 2: Anonymiser body complet
            body_anon = await anonymize_text(body_text_raw) if body_text_raw else ""

            logger.info("email_anonymized", message_id=message_id, body_length=len(body_anon))

            # Étape 2.5: Detection VIP + Urgence (Story 2.3)
            # Calcul hash email original (AVANT anonymisation)
            email_hash = compute_email_hash(from_raw)

            # Detection VIP via hash lookup
            vip_result = await detect_vip_sender(
                email_anon=from_anon,
                email_hash=email_hash,
                db_pool=self.db_pool,
            )
            is_vip = vip_result.payload["is_vip"]
            vip_data = vip_result.payload.get("vip")

            # Detection urgence multi-facteurs
            email_text = f"{subject_anon} {body_anon}"
            urgency_result = await detect_urgency(
                email_text=email_text,
                vip_status=is_vip,
                db_pool=self.db_pool,
            )
            is_urgent = urgency_result.payload["is_urgent"]
            urgency_score = urgency_result.confidence

            # Déterminer priority
            if is_urgent:
                priority = "urgent"
            elif is_vip:
                priority = "high"
            else:
                priority = "normal"

            logger.info(
                "vip_urgency_detected",
                message_id=message_id,
                is_vip=is_vip,
                is_urgent=is_urgent,
                urgency_score=urgency_score,
                priority=priority
            )

            # Étape 4: Classification stub (Day 1)
            # TODO Story 2.2: Remplacer par classification LLM réelle
            category = "inbox"
            confidence = 0.5

            # Étape 5: Stocker dans PostgreSQL (email anonymisé + email raw chiffré)
            email_id = await self.store_email_in_database(
                account_id=account_id,
                message_id=message_id,
                from_anon=from_anon,
                subject_anon=subject_anon,
                body_anon=body_anon,
                category=category,
                confidence=confidence,
                priority=priority,
                received_at=date_str,
                has_attachments=has_attachments,
                # Données raw pour stockage chiffré
                from_raw=f"{from_name} <{from_raw}>" if from_name else from_raw,
                to_raw=to_raw,
                subject_raw=subject_raw,
                body_raw=body_text_raw
            )

            # Étape 5.3: Extraction pièces jointes (Story 2.4 - Phase 4)
            # NOTE: Extraction APRÈS stockage DB pour avoir UUID email correct
            attachment_result = None
            if has_attachments:
                try:
                    # Extraire pièces jointes via EmailEngine
                    attachment_result = await extract_attachments(
                        email_id=str(email_id),  # UUID email depuis DB
                        db_pool=self.db_pool,
                        emailengine_client=self.emailengine_client,
                        redis_client=self.redis,
                    )

                    logger.info(
                        "attachments_extracted",
                        email_id=str(email_id),
                        message_id=message_id,
                        extracted_count=attachment_result.extracted_count,
                        failed_count=attachment_result.failed_count,
                        total_size_mb=attachment_result.total_size_mb
                    )

                except Exception as e:
                    logger.error(
                        "attachment_extraction_failed",
                        email_id=str(email_id),
                        message_id=message_id,
                        error=str(e)
                    )
                    # Continue quand même (email sans PJ)

            # Étape 5.5: Mettre à jour stats VIP si applicable
            if is_vip and vip_data:
                await update_vip_email_stats(
                    vip_id=vip_data["id"],
                    db_pool=self.db_pool
                )
                logger.info("vip_stats_updated", vip_id=vip_data["id"])

            # Étape 6: Notification Telegram email
            await self.send_telegram_notification(
                account_id=account_id,
                from_anon=from_anon,
                subject_anon=subject_anon,
                category=category,
                is_urgent=is_urgent,
                urgency_reasoning=urgency_result.reasoning if is_urgent else None
            )

            # Étape 6.5: Notification Telegram pièces jointes (Story 2.4)
            if attachment_result and attachment_result.extracted_count > 0:
                try:
                    await self.send_telegram_notification_attachments(
                        message_id=message_id,
                        from_anon=from_anon,
                        subject_anon=subject_anon,
                        attachment_result=attachment_result
                    )
                except Exception as e:
                    logger.error(
                        "telegram_attachment_notification_failed",
                        message_id=message_id,
                        error=str(e)
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
        message_id: str,
        max_retries: int = 6
    ) -> Optional[Dict]:
        """
        Fetch email complet depuis EmailEngine API avec retry backoff exponentiel

        Args:
            account_id: ID compte EmailEngine
            message_id: ID message
            max_retries: Nombre max de retries (défaut 6)

        Returns:
            Email JSON ou None si échec après retries

        Retry policy:
            - Backoff: 1s, 2s, 4s, 8s, 16s, 32s (total ~63s)
            - Max 6 retries
        """
        for attempt in range(max_retries + 1):
            try:
                response = await self.http_client.get(
                    f'{EMAILENGINE_URL}/v1/account/{account_id}/message/{message_id}',
                    headers={'Authorization': f'Bearer {EMAILENGINE_SECRET}'}
                )

                if response.status_code == 200:
                    if attempt > 0:
                        logger.info(
                            "emailengine_fetch_success_after_retry",
                            message_id=message_id,
                            attempt=attempt + 1
                        )
                    return response.json()
                else:
                    logger.error(
                        "emailengine_fetch_failed",
                        account_id=account_id,
                        message_id=message_id,
                        status_code=response.status_code,
                        attempt=attempt + 1
                    )

            except Exception as e:
                logger.error(
                    "emailengine_request_error",
                    message_id=message_id,
                    error=str(e),
                    attempt=attempt + 1
                )

            # Si pas encore au max retries, attendre avec backoff exponentiel
            if attempt < max_retries:
                backoff_seconds = 2 ** attempt  # 1s, 2s, 4s, 8s, 16s, 32s
                logger.info(
                    "emailengine_retry_backoff",
                    message_id=message_id,
                    attempt=attempt + 1,
                    next_retry_seconds=backoff_seconds
                )
                await asyncio.sleep(backoff_seconds)

        # Après max_retries tentatives, échec définitif
        logger.error(
            "emailengine_fetch_max_retries_exceeded",
            message_id=message_id,
            max_retries=max_retries
        )
        return None

    async def send_to_dlq(self, event_id: str, payload: Dict[str, str], error: str):
        """
        Envoyer événement échoué dans Dead-Letter Queue (DLQ)

        Args:
            event_id: ID de l'événement original
            payload: Payload original
            error: Message d'erreur
        """
        dlq_event = {
            **payload,
            'original_event_id': event_id,
            'error': error,
            'failed_at': datetime.utcnow().isoformat(),
            'retry_count': '6'  # Max retries atteint
        }

        try:
            dlq_id = await self.redis.xadd(STREAM_DLQ, dlq_event)
            logger.error(
                "email_sent_to_dlq",
                message_id=payload.get('message_id'),
                dlq_id=dlq_id,
                error=error
            )

            # Alerte Telegram topic System
            await self.send_telegram_alert_dlq(
                message_id=payload.get('message_id'),
                account_id=payload.get('account_id'),
                error=error
            )

        except Exception as e:
            logger.error("dlq_publish_failed", error=str(e), exc_info=True)

    async def send_telegram_alert_dlq(self, message_id: str, account_id: str, error: str):
        """Envoyer alerte Telegram pour email en DLQ"""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_SUPERGROUP_ID:
            logger.warning("telegram_not_configured_for_dlq_alert")
            return

        try:
            # Message d'alerte
            alert_text = (
                f"ALERTE Email echoue apres 6 retries\n\n"
                f"Account: {account_id}\n"
                f"Message ID: {message_id}\n"
                f"Erreur: {error}\n\n"
                f"L'email est dans la DLQ emails:failed"
            )

            # Envoyer vers topic System (TOPIC_SYSTEM_ID)
            topic_system_id = os.getenv('TOPIC_SYSTEM_ID')

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                    json={
                        'chat_id': TELEGRAM_SUPERGROUP_ID,
                        'message_thread_id': topic_system_id,
                        'text': alert_text,
                        'parse_mode': 'HTML'
                    }
                )

                if response.status_code == 200:
                    logger.info("dlq_alert_sent_telegram", message_id=message_id)
                else:
                    logger.error(
                        "dlq_alert_failed",
                        status_code=response.status_code,
                        response=response.text
                    )

        except Exception as e:
            logger.error("dlq_alert_exception", error=str(e))

    async def store_email_in_database(
        self,
        account_id: str,
        message_id: str,
        from_anon: str,
        subject_anon: str,
        body_anon: str,
        category: str,
        confidence: float,
        priority: str,
        received_at: str,
        has_attachments: bool,
        # Données raw pour stockage chiffré
        from_raw: str,
        to_raw: str,
        subject_raw: str,
        body_raw: str
    ) -> str:
        """
        Store email dans PostgreSQL ingestion.emails + ingestion.emails_raw (chiffré)

        Returns:
            email_id (UUID) de l'email inséré
        """
        async with self.db_pool.acquire() as conn:
            # Étape 1: Insérer email anonymisé dans ingestion.emails
            email_id = await conn.fetchval(
                """
                INSERT INTO ingestion.emails (
                    account_id, message_id, from_anon, subject_anon, body_anon,
                    category, confidence, priority, received_at, has_attachments
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (account_id, message_id) DO UPDATE SET
                    from_anon = EXCLUDED.from_anon,
                    subject_anon = EXCLUDED.subject_anon,
                    body_anon = EXCLUDED.body_anon,
                    category = EXCLUDED.category,
                    confidence = EXCLUDED.confidence,
                    priority = EXCLUDED.priority,
                    processed_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                account_id,
                message_id,
                from_anon,
                subject_anon,
                body_anon,
                category,
                confidence,
                priority,
                datetime.fromisoformat(received_at.replace('Z', '+00:00')),
                has_attachments
            )

            logger.info("email_stored_database", message_id=message_id, email_id=str(email_id), priority=priority)

            # Étape 2: Insérer email raw chiffré dans ingestion.emails_raw
            # Chiffrement pgcrypto avec EMAILENGINE_ENCRYPTION_KEY
            await conn.execute(
                """
                INSERT INTO ingestion.emails_raw (
                    email_id, from_encrypted, to_encrypted, subject_encrypted, body_encrypted
                ) VALUES (
                    $1,
                    pgp_sym_encrypt($2, $3),
                    pgp_sym_encrypt($4, $3),
                    pgp_sym_encrypt($5, $3),
                    pgp_sym_encrypt($6, $3)
                )
                ON CONFLICT (email_id) DO UPDATE SET
                    from_encrypted = EXCLUDED.from_encrypted,
                    to_encrypted = EXCLUDED.to_encrypted,
                    subject_encrypted = EXCLUDED.subject_encrypted,
                    body_encrypted = EXCLUDED.body_encrypted
                """,
                email_id,
                from_raw,
                EMAILENGINE_ENCRYPTION_KEY,
                to_raw,
                subject_raw,
                body_raw
            )

            logger.info("email_raw_stored_encrypted", message_id=message_id, email_id=str(email_id))

        return str(email_id)

    async def send_telegram_notification(
        self,
        account_id: str,
        from_anon: str,
        subject_anon: str,
        category: str,
        is_urgent: bool = False,
        urgency_reasoning: Optional[str] = None
    ):
        """Envoyer notification Telegram topic Email ou Actions si urgent"""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_SUPERGROUP_ID:
            logger.warning("telegram_not_configured_skip_notification")
            return

        # Si urgent, envoyer au topic Actions, sinon Email
        if is_urgent:
            if not TOPIC_ACTIONS_ID:
                logger.warning("topic_actions_not_configured_fallback_email")
                topic_id = TOPIC_EMAIL_ID
                topic_name = "Email"
            else:
                topic_id = TOPIC_ACTIONS_ID
                topic_name = "Actions"
        else:
            if not TOPIC_EMAIL_ID:
                logger.warning("topic_email_not_configured_skip_notification")
                return
            topic_id = TOPIC_EMAIL_ID
            topic_name = "Email"

        try:
            # Format message notification (sans emojis)
            if is_urgent:
                notification_text = (
                    f"EMAIL URGENT detecte\n\n"
                    f"Sujet : {subject_anon}\n"
                    f"De : {from_anon}\n"
                    f"Categorie : {category}\n"
                    f"Compte : {account_id}\n\n"
                    f"Raison urgence : {urgency_reasoning}"
                )
            else:
                notification_text = (
                    f"Nouvel email : {subject_anon}\n"
                    f"De : {from_anon}\n"
                    f"Categorie : {category}\n"
                    f"Compte : {account_id}"
                )

            # Envoyer vers topic approprié
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                    json={
                        'chat_id': TELEGRAM_SUPERGROUP_ID,
                        'message_thread_id': topic_id,
                        'text': notification_text,
                        'parse_mode': 'HTML'
                    },
                    timeout=10.0
                )

                if response.status_code == 200:
                    logger.info(
                        "telegram_notification_sent",
                        account_id=account_id,
                        category=category,
                        is_urgent=is_urgent,
                        topic=topic_name
                    )
                else:
                    logger.error(
                        "telegram_notification_failed",
                        status_code=response.status_code,
                        response=response.text[:200]
                    )

        except Exception as e:
            logger.error("telegram_notification_error", error=str(e))

    async def send_telegram_notification_attachments(
        self,
        message_id: str,
        from_anon: str,
        subject_anon: str,
        attachment_result: Any
    ):
        """
        Envoyer notification Telegram pour pièces jointes extraites (Story 2.4).

        Topic: TOPIC_EMAIL_ID (Email & Communications)

        Args:
            message_id: ID message email
            from_anon: Sender anonymisé
            subject_anon: Sujet anonymisé
            attachment_result: AttachmentExtractResult avec stats extraction
        """
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_SUPERGROUP_ID or not TOPIC_EMAIL_ID:
            logger.warning("telegram_not_configured_skip_attachment_notification")
            return

        try:
            # Format notification pièces jointes (AC6 Story 2.4)
            notification_text = (
                f"Pieces jointes extraites : {attachment_result.extracted_count}\n\n"
                f"Email : {subject_anon}\n"
                f"De : {from_anon}\n"
                f"Taille totale : {attachment_result.total_size_mb:.2f} Mo\n"
            )

            # Ajouter liste fichiers (max 5)
            if attachment_result.filepaths:
                fichiers = attachment_result.filepaths[:5]
                fichiers_text = "\n".join([f"- {Path(fp).name}" for fp in fichiers])
                notification_text += f"\nFichiers :\n{fichiers_text}"

                if len(attachment_result.filepaths) > 5:
                    remaining = len(attachment_result.filepaths) - 5
                    notification_text += f"\n... et {remaining} autre(s)"

            # Ajouter inline button [View Email] (AC6)
            keyboard = {
                "inline_keyboard": [[
                    {
                        "text": "View Email",
                        "url": f"https://mail.google.com/mail/u/0/#inbox/{message_id}"
                    }
                ]]
            }

            # Envoyer au topic Email
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                    json={
                        'chat_id': TELEGRAM_SUPERGROUP_ID,
                        'message_thread_id': TOPIC_EMAIL_ID,
                        'text': notification_text,
                        'parse_mode': 'HTML',
                        'reply_markup': keyboard
                    },
                    timeout=10.0
                )

                if response.status_code == 200:
                    logger.info(
                        "telegram_attachment_notification_sent",
                        message_id=message_id,
                        extracted_count=attachment_result.extracted_count,
                        topic="Email"
                    )
                else:
                    logger.error(
                        "telegram_attachment_notification_failed",
                        status_code=response.status_code,
                        response=response.text[:200]
                    )

        except Exception as e:
            logger.error("telegram_attachment_notification_error", error=str(e))


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
