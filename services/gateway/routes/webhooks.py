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
from aiobreaker import CircuitBreaker
from slowapi import Limiter
from slowapi.util import get_remote_address

from config import get_settings

# Import lazy de anonymize_text pour éviter conflit de noms
# (le config.py gateway masque le package config/ des agents)
_anonymize_text = None


def _get_anonymize_text():
    """Import lazy de anonymize_text depuis agents (résout conflit config.py vs config/)"""
    global _anonymize_text
    if _anonymize_text is not None:
        return _anonymize_text

    import sys
    from pathlib import Path

    # En container Docker: ./agents/src monté sur /agents
    # En dev local: repo_root/agents/src
    agents_path = Path("/agents")
    if agents_path.is_dir():
        search_path = str(agents_path)
    else:
        repo_root = Path(__file__).parent.parent.parent.parent
        search_path = str(repo_root / "agents" / "src")

    # Temporairement insérer le path agents EN PREMIER pour que
    # config/ (package agents) prenne priorité sur config.py (gateway)
    old_path = sys.path.copy()
    sys.path.insert(0, search_path)
    try:
        from tools.anonymize import anonymize_text
        _anonymize_text = anonymize_text
    finally:
        sys.path[:] = old_path

    return _anonymize_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

# Rate limiter: 100 requêtes par minute par IP
limiter = Limiter(key_func=get_remote_address)

# Circuit breaker: open après 5 échecs, half-open après 30s
webhook_circuit_breaker = CircuitBreaker(
    fail_max=5,
    timeout_duration=30,
    expected_exception=Exception
)

# Limite taille body webhook (10 MB max)
MAX_WEBHOOK_BODY_SIZE = 10 * 1024 * 1024  # 10 MB


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
@limiter.limit("100/minute")  # Rate limiting: 100 req/min par IP
async def webhook_emailengine_message_new(
    account_id: str,
    request: Request,
    x_ee_signature: Optional[str] = Header(None, alias="X-EE-Signature"),
    redis_client: redis.Redis = Depends(get_redis_client)
):
    """
    Webhook EmailEngine - Nouvel email reçu (messageNew)

    Flow:
        1. Valider taille body (<10MB)
        2. Valider signature HMAC-SHA256
        3. Parser payload EmailEngine
        4. Anonymiser from/subject/body (Presidio)
        5. Publier événement Redis Streams "emails:received" (via circuit breaker)
        6. Retourner 200 OK

    Security:
        - Signature HMAC-SHA256 obligatoire (X-EE-Signature header)
        - Secret partagé WEBHOOK_SECRET dans .env
        - Rate limiting: 100 req/min par IP
        - Body size limit: 10 MB max
        - Circuit breaker: fail-fast si Redis down

    Args:
        account_id: ID du compte EmailEngine (account-medical, etc.)
        request: Request FastAPI (pour body brut)
        x_ee_signature: Header X-EE-Signature (HMAC-SHA256)
        redis_client: Client Redis (dependency)

    Returns:
        200 OK si succès, 401 si signature invalide, 413 si body trop gros, 500 si erreur
    """
    settings = get_settings()

    # Étape 0 : Vérifier taille body (protection DoS)
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_WEBHOOK_BODY_SIZE:
        logger.error(
            "webhook_body_too_large",
            account_id=account_id,
            size_bytes=int(content_length),
            max_bytes=MAX_WEBHOOK_BODY_SIZE
        )
        raise HTTPException(status_code=413, detail="Request body too large (max 10 MB)")

    # Lire body brut (nécessaire pour vérifier signature)
    payload_body = await request.body()

    # Vérifier taille réelle après lecture
    if len(payload_body) > MAX_WEBHOOK_BODY_SIZE:
        logger.error(
            "webhook_body_too_large",
            account_id=account_id,
            size_bytes=len(payload_body),
            max_bytes=MAX_WEBHOOK_BODY_SIZE
        )
        raise HTTPException(status_code=413, detail="Request body too large (max 10 MB)")

    # Étape 1 : Vérifier signature HMAC-SHA256
    if not verify_webhook_signature(payload_body, x_ee_signature, settings.WEBHOOK_SECRET):
        logger.error("webhook_signature_invalid", account_id=account_id)
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parser JSON
    try:
        payload = EmailEngineWebhookPayload.parse_raw(payload_body)
    except Exception as e:
        logger.error("webhook_payload_invalid", account_id=account_id, error=str(e))
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    # Vérifier que l'account_id correspond (strict validation)
    if payload.account != account_id:
        logger.error(
            "webhook_account_mismatch",
            url_account=account_id,
            payload_account=payload.account
        )
        raise HTTPException(
            status_code=400,
            detail=f"Account mismatch: URL={account_id}, payload={payload.account}"
        )

    # Vérifier que c'est bien un événement messageNew
    if payload.event != "messageNew":
        logger.info("webhook_event_ignored", account_id=account_id, event=payload.event)
        return {"status": "ignored", "event": payload.event}

    # Extraire données email (PAS de log avant anonymisation!)
    message_data = payload.data
    message_id = message_data.get("id", "unknown")
    from_raw = message_data.get("from", {}).get("address", "unknown")
    from_name = message_data.get("from", {}).get("name", "")
    subject_raw = message_data.get("subject", "(no subject)")
    date_raw = message_data.get("date", datetime.utcnow().isoformat())
    text_raw = message_data.get("text", message_data.get("html", ""))
    attachments = message_data.get("attachments", [])

    # Étape 2 : Anonymiser from, subject, body (Presidio)
    try:
        # Anonymiser expéditeur
        from_combined = f"{from_name} <{from_raw}>" if from_name else from_raw
        anonymize = _get_anonymize_text()
        from_anon = await anonymize(from_combined)

        # Anonymiser sujet
        subject_anon = await anonymize(subject_raw)

        # Anonymiser body preview (premiers 500 chars)
        body_preview = text_raw[:500] if text_raw else ""
        body_preview_anon = await anonymize(body_preview) if body_preview else ""

        # Log APRÈS anonymisation (pas de PII)
        logger.info(
            "webhook_received",
            account_id=account_id,
            message_id=message_id,
            from_anon=from_anon[:50],
            subject_anon=subject_anon[:50]
        )

        logger.info(
            "presidio_anonymized",
            message_id=message_id,
            from_length=len(from_anon),
            subject_length=len(subject_anon)
        )

    except Exception as e:
        logger.error("presidio_anonymization_failed", message_id=message_id, error=str(e))
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

    # Étape 4 : Publier dans Redis Streams "emails:received" (via circuit breaker)
    try:
        # Circuit breaker protège contre Redis down
        async def publish_to_redis():
            return await redis_client.xadd("emails:received", event.dict())

        event_id = await webhook_circuit_breaker.call_async(publish_to_redis)

        logger.info("redis_event_published", event_id=event_id, message_id=message_id)

    except Exception as e:
        logger.error("redis_publish_failed", message_id=message_id, error=str(e))
        # Si circuit breaker open, quand même retourner 200 (webhook retenté par EmailEngine)
        if webhook_circuit_breaker.opened:
            logger.warning(
                "circuit_breaker_open",
                message_id=message_id,
                fail_count=webhook_circuit_breaker.fail_counter
            )
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
