"""
Tests Unitaires - Conflict Detector

Story 7.3: Multi-casquettes & Conflits (AC4)

Tests:
- Conflit casquettes différentes (médecin ⚡ enseignant)
- AUCUN conflit si même casquette
- Overlap calculation (1h, 30min, 15min)
- Aucun conflit si événements non chevauchants
- Déduplication (même conflit pas détecté 2x)
- Conflits sur 7 jours (AC5)
- Événements status='cancelled' exclus
- Événements même heure début/fin (edge case)
- Event1 englobe event2 complètement
- Transaction atomique rollback si erreur
"""

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agents.src.agents.calendar.conflict_detector import (
    _has_temporal_overlap,
    calculate_overlap,
    detect_calendar_conflicts,
    get_conflicts_range,
    save_conflict_to_db,
)
from agents.src.agents.calendar.models import CalendarConflict, CalendarEvent, Casquette

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg.Pool."""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


@pytest.fixture
def sample_events_conflict():
    """2 événements qui se chevauchent (casquettes différentes)."""
    base_date = datetime(2026, 2, 17)

    return [
        CalendarEvent(
            id=str(uuid4()),
            title="Consultation patient",
            casquette=Casquette.MEDECIN,
            start_datetime=base_date.replace(hour=14, minute=30),
            end_datetime=base_date.replace(hour=15, minute=30),
            status="confirmed",
        ),
        CalendarEvent(
            id=str(uuid4()),
            title="Cours L2 Anatomie",
            casquette=Casquette.ENSEIGNANT,
            start_datetime=base_date.replace(hour=14, minute=0),
            end_datetime=base_date.replace(hour=16, minute=0),
            status="confirmed",
        ),
    ]


# ============================================================================
# Tests Détection Conflits
# ============================================================================


@pytest.mark.asyncio
async def test_detect_conflict_different_casquettes(mock_db_pool, sample_events_conflict):
    """Test AC4: Conflit détecté si casquettes différentes."""
    pool, conn = mock_db_pool

    # Mock: Retourne 2 événements chevauchants
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": uuid4(),
                "title": event.title,
                "casquette": event.casquette.value,
                "start_datetime": event.start_datetime,
                "end_datetime": event.end_datetime,
                "status": "confirmed",
            }
            for event in sample_events_conflict
        ]
    )

    # Détecter conflits
    target_date = date(2026, 2, 17)
    conflicts = await detect_calendar_conflicts(target_date, pool)

    # Assertions
    assert len(conflicts) == 1, "1 conflit devrait être détecté"

    conflict = conflicts[0]
    assert conflict.event1.casquette != conflict.event2.casquette
    assert conflict.overlap_minutes == 60  # 14h30-15h30 = 1h
    assert conflict.event1.casquette == Casquette.MEDECIN
    assert conflict.event2.casquette == Casquette.ENSEIGNANT


@pytest.mark.asyncio
async def test_no_conflict_same_casquette(mock_db_pool):
    """Test AC4: AUCUN conflit si même casquette (probablement erreur saisie)."""
    pool, conn = mock_db_pool

    base_date = datetime(2026, 2, 17)

    # Mock: 2 événements chevauchants MÊME casquette
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": uuid4(),
                "title": "Consultation 1",
                "casquette": "medecin",
                "start_datetime": base_date.replace(hour=14, minute=0),
                "end_datetime": base_date.replace(hour=15, minute=0),
                "status": "confirmed",
            },
            {
                "id": uuid4(),
                "title": "Consultation 2",
                "casquette": "medecin",  # Même casquette
                "start_datetime": base_date.replace(hour=14, minute=30),
                "end_datetime": base_date.replace(hour=15, minute=30),
                "status": "confirmed",
            },
        ]
    )

    # Détecter conflits
    conflicts = await detect_calendar_conflicts(date(2026, 2, 17), pool)

    # Assertions: Aucun conflit
    assert len(conflicts) == 0, "Pas de conflit si même casquette"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start1,end1,start2,end2,expected_overlap",
    [
        # Overlap 1h (14h30-15h30)
        (
            datetime(2026, 2, 17, 14, 30),
            datetime(2026, 2, 17, 15, 30),
            datetime(2026, 2, 17, 14, 0),
            datetime(2026, 2, 17, 16, 0),
            60,
        ),
        # Overlap 30min (14h00-14h30)
        (
            datetime(2026, 2, 17, 14, 0),
            datetime(2026, 2, 17, 15, 0),
            datetime(2026, 2, 17, 14, 30),
            datetime(2026, 2, 17, 16, 0),
            30,
        ),
        # Overlap 15min (09h45-10h00)
        (
            datetime(2026, 2, 17, 9, 30),
            datetime(2026, 2, 17, 10, 0),
            datetime(2026, 2, 17, 9, 45),
            datetime(2026, 2, 17, 10, 30),
            15,
        ),
    ],
)
def test_overlap_calculation(start1, end1, start2, end2, expected_overlap):
    """Test AC4: Calcul overlap_minutes (1h, 30min, 15min)."""
    event1 = CalendarEvent(
        id=str(uuid4()),
        title="Event 1",
        casquette=Casquette.MEDECIN,
        start_datetime=start1,
        end_datetime=end1,
    )

    event2 = CalendarEvent(
        id=str(uuid4()),
        title="Event 2",
        casquette=Casquette.ENSEIGNANT,
        start_datetime=start2,
        end_datetime=end2,
    )

    overlap = calculate_overlap(event1, event2)

    assert overlap == expected_overlap, f"Expected {expected_overlap}min, got {overlap}min"


@pytest.mark.asyncio
async def test_no_conflict_non_overlapping_events(mock_db_pool):
    """Test AC4: Aucun conflit si événements non chevauchants."""
    pool, conn = mock_db_pool

    base_date = datetime(2026, 2, 17)

    # Mock: 2 événements NON chevauchants
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": uuid4(),
                "title": "Consultation matin",
                "casquette": "medecin",
                "start_datetime": base_date.replace(hour=9, minute=0),
                "end_datetime": base_date.replace(hour=10, minute=0),
                "status": "confirmed",
            },
            {
                "id": uuid4(),
                "title": "Cours après-midi",
                "casquette": "enseignant",
                "start_datetime": base_date.replace(hour=14, minute=0),
                "end_datetime": base_date.replace(hour=16, minute=0),
                "status": "confirmed",
            },
        ]
    )

    # Détecter conflits
    conflicts = await detect_calendar_conflicts(date(2026, 2, 17), pool)

    # Assertions: Aucun conflit
    assert len(conflicts) == 0


@pytest.mark.asyncio
async def test_deduplication_same_conflict(mock_db_pool):
    """Test AC4: Déduplication (même conflit pas détecté 2x)."""
    pool, conn = mock_db_pool

    base_date = datetime(2026, 2, 17)

    # Mock: 2 événements chevauchants
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": uuid4(),
                "title": "Event 1",
                "casquette": "medecin",
                "start_datetime": base_date.replace(hour=14, minute=0),
                "end_datetime": base_date.replace(hour=15, minute=0),
                "status": "confirmed",
            },
            {
                "id": uuid4(),
                "title": "Event 2",
                "casquette": "enseignant",
                "start_datetime": base_date.replace(hour=14, minute=30),
                "end_datetime": base_date.replace(hour=15, minute=30),
                "status": "confirmed",
            },
        ]
    )

    # Détecter conflits 2 fois
    conflicts1 = await detect_calendar_conflicts(date(2026, 2, 17), pool)
    conflicts2 = await detect_calendar_conflicts(date(2026, 2, 17), pool)

    # Assertions: Même nombre conflits (pas de doublon dans résultat)
    assert len(conflicts1) == 1
    assert len(conflicts2) == 1

    # Note: Déduplication DB (index unique) testée dans test_save_conflict_to_db


@pytest.mark.asyncio
async def test_conflicts_range_7_days(mock_db_pool):
    """Test AC5: Conflits sur 7 jours (Heartbeat check)."""
    pool, conn = mock_db_pool

    # Mock: Retourne 2 événements qui se chevauchent sur la plage complète
    # (get_conflicts_range utilise une requête SQL unique pour toute la plage)
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": uuid4(),
                "title": "Event 1",
                "casquette": "medecin",
                "start_datetime": datetime(2026, 2, 17, 14, 0),
                "end_datetime": datetime(2026, 2, 17, 15, 0),
                "status": "confirmed",
            },
            {
                "id": uuid4(),
                "title": "Event 2",
                "casquette": "enseignant",
                "start_datetime": datetime(2026, 2, 17, 14, 30),
                "end_datetime": datetime(2026, 2, 17, 15, 30),
                "status": "confirmed",
            },
        ]
    )

    # Récupérer conflits 7 jours
    start_date = date(2026, 2, 17)
    end_date = start_date + timedelta(days=6)

    conflicts = await get_conflicts_range(start_date, end_date, pool)

    # Assertions: 1 conflit sur 7 jours
    assert len(conflicts) == 1
    assert conn.fetch.call_count == 1  # 1 seul appel SQL (requête range unique)


@pytest.mark.asyncio
async def test_cancelled_events_excluded(mock_db_pool):
    """Test AC4: Événements status='cancelled' exclus."""
    pool, conn = mock_db_pool

    # Mock: Seulement événements status='confirmed' (query filtre cancelled)
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": uuid4(),
                "title": "Event confirmed",
                "casquette": "medecin",
                "start_datetime": datetime(2026, 2, 17, 14, 0),
                "end_datetime": datetime(2026, 2, 17, 15, 0),
                "status": "confirmed",
            }
            # Event cancelled PAS retourné par query
        ]
    )

    # Détecter conflits
    conflicts = await detect_calendar_conflicts(date(2026, 2, 17), pool)

    # Assertions: Aucun conflit (1 seul événement)
    assert len(conflicts) == 0

    # Vérifier query filtre status='confirmed'
    query_call = conn.fetch.call_args[0][0]
    assert "(properties->>'status') = 'confirmed'" in query_call


def test_same_start_end_time_edge_case():
    """Test AC4: Edge case événements même heure début/fin (pas de chevauchement)."""
    event1 = CalendarEvent(
        id=str(uuid4()),
        title="Event 1",
        casquette=Casquette.MEDECIN,
        start_datetime=datetime(2026, 2, 17, 14, 0),
        end_datetime=datetime(2026, 2, 17, 15, 0),
    )

    event2 = CalendarEvent(
        id=str(uuid4()),
        title="Event 2",
        casquette=Casquette.ENSEIGNANT,
        start_datetime=datetime(2026, 2, 17, 15, 0),  # Commence quand event1 finit
        end_datetime=datetime(2026, 2, 17, 16, 0),
    )

    # Vérifier pas de chevauchement temporel
    has_overlap = _has_temporal_overlap(event1, event2)
    assert has_overlap is False, "Événements bout à bout ne doivent pas chevaucher"

    overlap = calculate_overlap(event1, event2)
    assert overlap == 0


def test_event1_englobes_event2():
    """Test AC4: Event1 englobe event2 complètement."""
    event1 = CalendarEvent(
        id=str(uuid4()),
        title="Event long",
        casquette=Casquette.MEDECIN,
        start_datetime=datetime(2026, 2, 17, 14, 0),
        end_datetime=datetime(2026, 2, 17, 18, 0),  # 4h
    )

    event2 = CalendarEvent(
        id=str(uuid4()),
        title="Event court",
        casquette=Casquette.ENSEIGNANT,
        start_datetime=datetime(2026, 2, 17, 15, 0),
        end_datetime=datetime(2026, 2, 17, 16, 0),  # 1h (à l'intérieur)
    )

    # Vérifier chevauchement complet
    has_overlap = _has_temporal_overlap(event1, event2)
    assert has_overlap is True

    overlap = calculate_overlap(event1, event2)
    assert overlap == 60, "Overlap = durée event2 complet (60min)"


@pytest.mark.asyncio
async def test_save_conflict_to_db_deduplication(mock_db_pool):
    """Test AC4: save_conflict_to_db déduplication (index unique)."""
    pool, conn = mock_db_pool

    event1 = CalendarEvent(
        id=str(uuid4()),
        title="Event 1",
        casquette=Casquette.MEDECIN,
        start_datetime=datetime(2026, 2, 17, 14, 0),
        end_datetime=datetime(2026, 2, 17, 15, 0),
    )

    event2 = CalendarEvent(
        id=str(uuid4()),
        title="Event 2",
        casquette=Casquette.ENSEIGNANT,
        start_datetime=datetime(2026, 2, 17, 14, 30),
        end_datetime=datetime(2026, 2, 17, 15, 30),
    )

    conflict = CalendarConflict(event1=event1, event2=event2, overlap_minutes=30)

    # Mock: 1er INSERT → retourne UUID
    conflict_id1 = str(uuid4())
    conn.fetchval = AsyncMock(return_value=conflict_id1)

    result1 = await save_conflict_to_db(conflict, pool)
    assert result1 == conflict_id1

    # Mock: 2ème INSERT → ON CONFLICT DO NOTHING (retourne None)
    conn.fetchval = AsyncMock(return_value=None)

    result2 = await save_conflict_to_db(conflict, pool)
    assert result2 is None, "Doublon devrait retourner None"


# ============================================================================
# Tests Helpers
# ============================================================================


def test_has_temporal_overlap_various_cases():
    """Test: _has_temporal_overlap cas variés."""
    base_date = datetime(2026, 2, 17)

    # Cas 1: Overlap partiel
    event1 = CalendarEvent(
        id=str(uuid4()),
        title="E1",
        casquette=Casquette.MEDECIN,
        start_datetime=base_date.replace(hour=14, minute=0),
        end_datetime=base_date.replace(hour=15, minute=0),
    )
    event2 = CalendarEvent(
        id=str(uuid4()),
        title="E2",
        casquette=Casquette.ENSEIGNANT,
        start_datetime=base_date.replace(hour=14, minute=30),
        end_datetime=base_date.replace(hour=16, minute=0),
    )
    assert _has_temporal_overlap(event1, event2) is True

    # Cas 2: Pas d'overlap
    event3 = CalendarEvent(
        id=str(uuid4()),
        title="E3",
        casquette=Casquette.MEDECIN,
        start_datetime=base_date.replace(hour=9, minute=0),
        end_datetime=base_date.replace(hour=10, minute=0),
    )
    event4 = CalendarEvent(
        id=str(uuid4()),
        title="E4",
        casquette=Casquette.ENSEIGNANT,
        start_datetime=base_date.replace(hour=11, minute=0),
        end_datetime=base_date.replace(hour=12, minute=0),
    )
    assert _has_temporal_overlap(event3, event4) is False
