"""
Tests Unitaires - Heartbeat Check Calendar Conflicts

Story 7.3: Multi-casquettes & Conflits Calendrier (AC5)

Tests :
- Check détecte conflits 7 jours
- Check skip quiet hours (22h-8h)
- Check skip si aucun événement
- CheckResult status='warning' si conflit
- CheckResult status='ok' si aucun conflit
- Formatage message notification
"""

import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from agents.src.core.heartbeat_checks.calendar_conflicts import (
    check_calendar_conflicts,
    _should_skip_quiet_hours,
    _format_conflict_notification,
)
from agents.src.core.heartbeat_models import CheckResult, CheckPriority


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_db_pool():
    """Mock asyncpg.Pool."""
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    pool.close = AsyncMock()
    return pool


@pytest.fixture
def context_daytime():
    """Contexte Heartbeat daytime (14h)."""
    return {
        "time": datetime(2026, 2, 17, 14, 30),
        "hour": 14,
        "is_weekend": False,
        "quiet_hours": False
    }


@pytest.fixture
def context_quiet_hours():
    """Contexte Heartbeat quiet hours (23h)."""
    return {
        "time": datetime(2026, 2, 17, 23, 0),
        "hour": 23,
        "is_weekend": False,
        "quiet_hours": True
    }


@pytest.fixture
def sample_conflicts():
    """Conflits calendrier test (non résolus)."""
    base_date = datetime(2026, 2, 18, 14, 30)  # Demain 14h30

    return [
        {
            "id": str(uuid4()),
            "event1_id": str(uuid4()),
            "event2_id": str(uuid4()),
            "event1_title": "Consultation Dr Dupont",
            "event2_title": "Cours L2 Anatomie",
            "event1_start_datetime": base_date,
            "event2_start_datetime": base_date.replace(hour=14, minute=0),
            "overlap_minutes": 30,
            "resolved": False
        },
        {
            "id": str(uuid4()),
            "event1_id": str(uuid4()),
            "event2_id": str(uuid4()),
            "event1_title": "Réunion labo",
            "event2_title": "Séminaire recherche",
            "event1_start_datetime": base_date.replace(day=19, hour=16, minute=0),
            "event2_start_datetime": base_date.replace(day=19, hour=15, minute=30),
            "overlap_minutes": 30,
            "resolved": False
        }
    ]


# ============================================================================
# Tests Check Conflits 7 Jours (AC5)
# ============================================================================

@pytest.mark.asyncio
async def test_check_detects_conflicts_7_days(mock_db_pool, context_daytime):
    """Test AC5: Check détecte conflits sur 7 jours prochains."""
    # Mock get_conflicts_range
    with patch("agents.src.core.heartbeat_checks.calendar_conflicts.get_conflicts_range") as mock_get:
        mock_get.return_value = [
            {
                "id": str(uuid4()),
                "event1_id": str(uuid4()),
                "event2_id": str(uuid4()),
                "event1_title": "Consultation",
                "event2_title": "Cours",
                "event1_start_datetime": datetime.now() + timedelta(days=2),
                "event2_start_datetime": datetime.now() + timedelta(days=2),
                "overlap_minutes": 60,
                "resolved": False
            }
        ]

        # Call check
        result = await check_calendar_conflicts(context_daytime, db_pool=mock_db_pool)

        # Assertions: Notification envoyée
        assert result.notify is True
        assert "1 conflit calendrier détecté" in result.message
        assert result.action == "view_conflicts"
        assert result.payload["conflict_count"] == 1

        # Assertions: get_conflicts_range appelé avec 7 jours
        mock_get.assert_called_once()
        call_args = mock_get.call_args[1]
        start_date = call_args["start_date"]
        end_date = call_args["end_date"]

        assert (end_date - start_date).days == 7


@pytest.mark.asyncio
async def test_check_status_ok_if_no_conflicts(mock_db_pool, context_daytime):
    """Test AC5: CheckResult notify=False si aucun conflit."""
    # Mock get_conflicts_range (aucun conflit)
    with patch("agents.src.core.heartbeat_checks.calendar_conflicts.get_conflicts_range") as mock_get:
        mock_get.return_value = []

        result = await check_calendar_conflicts(context_daytime, db_pool=mock_db_pool)

        # Assertions: Pas de notification
        assert result.notify is False
        assert result.message == ""


