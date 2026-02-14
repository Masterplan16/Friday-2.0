"""
Email Processor Consumer - Story 2.1 Task 3
Consumer Redis Streams pour traiter les événements email.received

Pipeline (D25: IMAP direct remplace EmailEngine):
    1. Fetch email complet via adapter IMAP direct
    2. Anonymiser body complet via Presidio
    3. Classification Claude Sonnet 4.5
    4. Stocker email dans PostgreSQL ingestion.emails
    5. Notification Telegram topic Email

Author: Claude Sonnet 4.5
Date: 2026-02-11 (D25 refactor: 2026-02-13)
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
from telegram import Bot  # M5 fix: Bot pour notifications Story 2.7

# Ajouter repo root au path
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))

from agents.src.adapters.email import get_email_adapter, EmailAdapter, EmailAdapterError
from agents.src.tools.anonymize import anonymize_text
from agents.src.agents.email.vip_detector import (
    compute_email_hash,
    detect_vip_sender,
    update_vip_email_stats,
)
from agents.src.agents.email.urgency_detector import detect_urgency
from agents.src.agents.email.attachment_extractor import extract_attachments
from agents.src.agents.email.classifier import classify_email  # A.5: Branche classifier
from agents.src.agents.email.draft_reply import draft_email_reply
from agents.src.agents.email.sender_filter import check_sender_filter  # Story 2.8 Task 5
from agents.src.middleware.trust import init_trust_manager

# ============================================
# Logging Setup
# ============================================

# Configure logging to stdout FIRST (critical for Docker logs capture)
logging.basicConfig(
    format="%(message)s",
    stream=sys.stdout,
    level=logging.INFO,
)

# Then configure structlog (will use logging.basicConfig as backend)
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
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_SUPERGROUP_ID = os.getenv('TELEGRAM_SUPERGROUP_ID')
TOPIC_EMAIL_ID = os.getenv('TOPIC_EMAIL_ID')
TOPIC_ACTIONS_ID = os.getenv('TOPIC_ACTIONS_ID')
PGP_ENCRYPTION_KEY = os.getenv('PGP_ENCRYPTION_KEY')

STREAM_NAME = 'emails:received'
STREAM_DLQ = 'emails:failed'
CONSUMER_GROUP = 'email-processor'
CONSUMER_NAME = f'consumer-{os.getpid()}'


# ============================================
# Adapter Compat Wrapper (D25: pour extract_attachments)
# ============================================

class AdapterEmailCompat:
    """
    Wrapper de compatibilite autour de EmailAdapter.
    Expose l'interface attendue par extract_attachments() (Story 2.4)
    qui attend get_message(message_id) et download_attachment(email_id, attachment_id).

    D25: Transitoire. A terme, extract_attachments sera refactore pour utiliser
    l'adapter directement.
    """

    def __init__(self, adapter: EmailAdapter, default_account_id: str = ""):
        self._adapter = adapter
        self._default_account = default_account_id

    async def get_message(self, message_id: str) -> Dict:
        """Compat: retourne un dict similaire a l'ancien format EmailEngine."""
        if '/' in message_id:
            account_id, msg_id = message_id.split('/', 1)
        else:
            account_id = self._default_account
            msg_id = message_id

        email_msg = await self._adapter.get_message(account_id, msg_id)
        # Convertir EmailMessage -> dict (format EmailEngine-like)
        return {
            'id': email_msg.message_id,
            'from': {'address': email_msg.from_address, 'name': email_msg.from_name},
            'to': [{'address': addr} for addr in email_msg.to_addresses],
            'subject': email_msg.subject,
            'text': email_msg.body_text,
            'html': email_msg.body_html,
            'date': email_msg.date,
            'attachments': email_msg.attachments,
        }

    async def download_attachment(self, email_id: str, attachment_id: str) -> bytes:
        """Compat: telecharge PJ via adapter."""
        if '/' in email_id:
            account_id, msg_id = email_id.split('/', 1)
        else:
            account_id = self._default_account
            msg_id = email_id

        return await self._adapter.download_attachment(account_id, msg_id, attachment_id)


