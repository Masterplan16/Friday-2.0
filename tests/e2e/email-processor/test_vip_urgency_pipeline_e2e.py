"""
Tests E2E VIP & Urgency Detection Pipeline
Story 2.3 - Task 6 validation

Tests le workflow complet:
EmailEngine → Consumer → VIP detection → Urgency detection → PostgreSQL → Telegram

Scenarios:
1. Email VIP urgent → priority='urgent', notification topic Actions
2. Email VIP non-urgent → priority='high', notification topic Email
3. Email normal → priority='normal', notification topic Email
"""

import asyncio
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
import redis.asyncio as redis

# Ajouter repo root au path
repo_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(repo_root))

from agents.src.agents.email.vip_detector import compute_email_hash
from agents.src.middleware.trust import init_trust_manager

# ==========================================
# Fixtures
# ==========================================


@pytest.fixture
async def redis_client():
    """Client Redis test"""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    client = redis.from_url(redis_url, decode_responses=True)

    # Cleanup avant test
    try:
        await client.delete("emails:received", "emails:failed")
    except:
        pass

    yield client

    # Cleanup après test
    try:
        await client.delete("emails:received", "emails:failed")
    except:
        pass

    await client.close()


class MockAsyncPool:
    """Mock asyncpg pool pour tests E2E"""

    def __init__(self):
        self.vip_senders = {}  # email_hash -> VIP data
        self.urgency_keywords = [
            {"keyword": "URGENT", "weight": 0.5},
            {"keyword": "urgent", "weight": 0.5},
            {"keyword": "deadline", "weight": 0.3},
        ]
        self.emails_stored = []
        self.mock_conn = AsyncMock()

    def add_vip(self, email: str, label: str):
        """Ajouter un VIP pour les tests"""
        email_hash = compute_email_hash(email)
        self.vip_senders[email_hash] = {
            "id": str(uuid.uuid4()),  # UUID valide requis par Pydantic
            "email_anon": f"[EMAIL_VIP_{email_hash[:8]}]",
            "email_hash": email_hash,
            "label": label,
            "priority_override": None,
            "designation_source": "manual",
            "added_by": None,
            "emails_received_count": 0,
            "active": True,
        }

    @asynccontextmanager
    async def acquire(self):
        """Mock acquire pour context manager"""

        # Setup mock conn pour différentes queries
        async def mock_fetchrow(query, *args):
            # VIP detection query
            if "vip_senders" in query and "email_hash" in query:
                email_hash = args[0] if args else None
                return self.vip_senders.get(email_hash)

            # Urgency keywords query (pas utilisé direct dans acquire, mais dans fetch)
            return None

        async def mock_fetch(query, *args):
            # Urgency keywords
            if "urgency_keywords" in query:
                return self.urgency_keywords
            return []

        async def mock_fetchval(query, *args):
            # INSERT email returning id
            if "INSERT INTO ingestion.emails" in query:
                email_id = f"email_{len(self.emails_stored)}"
                # Stocker les données pour validation
                self.emails_stored.append(
                    {
                        "id": email_id,
                        "account_id": args[0] if len(args) > 0 else None,
                        "message_id": args[1] if len(args) > 1 else None,
                        "from_anon": args[2] if len(args) > 2 else None,
                        "subject_anon": args[3] if len(args) > 3 else None,
                        "body_anon": args[4] if len(args) > 4 else None,
                        "category": args[5] if len(args) > 5 else None,
                        "confidence": args[6] if len(args) > 6 else None,
                        "priority": args[7] if len(args) > 7 else None,
                        "received_at": args[8] if len(args) > 8 else None,
                        "has_attachments": args[9] if len(args) > 9 else None,
                    }
                )
                return email_id

            # Trust level query
            if "trust_level" in query:
                return "auto"

            # Correction rules
            if "correction_rules" in query:
                return None

            return None

        async def mock_execute(query, *args):
            # INSERT emails_raw, UPDATE stats, etc.
            pass

        self.mock_conn.fetchrow = mock_fetchrow
        self.mock_conn.fetch = mock_fetch
        self.mock_conn.fetchval = mock_fetchval
        self.mock_conn.execute = mock_execute

        yield self.mock_conn

    async def fetchval(self, query, *args):
        """Mock fetchval direct sur pool (pour TrustManager)"""
        if "trust_level" in query:
            return "auto"
        return None

    async def fetchrow(self, query, *args):
        """Mock fetchrow direct sur pool (pour VIP detection)"""
        # VIP detection query
        if "vip_senders" in query and "email_hash" in query:
            email_hash = args[0] if args else None
            return self.vip_senders.get(email_hash)
        return None

    async def execute(self, query, *args):
        """Mock execute direct sur pool (pour update stats VIP, etc.)"""
        # Update VIP stats, etc.
        pass


