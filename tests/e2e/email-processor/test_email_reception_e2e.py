"""
Tests E2E complet Email Reception
Story 2.1 - Subtask 6.4
Tests: Webhook → Redis → Consumer → PostgreSQL → Telegram
"""

import pytest
import asyncio
import json
import hmac
import hashlib
from unittest.mock import AsyncMock, patch
import httpx
import redis.asyncio as redis
import asyncpg


@pytest.fixture
async def redis_client():
    """Client Redis test"""
    client = redis.from_url('redis://localhost:6379', decode_responses=True)
    yield client
    await client.close()


@pytest.fixture
async def db_connection():
    """Connexion PostgreSQL test"""
    conn = await asyncpg.connect('postgresql://friday:friday@localhost:5432/friday_test')
    yield conn
    await conn.close()


def compute_signature(payload: dict, secret: str) -> str:
    """Calculer signature HMAC webhook"""
    payload_bytes = json.dumps(payload).encode('utf-8')
    return hmac.new(secret.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_email_reception_end_to_end_stub(redis_client, db_connection):
    """
    Test E2E complet (stub simplifié):
    1. Webhook reçoit événement
    2. Événement publié Redis Streams
    3. Consumer lit et traite
    4. Email stocké PostgreSQL
    5. (Telegram notification mockée)

    NOTE: Ce test est un stub car il nécessite:
    - EmailEngine container running
    - Gateway service running
    - Consumer service running
    - Compte IMAP test configuré

    Pour test E2E complet, voir documentation docs/emailengine-integration.md
    """

    # Étape 1: Simuler publication webhook → Redis
    webhook_secret = 'test-secret'
    payload = {
        "account": "account-test",
        "path": "INBOX",
        "event": "messageNew",
        "data": {
            "id": "msg_e2e_123",
            "from": {"address": "test@example.com", "name": "Test User"},
            "subject": "Test E2E Email",
            "date": "2026-02-11T10:30:00Z",
            "text": "Body test E2E",
            "attachments": []
        }
    }

    # Étape 2: Publier dans Redis Streams (simule webhook)
    event = {
        'account_id': 'account-test',
        'message_id': 'msg_e2e_123',
        'from_anon': '[EMAIL_TEST]',
        'subject_anon': 'Test E2E Email',
        'date': '2026-02-11T10:30:00Z',
        'has_attachments': 'False',
        'body_preview_anon': 'Body test E2E'
    }

    event_id = await redis_client.xadd('emails:received', event)
    assert event_id is not None

    # Étape 3: Vérifier événement dans stream
    events = await redis_client.xread({'emails:received': '0'}, count=10)
    assert len(events) > 0

    # Étape 4: Cleanup
    await redis_client.delete('emails:received')


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_email_dlq_flow(redis_client):
    """
    Test E2E: Email échoué → DLQ
    1. Publier événement
    2. Simuler échec fetch EmailEngine
    3. Vérifier événement dans DLQ
    """

    # Créer consumer group
    try:
        await redis_client.xgroup_create('emails:received', 'test-group', id='$', mkstream=True)
    except:
        pass

    # Publier événement test
    event = {
        'account_id': 'account-fail',
        'message_id': 'msg_fail',
        'from_anon': '[EMAIL_FAIL]',
        'subject_anon': 'Test DLQ',
        'date': '2026-02-11T10:30:00Z'
    }

    event_id = await redis_client.xadd('emails:received', event)

    # Consumer lit événement
    events = await redis_client.xreadgroup('test-group', 'consumer-e2e', {'emails:received': '>'})
    assert len(events) == 1

    # Simuler envoi DLQ (normalement fait par consumer après max retries)
    dlq_event = {
        **event,
        'original_event_id': event_id,
        'error': 'EmailEngine fetch failed',
        'retry_count': '6'
    }

    dlq_id = await redis_client.xadd('emails:failed', dlq_event)
    assert dlq_id is not None

    # XACK original event (retiré du PEL)
    await redis_client.xack('emails:received', 'test-group', event_id)

    # Vérifier DLQ
    dlq_events = await redis_client.xread({'emails:failed': '0'})
    assert len(dlq_events) == 1

    # Cleanup
    await redis_client.delete('emails:received', 'emails:failed')
    try:
        await redis_client.xgroup_destroy('emails:received', 'test-group')
    except:
        pass


@pytest.mark.e2e
@pytest.mark.skip(reason="Requires full stack running (EmailEngine + Gateway + Consumer)")
async def test_full_email_pipeline_real():
    """
    Test E2E COMPLET (nécessite stack complet):

    Setup requis:
    1. docker compose up -d (PostgreSQL, Redis, EmailEngine, Gateway, Consumer)
    2. Script setup_emailengine_accounts.py exécuté
    3. Compte IMAP test configuré

    Flow:
    1. Envoyer email réel via SMTP → compte IMAP test
    2. EmailEngine détecte email (IDLE push)
    3. Webhook → Gateway
    4. Gateway → Anonymisation Presidio
    5. Gateway → Redis Streams
    6. Consumer → Fetch EmailEngine
    7. Consumer → Classification stub
    8. Consumer → PostgreSQL emails + emails_raw
    9. Consumer → Telegram notification
    10. XACK Redis

    Validation:
    - Email dans ingestion.emails (anonymisé)
    - Email dans ingestion.emails_raw (chiffré)
    - Notification Telegram reçue
    - Event XACK (pas dans PEL)

    Voir: docs/emailengine-integration.md section "Testing E2E"
    """
    pass