# ============================================
# EmailProcessorConsumer Class
# ============================================

class EmailProcessorConsumer:
    """
    Consumer Redis Streams pour pipeline email

    Workflow:
        1. XREADGROUP sur stream email.received
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
        self.email_adapter: Optional[EmailAdapter] = None
        self.email_compat: Optional[AdapterEmailCompat] = None  # D25: compat wrapper
        self.bot: Optional[Bot] = None  # M5 fix: Bot Telegram pour notifications

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

        # HTTP client (pour Telegram notifications)
        self.http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("http_client_created")

        # Email adapter (D25: IMAP direct remplace EmailEngine)
        self.email_adapter = get_email_adapter()
        self.email_compat = AdapterEmailCompat(self.email_adapter)
        logger.info("email_adapter_initialized", provider=os.getenv("EMAIL_PROVIDER", "imap_direct"))

        # M5 fix: Bot Telegram pour notifications Story 2.7 (AC3 + AC4)
        telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if telegram_token:
            self.bot = Bot(token=telegram_token)
            logger.info("telegram_bot_initialized")
        else:
            logger.warning("TELEGRAM_BOT_TOKEN not set, task notifications disabled")

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

    async def _is_pipeline_enabled(self) -> bool:
        """Check kill switch in Redis (Phase A.0)"""
        enabled = await self.redis.get("friday:pipeline_enabled")
        # Default to env var PIPELINE_ENABLED if Redis key not set
        if enabled is None:
            return os.getenv("PIPELINE_ENABLED", "false").lower() == "true"
        # Redis returns bytes, decode before comparison
        enabled_str = enabled.decode('utf-8') if isinstance(enabled, bytes) else enabled
        return enabled_str == "true"

    async def start(self):
        """Start consumer loop"""
        logger.info("consumer_starting", group=CONSUMER_GROUP, consumer=CONSUMER_NAME)

        logger.info("entering_main_loop")

        while True:
            try:
                # Kill switch check (Phase A.0)
                pipeline_enabled = await self._is_pipeline_enabled()
                logger.info("pipeline_enabled_check", enabled=pipeline_enabled)

                if not pipeline_enabled:
                    logger.info("pipeline_disabled_sleeping", sleep_seconds=10)
                    await asyncio.sleep(10)
                    continue

                # XREADGROUP: Lire événements du stream
                logger.info("xreadgroup_calling", stream=STREAM_NAME, group=CONSUMER_GROUP)
                events = await self.redis.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=CONSUMER_NAME,
                    streams={STREAM_NAME: '>'},
                    count=10,
                    block=5000  # Block 5s si aucun événement
                )

                logger.info("xreadgroup_result", events_count=len(events) if events else 0)

                if not events:
                    continue  # Timeout, retry

                # Process each event
                for stream_name, messages in events:
                    logger.info("processing_messages", count=len(messages))
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

            # Étape 1: Fetch email complet via adapter (D25: IMAP direct)
            email_full = await self.fetch_email_with_retry(account_id, message_id, max_retries=6)

            if not email_full:
                logger.error("email_fetch_failed_max_retries", message_id=message_id)
                await self.send_to_dlq(event_id, payload, error="IMAP fetch failed after 6 retries")
                await self.redis.xack(STREAM_NAME, CONSUMER_GROUP, event_id)
                return

            # Extraire données raw depuis EmailMessage (AVANT anonymisation)
            from_raw = email_full.from_address
            from_name = email_full.from_name
            to_raw = ', '.join(email_full.to_addresses)
            subject_raw = email_full.subject or '(no subject)'
            body_text_raw = email_full.body_text or email_full.body_html or ''

            # Etape 2: Filtrage sender AVANT anonymisation (A.6 nouvelle semantique)
            # Semantique: blacklist=skip analyse, whitelist=analyser, VIP=prioritaire
            filter_result = await check_sender_filter(
                email_id=message_id,
                sender_email=from_raw,
                sender_domain=from_raw.split("@")[1] if "@" in from_raw else None,
                db_pool=self.db_pool,
            )

            is_vip_filter = False
            if filter_result and filter_result["filter_type"] == "vip":
                is_vip_filter = True
                logger.info(
                    "email_vip_detected_by_filter",
                    message_id=message_id,
                    sender=from_raw,
                )

            # Blacklist short-circuit: skip anonymisation, classification, tout
            if filter_result and filter_result["filter_type"] == "blacklist":
                category = "blacklisted"
                confidence = 1.0
                logger.info(
                    "email_filtered_blacklist",
                    message_id=message_id,
                    filter_type="blacklist",
                    tokens_saved=filter_result["tokens_saved_estimate"],
                )

                await self.redis.xadd('email.filtered', {
                    'message_id': message_id,
                    'account_id': account_id,
                    'filter_type': 'blacklist',
                    'category': category,
                    'confidence': str(confidence),
                })

                await self._log_filter_savings(message_id, "blacklist", category)

                # Store minimal in DB (body_anon vide, priority normal)
                email_id = await self.store_email_in_database(
                    account_id=account_id,
                    message_id=message_id,
                    from_anon=from_anon,
                    subject_anon=subject_anon,
                    body_anon="",
                    category=category,
                    confidence=confidence,
                    priority="normal",
                    received_at=date_str,
                    has_attachments=has_attachments,
                    from_raw=f"{from_name} <{from_raw}>" if from_name else from_raw,
                    to_raw=to_raw,
                    subject_raw=subject_raw,
                    body_raw=body_text_raw
                )

                # Pas de notification pour blacklist
                await self.redis.xack(STREAM_NAME, CONSUMER_GROUP, event_id)
                latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                logger.info(
                    "email_processed_filtered",
                    event_id=event_id,
                    message_id=message_id,
                    filter_type="blacklist",
                    latency_ms=int(latency_ms)
                )
                return  # Short-circuit: skip rest of pipeline

            # Etape 3: Anonymiser body complet
            body_anon = await anonymize_text(body_text_raw) if body_text_raw else ""

            logger.info("email_anonymized", message_id=message_id, body_length=len(body_anon))

            # Etape 3.5: Detection VIP + Urgence (Story 2.3)
            email_hash = compute_email_hash(from_raw)

            vip_result = await detect_vip_sender(
                email_anon=from_anon,
                email_hash=email_hash,
                db_pool=self.db_pool,
            )
            is_vip = is_vip_filter or vip_result.payload["is_vip"]
            vip_data = vip_result.payload.get("vip")

            email_text = f"{subject_anon} {body_anon}"
            urgency_result = await detect_urgency(
                email_text=email_text,
                vip_status=is_vip,
                db_pool=self.db_pool,
            )
            is_urgent = urgency_result.payload["is_urgent"]
            urgency_score = urgency_result.confidence

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

            # Etape 4: Classification via Claude Sonnet 4.5 (A.5)
            # VIP, whitelist, et non-liste passent tous par le classifier
            try:
                classification_result = await classify_email(
                    email_id=message_id,
                    email_text=f"{from_anon}\n{subject_anon}\n{body_anon}",
                    db_pool=self.db_pool,
                )
                category = classification_result.payload.get("category", "inconnu")
                confidence = classification_result.confidence
                logger.info(
                    "email_classified",
                    message_id=message_id,
                    category=category,
                    confidence=confidence,
                )
            except Exception as e:
                logger.error(
                    "email_classification_failed",
                    message_id=message_id,
                    error=str(e),
                )
                # Fallback si classifier echoue
                category = "inconnu"
                confidence = 0.0

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
                    # Extraire pièces jointes via adapter (D25: compat wrapper)
                    attachment_result = await extract_attachments(
                        email_id=str(email_id),  # UUID email depuis DB
                        db_pool=self.db_pool,
                        emailengine_client=self.email_compat,
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

            # Étape 6.7: Extraction tâches depuis email (Story 2.7 - Phase 5)
            # Conditions:
            # 1. Email classifié (category != spam)
            # 2. Tâches détectées avec confidence >=0.7
            # 3. Trust level = propose → Validation Telegram requise
            if category != "spam":
                try:
                    from agents.src.agents.email.task_extractor import extract_tasks_from_email
                    from agents.src.agents.email.task_creator import create_tasks_with_validation

                    # Extraire tâches via Claude Sonnet 4.5
                    extraction_result = await extract_tasks_from_email(
                        email_text=body_text_raw,
                        email_metadata={
                            'email_id': str(email_id),
                            'sender': from_raw,
                            'subject': subject_raw,
                            'category': category
                        }
                    )

                    # Filtrer par confidence >=0.7
                    valid_tasks = [
                        task for task in extraction_result.tasks_detected
                        if task.confidence >= 0.7
                    ]

                    if valid_tasks:
                        logger.info(
                            "tasks_detected_in_email",
                            email_id=str(email_id),
                            message_id=message_id,
                            tasks_count=len(valid_tasks),
                            confidence_overall=extraction_result.confidence_overall
                        )

                        # Créer tâches via @friday_action (trust=propose)
                        # M5 fix: Passer bot pour notifications dual-topic (AC3 + AC4)
                        bot = getattr(self, 'bot', None)  # Bot Telegram si disponible
                        await create_tasks_with_validation(
                            tasks=valid_tasks,
                            email_id=str(email_id),
                            email_subject=subject_raw,
                            db_pool=self.db_pool,
                            bot=bot  # M5 fix: Notifications Telegram Story 2.7
                        )
                    else:
                        logger.debug(
                            "email_no_task_detected",
                            email_id=str(email_id),
                            message_id=message_id,
                            confidence_overall=extraction_result.confidence_overall
                        )

                except Exception as e:
                    logger.error(
                        "task_extraction_failed",
                        email_id=str(email_id),
                        message_id=message_id,
                        error=str(e),
                        exc_info=True
                    )
                    # Ne pas bloquer le traitement email si extraction échoue

            # Étape 7: Génération brouillon réponse optionnel (Story 2.5 - Phase 7)
            # Conditions déclenchement :
            # 1. Email classifié professional/medical/academic (pas spam, pas perso urgent)
            # 2. Email pas de Mainteneur lui-même (éviter boucle)
            # 3. Optionnel Day 1 : peut être déclenché manuellement via /draft
            should_draft = (
                category in ('professional', 'medical', 'academic') and
                not self._is_from_mainteneur(from_raw)
            )

            if should_draft:
                try:
                    # Construire email_data pour draft_email_reply
                    email_data = {
                        'from': from_raw,
                        'from_anon': from_anon,
                        'to': to_raw,
                        'subject': subject_raw,
                        'subject_anon': subject_anon,
                        'body': body_text_raw,
                        'body_anon': body_anon,
                        'category': category,
                        'message_id': message_id,
                        'sender_email': from_raw,
                        'recipient_email': to_raw
                    }

                    # Appel draft_email_reply (async, avec @friday_action)
                    # Notification Telegram envoyée automatiquement via middleware
                    draft_result = await draft_email_reply(
                        email_id=str(email_id),
                        email_data=email_data,
                        db_pool=self.db_pool
                    )

                    logger.info(
                        "draft_reply_generated",
                        email_id=str(email_id),
                        message_id=message_id,
                        confidence=draft_result.confidence,
                        examples_used=draft_result.payload.get('style_examples_used', 0)
                    )

                except Exception as e:
                    logger.error(
                        "draft_reply_failed",
                        email_id=str(email_id),
                        message_id=message_id,
                        error=str(e),
                        exc_info=True
                    )
                    # Continue quand même (draft optionnel, échec ne bloque pas pipeline)

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

    async def fetch_email_with_retry(
        self,
        account_id: str,
        message_id: str,
        max_retries: int = 6
    ) -> Optional[Any]:
        """
        Fetch email complet via adapter IMAP avec retry backoff exponentiel (D25)

        Args:
            account_id: ID compte IMAP
            message_id: UID IMAP
            max_retries: Nombre max de retries (défaut 6)

        Returns:
            EmailMessage ou None si échec après retries

        Retry policy:
            - Backoff: 1s, 2s, 4s, 8s, 16s, 32s (total ~63s)
            - Max 6 retries
        """
        for attempt in range(max_retries + 1):
            try:
                result = await self.email_adapter.get_message(account_id, message_id)
                if attempt > 0:
                    logger.info(
                        "imap_fetch_success_after_retry",
                        message_id=message_id,
                        attempt=attempt + 1
                    )
                return result

            except EmailAdapterError as e:
                logger.error(
                    "imap_fetch_failed",
                    account_id=account_id,
                    message_id=message_id,
                    error=str(e),
                    attempt=attempt + 1
                )
            except Exception as e:
                logger.error(
                    "imap_request_error",
                    message_id=message_id,
                    error=str(e),
                    attempt=attempt + 1
                )

            if attempt < max_retries:
                backoff_seconds = 2 ** attempt
                logger.info(
                    "imap_retry_backoff",
                    message_id=message_id,
                    attempt=attempt + 1,
                    next_retry_seconds=backoff_seconds
                )
                await asyncio.sleep(backoff_seconds)

        logger.error(
            "imap_fetch_max_retries_exceeded",
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
                f"L'email est dans la DLQ email.failed"
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
            # Chiffrement pgcrypto avec PGP_ENCRYPTION_KEY
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
                PGP_ENCRYPTION_KEY,
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

    async def _log_filter_savings(self, message_id: str, filter_type: str, category: str):
        """
        Log economie tokens dans core.llm_usage (migration 034).
        """
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO core.llm_usage
                    (provider, model, input_tokens, output_tokens, cost_usd, context, tokens_saved_by_filters)
                    VALUES ('anthropic', 'filter_skip', 0, 0, 0, $1, $2)
                    """,
                    f"filter_{filter_type}",
                    1000,  # Estimation tokens economises
                )
        except Exception as e:
            logger.warning(
                "filter_savings_log_failed",
                message_id=message_id,
                error=str(e),
            )

    def _is_from_mainteneur(self, from_email: str) -> bool:
        """
        Vérifier si l'email provient du Mainteneur lui-même (Story 2.5)

        Évite boucle infinie draft -> envoi -> recu -> draft -> ...

        Lit la liste depuis la variable d'environnement MAINTENEUR_EMAILS
        (virgules comme séparateur). JAMAIS hardcodé dans le code.

        Args:
            from_email: Email expéditeur brut (peut inclure nom)

        Returns:
            True si email de Mainteneur, False sinon
        """
        mainteneur_emails_raw = os.getenv("MAINTENEUR_EMAILS", "")
        if not mainteneur_emails_raw:
            logger.warning("MAINTENEUR_EMAILS not configured, _is_from_mainteneur always False")
            return False

        mainteneur_emails = [
            e.strip().lower() for e in mainteneur_emails_raw.split(",") if e.strip()
        ]

        # Normaliser from_email (extraire email si format "Name <email>")
        email_lower = from_email.lower()

        # Check si un des emails Mainteneur est dans from_email
        return any(mainteneur_email in email_lower for mainteneur_email in mainteneur_emails)


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