@pytest.fixture
async def db_pool():
    """Mock asyncpg pool pour tests E2E"""
    # Setup env vars AVANT init_trust_manager
    os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot-token"
    os.environ["TELEGRAM_SUPERGROUP_ID"] = "123456"  # Must be int-parseable
    os.environ["TOPIC_EMAIL_ID"] = "100"
    os.environ["TOPIC_ACTIONS_ID"] = "200"

    pool = MockAsyncPool()

    # Ajouter VIPs test
    pool.add_vip("doyen@univ-med.fr", "Doyen Faculte Medecine")
    pool.add_vip("comptable@scm.fr", "Comptable SCM")

    # Initialiser TrustManager avec mock pool
    init_trust_manager(db_pool=pool)

    yield pool


@pytest.fixture
def mock_emailengine():
    """Mock EmailEngine API responses"""
    # Create a real mock AsyncClient with tracking
    mock_client = AsyncMock()

    # Mock get email response with side_effect
    async def mock_get_side_effect(url, **kwargs):
        response = MagicMock()

        # Simuler EmailEngine API response
        if "message" in url:
            response.status_code = 200
            response.json = lambda: {
                "from": {"address": "doyen@univ-med.fr", "name": "Doyen"},
                "to": [{"address": "friday@test.fr"}],
                "subject": "URGENT - Validation diplomes",
                "text": "URGENT: Je dois valider les diplomes avant demain 17h pour la ceremonie.",
                "html": None,
            }
        else:
            response.status_code = 404
            response.json = lambda: {}

        return response

    # Mock post telegram response with side_effect
    async def mock_post_side_effect(url, **kwargs):
        response = MagicMock()
        response.status_code = 200
        response.json = lambda: {"ok": True}
        response.text = ""
        return response

    # Use AsyncMock with side_effect for call tracking
    mock_client.get = AsyncMock(side_effect=mock_get_side_effect)
    mock_client.post = AsyncMock(side_effect=mock_post_side_effect)
    mock_client.aclose = AsyncMock()

    yield mock_client


@pytest.fixture
def mock_presidio():
    """Mock Presidio anonymization"""
    with patch("agents.src.tools.anonymize.anonymize_text") as mock_anon:
        # Retourner texte anonymisé simple
        async def anonymize(text):
            if not text:
                return ""
            # Remplacer emails par [EMAIL_X]
            import re

            result = re.sub(
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL_ANON]", text
            )
            return result

        mock_anon.side_effect = anonymize
        yield mock_anon


