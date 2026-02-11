"""
Gateway Webhooks Routes - Story 2.1 Task 2
Endpoint webhook pour EmailEngine → Gateway → Redis Streams

Endpoints:
    POST /api/v1/webhooks/emailengine/{account_id}
        - Reçoit webhook EmailEngine (nouvel email)
        - Valide signature HMAC-SHA256
        - Anonymise payload (Presidio)
        - Publie événement Redis Streams

Author: Claude Sonnet 4.5
Date: 2026-02-11
"""

import hmac
import hashlib
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Header, Request, Depends
from pydantic import BaseModel, Field
import redis.asyncio as redis

# Imports internes (paths relatifs depuis services/gateway/)
import sys
from pathlib import Path

# Ajouter repo root au path pour imports agents
repo_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(repo_root))

from agents.src.tools.anonymize import anonymize_text
from services.gateway.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


# ============================================
# Models Pydantic
# ============================================

class EmailEngineWebhookPayload(BaseModel):
    """Payload webhook EmailEngine - événement messageNew"""

    account: str = Field(..., description="Account ID EmailEngine")
    path: str = Field(..., description="IMAP path (ex: INBOX)")
    event: str = Field(..., description="Event type: messageNew")
    data: dict = Field(..., description="Message data")

    class Config:
        json_schema_extra = {
            "example": {
                "account": "account-medical",
                "path": "INBOX",
                "event": "messageNew",
                "data": {
                    "id": "msg_abc123",
                    "from": {"address": "user@example.com", "name": "John Doe"},
                    "subject": "Rendez-vous médical",
                    "date": "2026-02-11T10:30:00Z",
                    "attachments": [],
                    "text": "Bonjour, je confirme le rendez-vous..."
                }
            }
        }


class RedisEmailEvent(BaseModel):
    """Événement email.received publié dans Redis Streams (anonymisé)"""

    account_id: str
    message_id: str
    from_anon: str  # Anonymisé Presidio
    subject_anon: str  # Anonymisé Presidio
    date: str  # ISO8601
    has_attachments: bool
    body_preview_anon: str  # Premiers 500 chars anonymisés


# ============================================
# Dependencies
# ============================================

async def get_redis_client():
    """Dependency : Redis client pour publier événements"""
    settings = get_settings()
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        yield client
    finally:
        await client.close()


def verify_webhook_signature(
    payload_body: bytes,
    signature: Optional[str],
    secret: str
) -> bool:
    """
    Vérifie signature HMAC-SHA256 webhook EmailEngine

    Args:
        payload_body: Corps brut du webhook (bytes)
        signature: Header X-EE-Signature (hex)
        secret: WEBHOOK_SECRET partagé

    Returns:
        True si signature valide, False sinon
    """
    if not signature:
        logger.warning("Missing X-EE-Signature header")
        return False

    # Calculer signature attendue
    expected_signature = hmac.new(
        secret.encode('utf-8'),
        payload_body,
        hashlib.sha256
    ).hexdigest()

    # Comparaison timing-safe
    return hmac.compare_digest(signature, expected_signature)


# ============================================
# Routes
# ============================================

@router.post("/emailengine/{account_id}")
async def webhook_emailengine_message_new(
    account_id: str,
    request: Request,
    x_ee_signature: Optional[str] = Header(None, alias="X-EE-Signature"),
    redis_client: redis.Redis = Depends(get_redis_client)
):
    """
    Webhook EmailEngine - Nouvel email reçu (messageNew)

    Flow:
        1. Valider signature HMAC-SHA256
        2. Parser payload EmailEngine
        3. Anonymiser from/subject/body (Presidio)
        4. Publier événement Redis Streams "emails:received"
        5. Retourner 200 OK

    Security:
        - Signature HMAC-SHA256 obligatoire (X-EE-Signature header)
        - Secret partagé WEBHOOK_SECRET dans .env

    Args:
        account_id: ID du compte EmailEngine (account-medical, etc.)
        request: Request FastAPI (pour body brut)
        x_ee_signature: Header X-EE-Signature (HMAC-SHA256)
        redis_client: Client Redis (dependency)

    Returns:
        200 OK si succès, 401 si signature invalide, 500 si erreur
    """
    settings = get_settings()

    # Lire body brut (nécessaire pour vérifier signature)
    payload_body = await request.body()

    # Étape 1 : Vérifier signature HMAC-SHA256
    if not verify_webhook_signature(payload_body, x_ee_signature, settings.WEBHOOK_SECRET):
        logger.error(f"❌ Invalid webhook signature for account {account_id}")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parser JSON
    try:
        payload = EmailEngineWebhookPayload.parse_raw(payload_body)
    except Exception as e:
        logger.error(f"❌ Invalid webhook payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    # Vérifier que l'account_id correspond
    if payload.account != account_id:
        logger.warning(f"⚠️  Account mismatch: URL={account_id}, payload={payload.account}")
        # Continuer quand même (tolérance)

    # Vérifier que c'est bien un événement messageNew
    if payload.event != "messageNew":
        logger.info(f"ℹ️  Ignoring event {payload.event} for account {account_id}")
        return {"status": "ignored", "event": payload.event}

    # Extraire données email
    message_data = payload.data
    message_id = message_data.get("id", "unknown")
    from_raw = message_data.get("from", {}).get("address", "unknown")
    from_name = message_data.get("from", {}).get("name", "")
    subject_raw = message_data.get("subject", "(no subject)")
    date_raw = message_data.get("date", datetime.utcnow().isoformat())
    text_raw = message_data.get("text", message_data.get("html", ""))
    attachments = message_data.get("attachments", [])

    logger.info(
        f"📧 Received webhook: account={account_id}, message_id={message_id}, "
        f"from={from_raw}, subject={subject_raw[:50]}..."
    )

    # Étape 2 : Anonymiser from, subject, body (Presidio)
    try:
        # Anonymiser expéditeur
        from_combined = f"{from_name} <{from_raw}>" if from_name else from_raw
        from_anon = await anonymize_text(from_combined)

        # Anonymiser sujet
        subject_anon = await anonymize_text(subject_raw)

        # Anonymiser body preview (premiers 500 chars)
        body_preview = text_raw[:500] if text_raw else ""
        body_preview_anon = await anonymize_text(body_preview) if body_preview else ""

        logger.info(f"✅ Anonymized: from={from_anon}, subject={subject_anon[:50]}...")

    except Exception as e:
        logger.error(f"❌ Presidio anonymization failed: {e}")
        raise HTTPException(status_code=500, detail=f"Anonymization failed: {e}")

    # Étape 3 : Créer événement Redis
    event = RedisEmailEvent(
        account_id=account_id,
        message_id=message_id,
        from_anon=from_anon,
        subject_anon=subject_anon,
        date=date_raw,
        has_attachments=len(attachments) > 0,
        body_preview_anon=body_preview_anon
    )

    # Étape 4 : Publier dans Redis Streams "emails:received"
    try:
        event_id = await redis_client.xadd(
            "emails:received",
            event.dict()
        )

        logger.info(f"✅ Published to Redis Streams: event_id={event_id}")

    except Exception as e:
        logger.error(f"❌ Failed to publish to Redis Streams: {e}")
        raise HTTPException(status_code=500, detail=f"Redis publish failed: {e}")

    # Étape 5 : Retourner succès
    return {
        "status": "success",
        "account_id": account_id,
        "message_id": message_id,
        "event_id": event_id
    }


@router.get("/health")
async def webhooks_health():
    """Healthcheck endpoint pour webhooks"""
    return {"status": "ok", "service": "webhooks"}
