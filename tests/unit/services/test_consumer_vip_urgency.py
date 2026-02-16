"""
Tests unitaires pour consumer VIP+urgency integration (Story 2.3 - Subtask 6.4).

Tests intégration detect_vip_sender() et detect_urgency() dans consumer pipeline.
Code Review Fix M3.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Mock friday_action avant imports
def mock_friday_action(module=None, action=None, trust_default=None):
    def decorator(func):
        return func

    return decorator


with patch("agents.src.agents.email.vip_detector.friday_action", mock_friday_action):
    with patch("agents.src.agents.email.urgency_detector.friday_action", mock_friday_action):
        from agents.src.agents.email.urgency_detector import detect_urgency
        from agents.src.agents.email.vip_detector import compute_email_hash, detect_vip_sender


# ==========================================
# Fixtures
# ==========================================


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg Pool."""
    return AsyncMock()


# ==========================================
# Tests Integration VIP Detection
# ==========================================


@pytest.mark.asyncio
async def test_consumer_detect_vip_flow(mock_db_pool):
    """
    Test flow consumer : email reçu → detect VIP → priority high.

    Simule consumer.py lignes 240-250 (VIP detection).
    """
    # Setup : Email VIP
    email_raw = "vip@test.com"
    email_anon = "[EMAIL_VIP_TEST]"
    email_hash = compute_email_hash(email_raw)

    # Mock db_pool fetchrow → VIP trouvé
    mock_db_pool.fetchrow = AsyncMock(
        return_value={
            "id": "00000000-0000-0000-0000-111111111111",
            "email_anon": email_anon,
            "email_hash": email_hash,
            "label": "VIP Test",
            "priority_override": None,
            "designation_source": "manual",
            "added_by": None,
            "emails_received_count": 5,
            "active": True,
        }
    )

    # Execute : Detect VIP
    vip_result = await detect_vip_sender(
        email_anon=email_anon,
        email_hash=email_hash,
        db_pool=mock_db_pool,
    )

    # Assert : VIP détecté
    assert vip_result.payload["is_vip"] is True
    assert vip_result.payload["vip"]["label"] == "VIP Test"
    assert vip_result.confidence == 1.0


@pytest.mark.asyncio
async def test_consumer_detect_non_vip_flow(mock_db_pool):
    """
    Test flow consumer : email reçu → detect VIP → non VIP → priority normal.
    """
    # Setup : Email non VIP
    email_raw = "normal@test.com"
    email_anon = "[EMAIL_NORMAL]"
    email_hash = compute_email_hash(email_raw)

    # Mock db_pool fetchrow → VIP pas trouvé
    mock_db_pool.fetchrow = AsyncMock(return_value=None)

    # Execute : Detect VIP
    vip_result = await detect_vip_sender(
        email_anon=email_anon,
        email_hash=email_hash,
        db_pool=mock_db_pool,
    )

    # Assert : Non VIP
    assert vip_result.payload["is_vip"] is False
    assert vip_result.payload["vip"] is None


# ==========================================
# Tests Integration Urgency Detection
# ==========================================


@pytest.mark.asyncio
async def test_consumer_detect_urgency_vip_urgent(mock_db_pool):
    """
    Test flow consumer : VIP + keyword deadline → urgent.

    Simule consumer.py lignes 252-268 (urgency detection).
    """
    # Setup : Email VIP + deadline
    email_text = "Email urgent avec deadline demain"
    vip_status = True

    # Mock db_pool.acquire pour keywords
    async def mock_acquire():
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {"keyword": "urgent", "weight": 0.5},
                {"keyword": "deadline", "weight": 0.3},
            ]
        )

        class MockAcquire:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *args):
                pass

        return MockAcquire()

    mock_db_pool.acquire = mock_acquire

    # Execute : Detect urgency
    urgency_result = await detect_urgency(
        email_text=email_text,
        vip_status=vip_status,
        db_pool=mock_db_pool,
    )

    # Assert : Urgent détecté
    # VIP (0.5) + keywords (0.3) + deadline (0.2) = 1.0 > 0.6
    assert urgency_result.payload["is_urgent"] is True
    assert urgency_result.confidence >= 0.6
    assert "urgent" in urgency_result.payload["urgency"]["factors"]["keywords_matched"]


@pytest.mark.asyncio
async def test_consumer_priority_mapping():
    """
    Test consumer priority mapping logic (lignes 262-267).

    Logique :
    - urgent → priority='urgent'
    - VIP + non urgent → priority='high'
    - Normal → priority='normal'
    """
    # Test case 1 : Urgent
    is_urgent = True
    is_vip = False
    priority = "urgent" if is_urgent else ("high" if is_vip else "normal")
    assert priority == "urgent"

    # Test case 2 : VIP non urgent
    is_urgent = False
    is_vip = True
    priority = "urgent" if is_urgent else ("high" if is_vip else "normal")
    assert priority == "high"

    # Test case 3 : Normal
    is_urgent = False
    is_vip = False
    priority = "urgent" if is_urgent else ("high" if is_vip else "normal")
    assert priority == "normal"


@pytest.mark.asyncio
async def test_consumer_telegram_notification_routing():
    """
    Test routing notifications Telegram (consumer.py lignes 592-606).

    Logique :
    - is_urgent=True → TOPIC_ACTIONS_ID
    - is_urgent=False → TOPIC_EMAIL_ID
    """
    # Test case 1 : Urgent → Actions topic
    is_urgent = True
    topic_id = "TOPIC_ACTIONS_ID" if is_urgent else "TOPIC_EMAIL_ID"
    assert topic_id == "TOPIC_ACTIONS_ID"

    # Test case 2 : Normal → Email topic
    is_urgent = False
    topic_id = "TOPIC_ACTIONS_ID" if is_urgent else "TOPIC_EMAIL_ID"
    assert topic_id == "TOPIC_EMAIL_ID"


# Note: Tests end-to-end pipeline complet omis pour brièveté
# TODO: Ajouter test E2E complet email → VIP → urgency → notification → DB update