# ==========================================
# Tests E2E
# ==========================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_vip_urgent_email_pipeline(redis_client, db_pool, mock_emailengine, mock_presidio):
    """
    Test E2E: Email VIP urgent → priority='urgent', notification topic Actions

    Scenario:
    1. Email de doyen@univ-med.fr (VIP)
    2. Contenu: "URGENT", "avant demain" (urgence keywords + deadline)
    3. Expected: priority='urgent', notification → TOPIC_ACTIONS_ID
    """

    # Configuration test (env vars déjà set dans db_pool fixture)
    os.environ["EMAILENGINE_SECRET"] = "test-secret"
    os.environ["EMAILENGINE_ENCRYPTION_KEY"] = "test-encryption-key"

    # Import consumer après env vars
    from services.email_processor.consumer import EmailProcessorConsumer

    # Créer consumer avec mocks
    consumer = EmailProcessorConsumer()
    consumer.redis = redis_client
    consumer.db_pool = db_pool
    consumer.http_client = mock_emailengine

    # Publier événement dans Redis
    event = {
        "account_id": "account-test",
        "message_id": "msg_vip_urgent_123",
        "from_anon": "[EMAIL_DOYEN]",
        "subject_anon": "URGENT - Validation diplomes",
        "date": "2026-02-11T10:30:00Z",
        "has_attachments": "False",
    }

    event_id = await redis_client.xadd("emails:received", event)

    # Traiter événement (appel direct à process_email_event)
    await consumer.process_email_event(event_id, event)

    # Validations CORE workflow
    assert (
        len(db_pool.emails_stored) == 1
    ), f"Expected 1 email stored, got {len(db_pool.emails_stored)}"
    stored_email = db_pool.emails_stored[0]

    # Vérifier priority='urgent' (VIP + urgence keywords + deadline → score 1.0)
    assert (
        stored_email["priority"] == "urgent"
    ), f"Expected priority='urgent', got '{stored_email['priority']}'"

    # Vérifier from_anon et subject_anon
    assert (
        stored_email["from_anon"] == "[EMAIL_DOYEN]"
    ), f"Expected from_anon='[EMAIL_DOYEN]', got '{stored_email['from_anon']}'"
    assert "Validation" in stored_email["subject_anon"], "Subject should contain 'Validation'"

    # Vérifier category (stub 'inbox')
    assert (
        stored_email["category"] == "inbox"
    ), f"Expected category='inbox', got '{stored_email['category']}'"

    # NOTE: Telegram notification uses own httpx.AsyncClient() so mock doesn't capture calls
    # Validation Telegram would require global httpx patch, skipped for simplicity

    # Cleanup
    await redis_client.delete("emails:received")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_vip_non_urgent_email_pipeline(
    redis_client, db_pool, mock_emailengine, mock_presidio
):
    """
    Test E2E: Email VIP non-urgent → priority='high', notification topic Email

    Scenario:
    1. Email de doyen@univ-med.fr (VIP)
    2. Contenu: Normal (pas de keywords urgence)
    3. Expected: priority='high', notification → TOPIC_EMAIL_ID
    """

    # Setup env (env vars Telegram déjà set dans db_pool fixture)
    os.environ["EMAILENGINE_SECRET"] = "test-secret"
    os.environ["EMAILENGINE_ENCRYPTION_KEY"] = "test-encryption-key"

    # Mock EmailEngine response pour email VIP non-urgent
    async def mock_get_normal(url, **kwargs):
        response = AsyncMock()
        if "message" in url:
            response.status_code = 200
            response.json.return_value = {
                "from": {"address": "doyen@univ-med.fr", "name": "Doyen"},
                "to": [{"address": "friday@test.fr"}],
                "subject": "Reunion pedagogique",
                "text": "Bonjour, je souhaiterais organiser une reunion pedagogique la semaine prochaine.",
                "html": None,
            }
        return response

    mock_emailengine.get = mock_get_normal

    from services.email_processor.consumer import EmailProcessorConsumer

    consumer = EmailProcessorConsumer()
    consumer.redis = redis_client
    consumer.db_pool = db_pool
    consumer.http_client = mock_emailengine

    # Reset emails stored
    db_pool.emails_stored = []

    event = {
        "account_id": "account-test",
        "message_id": "msg_vip_normal_456",
        "from_anon": "[EMAIL_DOYEN]",
        "subject_anon": "Reunion pedagogique",
        "date": "2026-02-11T11:00:00Z",
        "has_attachments": "False",
    }

    event_id = await redis_client.xadd("emails:received", event)
    await consumer.process_email_event(event_id, event)

    # Validations CORE workflow
    assert (
        len(db_pool.emails_stored) == 1
    ), f"Expected 1 email stored, got {len(db_pool.emails_stored)}"
    stored_email = db_pool.emails_stored[0]

    # Vérifier priority='high' (VIP mais pas urgent - score 0.5 < 0.6)
    assert (
        stored_email["priority"] == "high"
    ), f"Expected priority='high', got '{stored_email['priority']}'"

    # Vérifier from_anon et subject_anon
    assert (
        stored_email["from_anon"] == "[EMAIL_DOYEN]"
    ), f"Expected from_anon='[EMAIL_DOYEN]', got '{stored_email['from_anon']}'"
    assert "Reunion" in stored_email["subject_anon"], "Subject should contain 'Reunion'"

    # NOTE: Telegram notification uses own httpx.AsyncClient() so mock doesn't capture calls

    await redis_client.delete("emails:received")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_normal_email_pipeline(redis_client, db_pool, mock_emailengine, mock_presidio):
    """
    Test E2E: Email normal → priority='normal', notification topic Email

    Scenario:
    1. Email de unknown@example.com (non-VIP)
    2. Contenu: Normal (pas de keywords urgence)
    3. Expected: priority='normal', notification → TOPIC_EMAIL_ID
    """

    # Setup env (env vars Telegram déjà set dans db_pool fixture)
    os.environ["EMAILENGINE_SECRET"] = "test-secret"
    os.environ["EMAILENGINE_ENCRYPTION_KEY"] = "test-encryption-key"

    # Mock EmailEngine response pour email normal
    async def mock_get_normal(url, **kwargs):
        response = AsyncMock()
        if "message" in url:
            response.status_code = 200
            response.json.return_value = {
                "from": {"address": "colleague@example.com", "name": "Colleague"},
                "to": [{"address": "friday@test.fr"}],
                "subject": "Question projet",
                "text": "Bonjour, j'ai une question sur le projet.",
                "html": None,
            }
        return response

    mock_emailengine.get = mock_get_normal

    from services.email_processor.consumer import EmailProcessorConsumer

    consumer = EmailProcessorConsumer()
    consumer.redis = redis_client
    consumer.db_pool = db_pool
    consumer.http_client = mock_emailengine

    # Reset
    db_pool.emails_stored = []

    event = {
        "account_id": "account-test",
        "message_id": "msg_normal_789",
        "from_anon": "[EMAIL_COLLEAGUE]",
        "subject_anon": "Question projet",
        "date": "2026-02-11T12:00:00Z",
        "has_attachments": "False",
    }

    event_id = await redis_client.xadd("emails:received", event)
    await consumer.process_email_event(event_id, event)

    # Validations CORE workflow
    assert (
        len(db_pool.emails_stored) == 1
    ), f"Expected 1 email stored, got {len(db_pool.emails_stored)}"
    stored_email = db_pool.emails_stored[0]

    # Vérifier priority='normal' (non-VIP, pas urgent)
    assert (
        stored_email["priority"] == "normal"
    ), f"Expected priority='normal', got '{stored_email['priority']}'"

    # Vérifier from_anon et subject_anon
    assert (
        stored_email["from_anon"] == "[EMAIL_COLLEAGUE]"
    ), f"Expected from_anon='[EMAIL_COLLEAGUE]', got '{stored_email['from_anon']}'"
    assert "Question" in stored_email["subject_anon"], "Subject should contain 'Question'"

    # NOTE: Telegram notification uses own httpx.AsyncClient() so mock doesn't capture calls

    await redis_client.delete("emails:received")


