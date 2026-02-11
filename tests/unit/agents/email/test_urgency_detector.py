"""
Tests unitaires pour agents/email/urgency_detector.py

Tests de detection urgence multi-facteurs.
Story 2.3 - Detection VIP & Urgence
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from agents.src.agents.email.urgency_detector import (
    check_urgency_keywords,
    detect_urgency,
    extract_deadline_patterns,
)


# ==========================================
# Mock Helper Classes
# ==========================================


class MockAsyncPoolKeywords:
    """Mock pool pour tests keywords (retourne fetch results)."""

    def __init__(self, keywords_rows):
        self.keywords_rows = keywords_rows
        self.mock_conn = AsyncMock()
        self.mock_conn.fetch.return_value = keywords_rows

    @asynccontextmanager
    async def acquire(self):
        yield self.mock_conn


# ==========================================
# Tests extract_deadline_patterns (helper)
# ==========================================


def test_extract_deadline_patterns_avant_demain():
    """Test detection pattern 'avant demain'."""
    text = "Merci de repondre avant demain matin."
    result = extract_deadline_patterns(text)
    assert result is not None
    assert "avant demain" in result


def test_extract_deadline_patterns_deadline_date():
    """Test detection pattern 'deadline 15'."""
    text = "La deadline 15 est critique pour le projet."
    result = extract_deadline_patterns(text)
    assert result is not None
    assert "deadline 15" in result


def test_extract_deadline_patterns_pour_demain():
    """Test detection pattern 'pour demain'."""
    text = "J'ai besoin de cette info pour demain."
    result = extract_deadline_patterns(text)
    assert result is not None
    assert "pour demain" in result


def test_extract_deadline_patterns_dici():
    """Test detection pattern 'd'ici'."""
    text = "Merci de valider d'ici 2 jours."
    result = extract_deadline_patterns(text)
    assert result is not None
    assert "d'ici 2 jours" in result


def test_extract_deadline_patterns_urgent_demain():
    """Test detection pattern 'urgent' + 'demain'."""
    text = "C'est urgent, je dois savoir demain au plus tard."
    result = extract_deadline_patterns(text)
    assert result is not None
    assert "urgent" in result or "demain" in result


def test_extract_deadline_patterns_case_insensitive():
    """Test que la detection est case-insensitive."""
    text1 = "Avant DEMAIN"
    text2 = "AVANT demain"
    result1 = extract_deadline_patterns(text1)
    result2 = extract_deadline_patterns(text2)
    assert result1 is not None
    assert result2 is not None


def test_extract_deadline_patterns_no_match():
    """Test texte sans deadline."""
    text = "Bonjour, j'espere que vous allez bien."
    result = extract_deadline_patterns(text)
    assert result is None


# ==========================================
# Tests check_urgency_keywords (helper)
# ==========================================


@pytest.mark.asyncio
async def test_check_urgency_keywords_match():
    """Test detection keywords urgence."""
    # Mock db_pool avec keywords actifs
    mock_pool = MockAsyncPoolKeywords([
        {"keyword": "URGENT", "weight": 0.5},
        {"keyword": "deadline", "weight": 0.3},
    ])

    text = "URGENT: Cette demande a une deadline serree."
    result = await check_urgency_keywords(text, mock_pool)

    assert len(result) == 2
    assert "URGENT" in result
    assert "deadline" in result


@pytest.mark.asyncio
async def test_check_urgency_keywords_case_insensitive():
    """Test que la recherche est case-insensitive."""
    # Mock db_pool
    mock_pool = MockAsyncPoolKeywords([
        {"keyword": "URGENT", "weight": 0.5},
    ])

    # Texte avec keyword en minuscules
    text = "Ce message est urgent, merci de repondre vite."
    result = await check_urgency_keywords(text, mock_pool)

    assert len(result) == 1
    assert "URGENT" in result


@pytest.mark.asyncio
async def test_check_urgency_keywords_no_match():
    """Test texte sans keywords urgence."""
    # Mock db_pool
    mock_pool = MockAsyncPoolKeywords([
        {"keyword": "URGENT", "weight": 0.5},
        {"keyword": "deadline", "weight": 0.3},
    ])

    text = "Bonjour, j'aimerais avoir des nouvelles du projet."
    result = await check_urgency_keywords(text, mock_pool)

    assert len(result) == 0


@pytest.mark.asyncio
async def test_check_urgency_keywords_empty_db():
    """Test avec aucun keyword en DB."""
    # Mock db_pool avec liste vide
    mock_pool = MockAsyncPoolKeywords([])

    text = "URGENT: deadline demain"
    result = await check_urgency_keywords(text, mock_pool)

    assert len(result) == 0


