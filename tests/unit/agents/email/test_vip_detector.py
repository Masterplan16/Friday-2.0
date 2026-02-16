"""
Tests unitaires pour agents/email/vip_detector.py

Tests de détection VIP via hash SHA256 et helpers.
Story 2.3 - Detection VIP & Urgence
"""

import hashlib
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest


# Mock friday_action decorator to bypass TrustManager in unit tests
def mock_friday_action(module=None, action=None, trust_default=None):
    """Mock decorator that returns function unchanged."""

    def decorator(func):
        return func

    return decorator


# Apply mock before importing detect_vip_sender
with patch("agents.src.agents.email.vip_detector.friday_action", mock_friday_action):
    from agents.src.agents.email.vip_detector import (
        VIPDetectorError,
        compute_email_hash,
        detect_vip_sender,
        update_vip_email_stats,
    )
    from agents.src.models.vip_detection import VIPSender


# ==========================================
# Tests compute_email_hash (helper)
# ==========================================


def test_compute_email_hash_basic():
    """Test calcul hash SHA256 basique."""
    email = "doyen@univ.fr"
    hash_result = compute_email_hash(email)

    # Vérifier format (64 caractères hex)
    assert len(hash_result) == 64
    assert all(c in "0123456789abcdef" for c in hash_result)


def test_compute_email_hash_normalization():
    """Test que la normalisation (lowercase + strip) fonctionne."""
    # Ces 3 variantes doivent produire le même hash
    email1 = "doyen@univ.fr"
    email2 = "Doyen@Univ.FR"
    email3 = "  doyen@univ.fr  "

    hash1 = compute_email_hash(email1)
    hash2 = compute_email_hash(email2)
    hash3 = compute_email_hash(email3)

    assert hash1 == hash2 == hash3


def test_compute_email_hash_different_emails():
    """Test que des emails différents produisent des hash différents."""
    hash1 = compute_email_hash("doyen@univ.fr")
    hash2 = compute_email_hash("comptable@scm.fr")

    assert hash1 != hash2


def test_compute_email_hash_deterministic():
    """Test que le hash est déterministe (même input → même output)."""
    email = "test@example.com"

    hash1 = compute_email_hash(email)
    hash2 = compute_email_hash(email)

    assert hash1 == hash2


# ==========================================
# Tests detect_vip_sender (fonction principale)
# ==========================================


@pytest.mark.asyncio
async def test_detect_vip_sender_found():
    """Test détection VIP trouvé dans la base."""
    # Mock db_pool avec VIP trouvé
    mock_pool = AsyncMock()
    vip_id = "123e4567-e89b-12d3-a456-426614174000"
    mock_pool.fetchrow.return_value = {
        "id": UUID(vip_id),
        "email_anon": "[EMAIL_DOYEN_123]",
        "email_hash": "a" * 64,
        "label": "Doyen Faculté Médecine",
        "priority_override": "urgent",
        "designation_source": "manual",
        "added_by": UUID("987e6543-e21b-98d7-b654-321098765432"),
        "emails_received_count": 42,
        "active": True,
    }

    # Test
    result = await detect_vip_sender(
        email_anon="[EMAIL_DOYEN_123]",
        email_hash="a" * 64,
        db_pool=mock_pool,
    )

    # Assertions
    assert result.confidence == 1.0
    assert "VIP detecte" in result.output_summary
    assert result.payload["is_vip"] is True
    assert result.payload["vip"]["label"] == "Doyen Faculté Médecine"
    assert "manual" in result.reasoning


@pytest.mark.asyncio
async def test_detect_vip_sender_not_found():
    """Test expéditeur non VIP (pas dans la base)."""
    # Mock db_pool avec aucun VIP trouvé
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = None

    # Test
    result = await detect_vip_sender(
        email_anon="[EMAIL_INCONNU_456]",
        email_hash="b" * 64,
        db_pool=mock_pool,
    )

    # Assertions
    assert result.confidence == 1.0
    assert "Non VIP" in result.output_summary
    assert result.payload["is_vip"] is False
    assert result.payload["vip"] is None
    assert "pas dans table VIP" in result.reasoning


@pytest.mark.asyncio
async def test_detect_vip_sender_inactive_vip():
    """Test que VIP inactif (active=FALSE) n'est PAS détecté."""
    # Mock db_pool : requête filtre active=TRUE donc retourne None
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = None

    # Test
    result = await detect_vip_sender(
        email_anon="[EMAIL_INACTIVE_789]",
        email_hash="c" * 64,
        db_pool=mock_pool,
    )

    # Assertions
    assert result.payload["is_vip"] is False
    assert result.payload["vip"] is None


@pytest.mark.asyncio
async def test_detect_vip_sender_database_error():
    """Test gestion erreur base de données."""
    # Mock db_pool avec erreur
    mock_pool = AsyncMock()
    mock_pool.fetchrow.side_effect = Exception("Database connection error")

    # Test - doit raise VIPDetectorError
    with pytest.raises(VIPDetectorError) as exc_info:
        await detect_vip_sender(
            email_anon="[EMAIL_TEST]",
            email_hash="d" * 64,
            db_pool=mock_pool,
        )

    assert "Unexpected error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_detect_vip_sender_vip_without_label():
    """Test VIP sans label (label=NULL)."""
    # Mock db_pool avec VIP sans label
    mock_pool = AsyncMock()
    vip_id = "234e5678-e89b-12d3-a456-426614174111"
    mock_pool.fetchrow.return_value = {
        "id": UUID(vip_id),
        "email_anon": "[EMAIL_NOLABEL_111]",
        "email_hash": "e" * 64,
        "label": None,
        "priority_override": None,
        "designation_source": "manual",
        "added_by": None,
        "emails_received_count": 5,
        "active": True,
    }

    # Test
    result = await detect_vip_sender(
        email_anon="[EMAIL_NOLABEL_111]",
        email_hash="e" * 64,
        db_pool=mock_pool,
    )

    # Assertions
    assert result.payload["is_vip"] is True
    assert result.payload["vip"]["label"] is None
    # Devrait utiliser email_anon si pas de label
    assert "[EMAIL_NOLABEL_111]" in result.output_summary


# ==========================================
# Tests update_vip_email_stats (helper)
# ==========================================


@pytest.mark.asyncio
async def test_update_vip_email_stats_success():
    """Test mise à jour stats VIP réussie."""
    # Mock db_pool
    mock_pool = AsyncMock()
    mock_pool.execute.return_value = None

    vip_id = "123e4567-e89b-12d3-a456-426614174000"

    # Test - ne doit pas raise
    await update_vip_email_stats(
        vip_id=vip_id,
        db_pool=mock_pool,
    )

    # Vérifier que UPDATE a été appelé
    mock_pool.execute.assert_called_once()
    call_args = mock_pool.execute.call_args[0]
    assert "UPDATE core.vip_senders" in call_args[0]
    assert "emails_received_count" in call_args[0]


@pytest.mark.asyncio
async def test_update_vip_email_stats_db_error():
    """Test que erreur DB ne fait PAS crash (stats non critiques)."""
    # Mock db_pool avec erreur
    mock_pool = AsyncMock()
    mock_pool.execute.side_effect = Exception("Database error")

    vip_id = "123e4567-e89b-12d3-a456-426614174000"

    # Test - ne doit PAS raise (erreur loggée mais non critique)
    await update_vip_email_stats(
        vip_id=vip_id,
        db_pool=mock_pool,
    )

    # Vérifier que la fonction a bien retourné sans crash
    # (pas d'assertion, juste vérifier qu'elle ne raise pas)