@pytest.mark.asyncio
async def test_check_ignores_resolved_conflicts(mock_db_pool, context_daytime):
    """Test AC5: Check ignore conflits déjà résolus."""
    # Mock get_conflicts_range (1 résolu, 1 non résolu)
    with patch("agents.src.core.heartbeat_checks.calendar_conflicts.get_conflicts_range") as mock_get:
        mock_get.return_value = [
            {
                "id": str(uuid4()),
                "event1_id": str(uuid4()),
                "event2_id": str(uuid4()),
                "event1_title": "Event1",
                "event2_title": "Event2",
                "event1_start_datetime": datetime.now() + timedelta(days=1),
                "event2_start_datetime": datetime.now() + timedelta(days=1),
                "overlap_minutes": 60,
                "resolved": True  # Résolu
            },
            {
                "id": str(uuid4()),
                "event1_id": str(uuid4()),
                "event2_id": str(uuid4()),
                "event1_title": "Event3",
                "event2_title": "Event4",
                "event1_start_datetime": datetime.now() + timedelta(days=2),
                "event2_start_datetime": datetime.now() + timedelta(days=2),
                "overlap_minutes": 30,
                "resolved": False  # Non résolu
            }
        ]

        result = await check_calendar_conflicts(context_daytime, db_pool=mock_db_pool)

        # Assertions: Seulement 1 conflit détecté (non résolu)
        assert result.notify is True
        assert result.payload["conflict_count"] == 1
        assert "1 conflit calendrier détecté" in result.message


# ============================================================================
# Tests Quiet Hours (AC5)
# ============================================================================

@pytest.mark.asyncio
async def test_check_skips_quiet_hours(context_quiet_hours):
    """Test AC5: Check skip quiet hours 22h-8h."""
    result = await check_calendar_conflicts(context_quiet_hours, db_pool=None)

    # Assertions: Skip (pas de notification)
    assert result.notify is False
    assert result.message == ""


def test_should_skip_quiet_hours_23h():
    """Test helper: quiet hours 23h → skip."""
    context = {"hour": 23}
    assert _should_skip_quiet_hours(context) is True


def test_should_skip_quiet_hours_3h():
    """Test helper: quiet hours 03h → skip."""
    context = {"hour": 3}
    assert _should_skip_quiet_hours(context) is True


def test_should_skip_quiet_hours_14h():
    """Test helper: daytime 14h → exécute."""
    context = {"hour": 14}
    assert _should_skip_quiet_hours(context) is False


def test_should_skip_quiet_hours_8h():
    """Test helper: limite quiet hours 08h → exécute."""
    context = {"hour": 8}
    assert _should_skip_quiet_hours(context) is False


def test_should_skip_quiet_hours_22h():
    """Test helper: début quiet hours 22h → skip."""
    context = {"hour": 22}
    assert _should_skip_quiet_hours(context) is True


# ============================================================================
# Tests Formatage Message (AC5)
# ============================================================================

def test_format_conflict_notification_single_conflict(context_daytime):
    """Test AC5: Formatage message 1 conflit."""
    conflicts = [
        {
            "id": str(uuid4()),
            "event1_title": "Consultation Dr Dupont",
            "event2_title": "Cours L2 Anatomie",
            "event1_start_datetime": datetime(2026, 2, 18, 14, 30),  # Demain
            "overlap_minutes": 30
        }
    ]

    message = _format_conflict_notification(conflicts, context_daytime)

    # Assertions: Format message correct
    assert "1 conflit calendrier détecté" in message
    assert "Demain" in message or "📅" in message
    assert "Consultation" in message
    assert "Cours" in message
    assert "/conflits" in message


def test_format_conflict_notification_multiple_conflicts(context_daytime, sample_conflicts):
    """Test AC5: Formatage message 2+ conflits."""
    message = _format_conflict_notification(sample_conflicts, context_daytime)

    # Assertions: Pluriel correct
    assert "2 conflits calendrier détectés" in message

    # Assertions: Affiche 2 dates max
    assert "Demain" in message or "📅" in message
    assert "/conflits" in message


def test_format_conflict_notification_today(context_daytime):
    """Test AC5: Label "Aujourd'hui" si conflit aujourd'hui."""
    conflicts = [
        {
            "id": str(uuid4()),
            "event1_title": "Event1",
            "event2_title": "Event2",
            "event1_start_datetime": datetime.now().replace(hour=16, minute=0),  # Aujourd'hui
            "overlap_minutes": 60
        }
    ]

    message = _format_conflict_notification(conflicts, context_daytime)

    # Assertions: Label "Aujourd'hui"
    assert "Aujourd'hui" in message


# ============================================================================
# Tests Error Handling
# ============================================================================

@pytest.mark.asyncio
async def test_check_handles_db_error(context_daytime):
    """Test AC5: Check handle erreur DB gracefully."""
    # Mock get_conflicts_range qui raise Exception
    with patch("agents.src.core.heartbeat_checks.calendar_conflicts.get_conflicts_range") as mock_get:
        mock_get.side_effect = Exception("DB connection failed")

        result = await check_calendar_conflicts(context_daytime, db_pool=None)

        # Assertions: Erreur catchée, pas de notification
        assert result.notify is False
        assert result.error is not None
        assert "DB connection failed" in result.error


@pytest.mark.asyncio
async def test_check_handles_missing_database_url(context_daytime):
    """Test AC5: Check handle DATABASE_URL manquante."""
    with patch.dict("os.environ", {}, clear=True):
        result = await check_calendar_conflicts(context_daytime, db_pool=None)

        # Assertions: Erreur DATABASE_URL
        assert result.notify is False
        assert result.error is not None
        assert "DATABASE_URL" in result.error
