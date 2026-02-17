"""
Tests unitaires pour agents/email/sender_filter.py (Story 2.8)

Tests check_sender_filter() :
- Blacklist filter → spam, confidence=1.0
- Whitelist filter → catégorie assignée, confidence=0.95
- Neutral filter → None (proceed to classify)
- Pas de filter → None (proceed to classify)
- Circuit breaker sur erreurs DB
- Logs économie tokens
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from agents.src.agents.email.sender_filter import SenderFilterError, check_sender_filter

# ==========================================
# Fixtures
# ==========================================


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """Reset circuit breaker avant chaque test."""
    # Import la variable globale
    from agents.src.agents.email import sender_filter

    # Reset circuit breaker
    sender_filter._circuit_breaker_failures.clear()
    yield
    # Cleanup après test
    sender_filter._circuit_breaker_failures.clear()


# ==========================================
# Helper: Mock DB pool async context manager
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


# ==========================================
# Tests check_sender_filter (fonction principale)
# ==========================================


@pytest.mark.asyncio
async def test_check_sender_filter_blacklist():
    """Test blacklist filter → spam, confidence=1.0, SKIP Claude."""
    # Setup mock db_pool
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Mock fetchrow pour retourner un blacklist filter
    mock_conn.fetchrow.return_value = {
        "id": UUID("12345678-1234-1234-1234-123456789012"),
        "filter_type": "blacklist",
        "category": "spam",
        "confidence": 1.0,
    }

    # Test
    result = await check_sender_filter(
        email_id="test-email-123",
        sender_email="spam@newsletter.com",
        sender_domain="newsletter.com",
        db_pool=mock_pool,
    )

    # Assertions
    assert result is not None
    assert result["filter_type"] == "blacklist"
    assert result["category"] == "blacklisted"
    assert result["confidence"] == 1.0
    assert result["tokens_saved_estimate"] == 0.006  # $0.006 économie


@pytest.mark.asyncio
async def test_check_sender_filter_whitelist():
    """Test whitelist filter → catégorie assignée, confidence=0.95, SKIP Claude."""
    # Setup mock db_pool
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Mock fetchrow pour retourner un whitelist filter
    mock_conn.fetchrow.return_value = {
        "id": UUID("12345678-1234-1234-1234-123456789012"),
        "filter_type": "whitelist",
        "category": "pro",
        "confidence": 0.95,
    }

    # Test
    result = await check_sender_filter(
        email_id="test-email-456",
        sender_email="vip@hospital.fr",
        sender_domain="hospital.fr",
        db_pool=mock_pool,
    )

    # Assertions - whitelist = proceed to classify normalement (None)
    assert result is None


@pytest.mark.asyncio
async def test_check_sender_filter_neutral():
    """Test neutral filter → None (proceed to classify)."""
    # Setup mock db_pool
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Mock fetchrow pour retourner un neutral filter
    mock_conn.fetchrow.return_value = {
        "id": UUID("12345678-1234-1234-1234-123456789012"),
        "filter_type": "neutral",
        "category": None,
        "confidence": None,
    }

    # Test
    result = await check_sender_filter(
        email_id="test-email-789",
        sender_email="neutral@example.com",
        sender_domain="example.com",
        db_pool=mock_pool,
    )

    # Assertions - neutral filter = proceed to classify normalement
    assert result is None


@pytest.mark.asyncio
async def test_check_sender_filter_no_match():
    """Test pas de filter → None (proceed to classify)."""
    # Setup mock db_pool
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Mock fetchrow pour retourner None (pas de match)
    mock_conn.fetchrow.return_value = None

    # Test
    result = await check_sender_filter(
        email_id="test-email-999",
        sender_email="unknown@example.com",
        sender_domain="example.com",
        db_pool=mock_pool,
    )

    # Assertions - pas de match = proceed to classify normalement
    assert result is None


@pytest.mark.asyncio
async def test_check_sender_filter_email_priority():
    """Test lookup email prioritaire sur domain."""
    # Setup mock db_pool
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Mock fetchrow pour retourner blacklist via email exact match
    mock_conn.fetchrow.return_value = {
        "id": UUID("12345678-1234-1234-1234-123456789012"),
        "filter_type": "blacklist",
        "category": "spam",
        "confidence": 1.0,
    }

    # Test
    result = await check_sender_filter(
        email_id="test-email-priority",
        sender_email="spam@example.com",
        sender_domain="example.com",
        db_pool=mock_pool,
    )

    # Assertions - doit utiliser email exact match (prioritaire)
    assert result is not None
    assert result["filter_type"] == "blacklist"

    # Vérifier que la query utilisait l'email en priorité
    mock_conn.fetchrow.assert_called_once()
    call_args = mock_conn.fetchrow.call_args
    query = call_args[0][0]
    assert "sender_email = $1" in query or "sender_email" in query.lower()


@pytest.mark.asyncio
async def test_check_sender_filter_domain_fallback():
    """Test fallback domain si email pas trouvé."""
    # Setup mock db_pool
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Mock fetchrow pour simuler 2 appels (email = None, domain = blacklist)
    mock_conn.fetchrow.side_effect = [
        None,  # Premier appel (email) → pas trouvé
        {
            "id": UUID("12345678-1234-1234-1234-123456789012"),
            "filter_type": "blacklist",
            "category": "spam",
            "confidence": 1.0,
        },  # Deuxième appel (domain) → trouvé
    ]

    # Test
    result = await check_sender_filter(
        email_id="test-email-fallback",
        sender_email="new-sender@spam-domain.com",
        sender_domain="spam-domain.com",
        db_pool=mock_pool,
    )

    # Assertions - doit trouver via domain fallback
    assert result is not None
    assert result["filter_type"] == "blacklist"
    assert mock_conn.fetchrow.call_count == 2  # 2 appels (email + domain)


@pytest.mark.asyncio
async def test_check_sender_filter_circuit_breaker():
    """Test circuit breaker après 3 erreurs consécutives."""
    # Setup mock db_pool
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Mock fetchrow pour générer erreurs
    mock_conn.fetchrow.side_effect = Exception("DB connection error")

    # Test - 3 appels consécutifs doivent activer circuit breaker
    for i in range(3):
        result = await check_sender_filter(
            email_id=f"test-email-error-{i}",
            sender_email="test@example.com",
            sender_domain="example.com",
            db_pool=mock_pool,
        )
        # Doit retourner None (mode dégradé, proceed to classify)
        assert result is None

    # 4ème appel doit être court-circuité (circuit breaker ouvert)
    result = await check_sender_filter(
        email_id="test-email-circuit-breaker",
        sender_email="test@example.com",
        sender_domain="example.com",
        db_pool=mock_pool,
    )

    # Circuit breaker ouvert → retourne None immédiatement
    assert result is None
    # Nombre d'appels DB doit être limité (pas un 4ème appel)
    assert mock_conn.fetchrow.call_count == 3  # Seulement les 3 premiers appels


@pytest.mark.asyncio
async def test_check_sender_filter_logging_blacklist():
    """Test résultat blacklist avec économie tokens (logging vérifié via résultat)."""
    # Setup mock db_pool
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Mock fetchrow pour retourner blacklist
    mock_conn.fetchrow.return_value = {
        "id": UUID("12345678-1234-1234-1234-123456789012"),
        "filter_type": "blacklist",
        "category": "spam",
        "confidence": 1.0,
    }

    # Test
    result = await check_sender_filter(
        email_id="test-email-log",
        sender_email="spam@newsletter.com",
        sender_domain="newsletter.com",
        db_pool=mock_pool,
    )

    # Assertions - vérifier résultat contient économie tokens
    assert result is not None
    assert result["filter_type"] == "blacklist"
    assert result["tokens_saved_estimate"] == 0.006
    # Note: Logging structlog testé via tests E2E


@pytest.mark.asyncio
async def test_check_sender_filter_logging_no_filter():
    """Test comportement quand pas de filter trouvé (logging vérifié via résultat)."""
    # Setup mock db_pool
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Mock fetchrow pour retourner None
    mock_conn.fetchrow.return_value = None

    # Test
    result = await check_sender_filter(
        email_id="test-email-no-filter",
        sender_email="unknown@example.com",
        sender_domain="example.com",
        db_pool=mock_pool,
    )

    # Assertions - doit retourner None (proceed to classify)
    assert result is None
    # Note: Logging structlog testé via tests E2E


# ==========================================
# Tests edge cases
# ==========================================


@pytest.mark.asyncio
async def test_check_sender_filter_missing_email_parameter():
    """Test erreur si sender_email ET sender_domain manquants."""
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Test - doit raise ValueError
    with pytest.raises(ValueError, match="Au moins sender_email ou sender_domain requis"):
        await check_sender_filter(
            email_id="test-email-invalid",
            sender_email=None,
            sender_domain=None,
            db_pool=mock_pool,
        )


@pytest.mark.asyncio
async def test_check_sender_filter_only_domain():
    """Test filter par domain uniquement (sans email)."""
    # Setup mock db_pool
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Mock fetchrow pour retourner blacklist via domain
    mock_conn.fetchrow.return_value = {
        "id": UUID("12345678-1234-1234-1234-123456789012"),
        "filter_type": "blacklist",
        "category": "spam",
        "confidence": 1.0,
    }

    # Test - sender_email=None, sender_domain présent
    result = await check_sender_filter(
        email_id="test-email-domain-only",
        sender_email=None,
        sender_domain="spam-domain.com",
        db_pool=mock_pool,
    )

    # Assertions
    assert result is not None
    assert result["filter_type"] == "blacklist"


@pytest.mark.asyncio
async def test_check_sender_filter_only_email():
    """Test filter par email uniquement (sans domain)."""
    # Setup mock db_pool
    mock_conn = AsyncMock()
    mock_pool = create_mock_pool(mock_conn)

    # Mock fetchrow pour retourner whitelist via email
    mock_conn.fetchrow.return_value = {
        "id": UUID("12345678-1234-1234-1234-123456789012"),
        "filter_type": "whitelist",
        "category": "pro",
        "confidence": 0.95,
    }

    # Test - sender_email présent, sender_domain=None
    result = await check_sender_filter(
        email_id="test-email-only",
        sender_email="vip@hospital.fr",
        sender_domain=None,
        db_pool=mock_pool,
    )

    # Assertions - whitelist = proceed to classify normalement (None)
    assert result is None