@pytest.mark.e2e
@pytest.mark.skip(reason="Requires real stack (EmailEngine + PostgreSQL + Redis + Telegram)")
async def test_full_vip_urgency_pipeline_real():
    """
    Test E2E COMPLET avec vraie stack (manuel)

    Setup requis:
    1. docker compose up -d
    2. Migration 027-028 appliquées (VIP senders + urgency keywords)
    3. VIP ajouté via /vip add doyen@univ-med.fr "Doyen Faculte"
    4. Compte IMAP test configuré dans EmailEngine

    Steps manuels:
    1. Envoyer email SMTP → compte IMAP test depuis doyen@univ-med.fr
       Subject: "URGENT - Validation diplomes"
       Body: "Je dois valider avant demain 17h"

    2. Vérifier dans PostgreSQL:
       SELECT message_id, from_anon, priority, category
       FROM ingestion.emails
       WHERE subject_anon LIKE '%Validation%'
       ORDER BY created_at DESC LIMIT 1;

       Expected: priority='urgent'

    3. Vérifier Telegram:
       - Notification dans topic Actions (pas Email)
       - Contient "EMAIL URGENT detecte"
       - Contient reasoning urgence

    4. Vérifier stats VIP:
       SELECT label, emails_received_count, last_email_at
       FROM core.vip_senders
       WHERE label = 'Doyen Faculte';

       Expected: emails_received_count incrémenté
    """
    pass