@pytest.mark.asyncio
async def test_check_urgency_keywords_db_error():
    """Test gestion erreur DB (mode degrade)."""
    # Mock db_pool avec erreur qui raise lors de l'acquire
    class MockPoolError:
        @asynccontextmanager
        async def acquire(self):
            raise Exception("Database error")
            yield  # Jamais atteint mais necessaire pour syntaxe

    mock_pool = MockPoolError()

    text = "URGENT: deadline"
    # Ne doit PAS raise - mode degrade
    result = await check_urgency_keywords(text, mock_pool)

    # Mode degrade : retourne liste vide
    assert len(result) == 0


# ==========================================
# Tests detect_urgency (fonction principale)
# ==========================================


@pytest.mark.asyncio
async def test_detect_urgency_vip_only():
    """Test urgence VIP seul (score=0.5, seuil=0.6 -> non urgent)."""
    # Mock db_pool (pas de keywords)
    mock_pool = MockAsyncPoolKeywords([])

    text = "Bonjour, j'ai une question."
    result = await detect_urgency(
        email_text=text,
        vip_status=True,
        db_pool=mock_pool,
    )

    # VIP=0.5 < seuil 0.6 -> non urgent
    assert result.confidence == 0.5
    assert result.payload["is_urgent"] is False
    assert "VIP" in result.reasoning


@pytest.mark.asyncio
async def test_detect_urgency_vip_plus_keyword():
    """Test urgence VIP + keyword (score=0.5+0.3=0.8 -> urgent)."""
    # Mock db_pool avec keyword
    mock_pool = MockAsyncPoolKeywords([
        {"keyword": "URGENT", "weight": 0.5},
    ])

    text = "URGENT: j'ai besoin de cette info."
    result = await detect_urgency(
        email_text=text,
        vip_status=True,
        db_pool=mock_pool,
    )

    # VIP=0.5 + keywords=0.3 = 0.8 >= 0.6 -> urgent
    assert result.confidence == 0.8
    assert result.payload["is_urgent"] is True
    assert "VIP" in result.reasoning
    assert "keywords" in result.reasoning


@pytest.mark.asyncio
async def test_detect_urgency_keyword_plus_deadline():
    """Test urgence keyword + deadline (score=0.3+0.2=0.5 -> non urgent)."""
    # Mock db_pool avec keyword
    mock_pool = MockAsyncPoolKeywords([
        {"keyword": "URGENT", "weight": 0.5},
    ])

    text = "URGENT: merci de repondre avant demain."
    result = await detect_urgency(
        email_text=text,
        vip_status=False,
        db_pool=mock_pool,
    )

    # keywords=0.3 + deadline=0.2 = 0.5 < 0.6 -> non urgent
    assert result.confidence == 0.5
    assert result.payload["is_urgent"] is False


@pytest.mark.asyncio
async def test_detect_urgency_all_factors():
    """Test urgence tous facteurs (VIP + keyword + deadline = 1.0 -> urgent)."""
    # Mock db_pool avec keyword
    mock_pool = MockAsyncPoolKeywords([
        {"keyword": "URGENT", "weight": 0.5},
    ])

    text = "URGENT: Doyen demande reponse avant demain."
    result = await detect_urgency(
        email_text=text,
        vip_status=True,
        db_pool=mock_pool,
    )

    # VIP=0.5 + keywords=0.3 + deadline=0.2 = 1.0 -> urgent
    assert result.confidence == 1.0
    assert result.payload["is_urgent"] is True
    assert "VIP" in result.reasoning
    assert "keywords" in result.reasoning
    assert "deadline" in result.reasoning


@pytest.mark.asyncio
async def test_detect_urgency_no_factors():
    """Test email normal (aucun facteur -> score=0.0)."""
    # Mock db_pool vide
    mock_pool = MockAsyncPoolKeywords([])

    text = "Bonjour, comment allez-vous ?"
    result = await detect_urgency(
        email_text=text,
        vip_status=False,
        db_pool=mock_pool,
    )

    # Aucun facteur = 0.0 < 0.6 -> non urgent
    assert result.confidence == 0.0
    assert result.payload["is_urgent"] is False
    assert "aucun" in result.reasoning


@pytest.mark.asyncio
async def test_detect_urgency_payload_structure():
    """Test structure payload UrgencyResult."""
    # Mock db_pool avec keyword
    mock_pool = MockAsyncPoolKeywords([
        {"keyword": "deadline", "weight": 0.3},
    ])

    text = "La deadline approche vite."
    result = await detect_urgency(
        email_text=text,
        vip_status=False,
        db_pool=mock_pool,
    )

    # Verifier structure payload
    assert "urgency" in result.payload
    urgency = result.payload["urgency"]
    assert "is_urgent" in urgency
    assert "confidence" in urgency
    assert "reasoning" in urgency
    assert "factors" in urgency

    # Verifier factors details
    factors = urgency["factors"]
    assert "vip" in factors
    assert "keywords" in factors
    assert "deadline" in factors
    assert "keywords_matched" in factors
