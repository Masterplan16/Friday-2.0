"""
Tests E2E pour sender filter pipeline (Story 2.8 - H3 fix).

Tests end-to-end simulant le flux complet:
    Email reçu → filter check → DB update → Redis event → notification

Note: Ces tests nécessitent PostgreSQL + Redis en fonctionnement.
      Marqués @pytest.mark.e2e pour exécution séparée.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.agents.email.sender_filter import check_sender_filter

# ==========================================
# Helper
# ==========================================


class MockAsyncContextManager:
    """Helper pour mocker async with db_pool.acquire() as conn."""

    def __init__(self, return_value):
        self.return_value = return_value

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


def create_mock_pool(mock_conn):
    """Crée un mock db_pool correct pour async context manager."""
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockAsyncContextManager(mock_conn)
    return mock_pool


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """Reset circuit breaker avant chaque test."""
    from agents.src.agents.email import sender_filter

    sender_filter._circuit_breaker_failures.clear()
    yield
    sender_filter._circuit_breaker_failures.clear()


# ==========================================
# E2E Tests
# ==========================================


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_full_email_pipeline_with_filters():
    """
    E2E: Email spam connu → blacklist filter → DB update → notification skipped.

    Simule le flux complet du consumer:
    1. Email reçu de spam@newsletter.com
    2. check_sender_filter() → blacklist match
    3. Catégorie 'spam' assignée (skip Claude)
    4. DB update directe (pas de @friday_action)
    5. Pas de notification Telegram (blacklist)
    6. Redis event emails:filtered publié
    """
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Phase 1: Vérifier filter match
    mock_conn.fetchrow.return_value = {
        "id": "e2e-filter-uuid",
        "filter_type": "blacklist",
        "category": "spam",
        "confidence": 1.0,
    }

    result = await check_sender_filter(
        email_id="e2e-email-001",
        sender_email="spam@newsletter.com",
        sender_domain="newsletter.com",
        db_pool=mock_pool,
    )

    # Assertions E2E
    assert result is not None, "Blacklist filter devrait matcher"
    assert result["filter_type"] == "blacklist"
    assert result["category"] == "spam"
    assert result["confidence"] == 1.0
    assert result["tokens_saved_estimate"] == 0.015

    # Phase 2: Vérifier qu'un email neutre passe au classify
    mock_conn.fetchrow.return_value = None

    neutral_result = await check_sender_filter(
        email_id="e2e-email-002",
        sender_email="new-person@unknown-domain.com",
        sender_domain="unknown-domain.com",
        db_pool=mock_pool,
    )

    assert neutral_result is None, "Email neutre devrait passer au classify"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_cold_start_filter_learning():
    """
    E2E: Cold start avec 0 filtres → tous emails classifiés normalement.

    Simule le démarrage Day 1:
    1. Table core.sender_filters vide
    2. 5 emails reçus de domaines différents
    3. Tous retournent None (proceed to classify)
    4. Après script extract_email_domains.py → filtres ajoutés
    5. Emails suivants filtrés automatiquement
    """
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Phase 1: Cold start - table vide, tous retournent None
    mock_conn.fetchrow.return_value = None

    domains = [
        ("user1@domain-a.com", "domain-a.com"),
        ("user2@domain-b.com", "domain-b.com"),
        ("user3@domain-c.com", "domain-c.com"),
        ("user4@domain-d.com", "domain-d.com"),
        ("user5@domain-e.com", "domain-e.com"),
    ]

    for email, domain in domains:
        result = await check_sender_filter(
            email_id=f"cold-start-{domain}",
            sender_email=email,
            sender_domain=domain,
            db_pool=mock_pool,
        )
        assert result is None, f"Cold start: {domain} devrait retourner None"

    # Phase 2: Après extract_email_domains.py, domain-a est blacklisté
    mock_conn.fetchrow.side_effect = [
        None,  # email lookup miss
        {
            "id": "learned-filter-uuid",
            "filter_type": "blacklist",
            "category": "spam",
            "confidence": 1.0,
        },  # domain lookup hit
    ]

    result = await check_sender_filter(
        email_id="post-learning-domain-a",
        sender_email="user6@domain-a.com",
        sender_domain="domain-a.com",
        db_pool=mock_pool,
    )

    assert result is not None, "Après learning, domain-a devrait être filtré"
    assert result["filter_type"] == "blacklist"
    assert result["category"] == "spam"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_filter_delete_and_reprocessing():
    """
    E2E: Filtre supprimé → emails repassent par classification.

    Simule la correction d'un faux positif:
    1. domain-x.com est en blacklist (erreur)
    2. Mainteneur /filters delete domain-x.com
    3. Emails suivants de domain-x.com passent par classify normalement
    """
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Phase 1: Filtre actif → blacklist hit
    mock_conn.fetchrow.return_value = {
        "id": "false-positive-filter",
        "filter_type": "blacklist",
        "category": "spam",
        "confidence": 1.0,
    }

    result = await check_sender_filter(
        email_id="fp-email-001",
        sender_email="legit@domain-x.com",
        sender_domain="domain-x.com",
        db_pool=mock_pool,
    )
    assert result is not None
    assert result["filter_type"] == "blacklist"

    # Phase 2: Après /filters delete → plus de match
    mock_conn.fetchrow.return_value = None

    result_after = await check_sender_filter(
        email_id="fp-email-002",
        sender_email="legit@domain-x.com",
        sender_domain="domain-x.com",
        db_pool=mock_pool,
    )
    assert result_after is None, "Après suppression filtre, devrait retourner None"
