"""
Tests Unitaires - Briefing Generator

Story 7.3: Multi-casquettes & Conflits (AC3)

Tests:
- Groupement 3 casquettes
- Tri chronologique dans section
- Filtrage /briefing medecin
- Émojis corrects par casquette
- Section conflits en haut (mock conflits)
"""

import pytest
from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from agents.src.agents.briefing.generator import BriefingGenerator
from agents.src.agents.briefing.templates import (
    format_briefing_message,
    _format_casquette_section,
    _format_event_line,
    _format_conflict_line
)
from agents.src.core.models import Casquette


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_db_pool():
    """Mock asyncpg.Pool."""
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool, conn


@pytest.fixture
def briefing_generator(mock_db_pool):
    """Instance BriefingGenerator avec mock."""
    pool, _ = mock_db_pool
    return BriefingGenerator(db_pool=pool)


@pytest.fixture
def sample_events():
    """Événements test pour 3 casquettes."""
    base_date = datetime(2026, 2, 17)

    return [
        {
            "id": str(uuid4()),
            "title": "3 consultations cardiologie",
            "casquette": Casquette.MEDECIN,
            "start_datetime": base_date.replace(hour=9, minute=0),
            "end_datetime": base_date.replace(hour=12, minute=0)
        },
        {
            "id": str(uuid4()),
            "title": "Cours L2 Anatomie",
            "casquette": Casquette.ENSEIGNANT,
            "start_datetime": base_date.replace(hour=14, minute=0),
            "end_datetime": base_date.replace(hour=16, minute=0)
        },
        {
            "id": str(uuid4()),
            "title": "Réunion labo (Teams)",
            "casquette": Casquette.CHERCHEUR,
            "start_datetime": base_date.replace(hour=18, minute=0),
            "end_datetime": base_date.replace(hour=19, minute=0)
        }
    ]


# ============================================================================
# Tests Briefing Generator
# ============================================================================

@pytest.mark.asyncio
async def test_briefing_grouped_by_casquette(briefing_generator, mock_db_pool, sample_events):
    """Test AC3: Briefing organisé par casquette (médecin/enseignant/chercheur)."""
    _, conn = mock_db_pool

    # Mock fetch events
    conn.fetch = AsyncMock(return_value=[
        {
            "id": uuid4(),
            "title": event["title"],
            "casquette": event["casquette"].value,
            "start_datetime": event["start_datetime"],
            "end_datetime": event["end_datetime"]
        }
        for event in sample_events
    ])

    # Générer briefing
    target_date = date(2026, 2, 17)
    briefing = await briefing_generator.generate_morning_briefing(target_date=target_date)

    # Assertions: Vérifier sections casquettes présentes
    assert "🩺 **MÉDECIN**" in briefing
    assert "🎓 **ENSEIGNANT**" in briefing
    assert "🔬 **CHERCHEUR**" in briefing

    # Vérifier ordre sections (médecin → enseignant → chercheur)
    medecin_pos = briefing.index("🩺 **MÉDECIN**")
    enseignant_pos = briefing.index("🎓 **ENSEIGNANT**")
    chercheur_pos = briefing.index("🔬 **CHERCHEUR**")

    assert medecin_pos < enseignant_pos < chercheur_pos

    # Vérifier événements présents
    assert "3 consultations cardiologie" in briefing
    assert "Cours L2 Anatomie" in briefing
    assert "Réunion labo (Teams)" in briefing


@pytest.mark.asyncio
async def test_briefing_chronological_order_within_section(briefing_generator, mock_db_pool):
    """Test AC3: Tri chronologique événements dans chaque section."""
    _, conn = mock_db_pool

    base_date = datetime(2026, 2, 17)

    # Mock: 2 événements médecin (ordre inversé dans DB)
    conn.fetch = AsyncMock(return_value=[
        {
            "id": uuid4(),
            "title": "Événement 2 (après-midi)",
            "casquette": "medecin",
            "start_datetime": base_date.replace(hour=14, minute=30),
            "end_datetime": base_date.replace(hour=15, minute=30)
        },
        {
            "id": uuid4(),
            "title": "Événement 1 (matin)",
            "casquette": "medecin",
            "start_datetime": base_date.replace(hour=9, minute=0),
            "end_datetime": base_date.replace(hour=10, minute=0)
        }
    ])

    # Générer briefing
    briefing = await briefing_generator.generate_morning_briefing(target_date=base_date.date())

    # Assertions: Ordre chronologique dans section médecin
    event1_pos = briefing.index("Événement 1 (matin)")
    event2_pos = briefing.index("Événement 2 (après-midi)")

    assert event1_pos < event2_pos, "Événements pas triés chronologiquement"


@pytest.mark.asyncio
async def test_briefing_filter_by_casquette(briefing_generator, mock_db_pool, sample_events):
    """Test AC3: Filtrage /briefing medecin → seulement événements médecin."""
    _, conn = mock_db_pool

    # Mock: Seulement événements médecin (filtre appliqué dans query)
    medecin_events = [e for e in sample_events if e["casquette"] == Casquette.MEDECIN]

    conn.fetch = AsyncMock(return_value=[
        {
            "id": uuid4(),
            "title": event["title"],
            "casquette": event["casquette"].value,
            "start_datetime": event["start_datetime"],
            "end_datetime": event["end_datetime"]
        }
        for event in medecin_events
    ])

    # Générer briefing avec filtre
    target_date = date(2026, 2, 17)
    briefing = await briefing_generator.generate_morning_briefing(
        target_date=target_date,
        filter_casquette=Casquette.MEDECIN
    )

    # Assertions: Seulement section médecin
    assert "🩺 **MÉDECIN**" in briefing
    assert "3 consultations cardiologie" in briefing

    # Pas d'autres casquettes
    assert "🎓 **ENSEIGNANT**" not in briefing
    assert "🔬 **CHERCHEUR**" not in briefing


@pytest.mark.asyncio
async def test_briefing_emojis_correct_by_casquette(briefing_generator, mock_db_pool, sample_events):
    """Test AC3: Émojis corrects par casquette (🩺🎓🔬)."""
    _, conn = mock_db_pool

    # Mock events
    conn.fetch = AsyncMock(return_value=[
        {
            "id": uuid4(),
            "title": event["title"],
            "casquette": event["casquette"].value,
            "start_datetime": event["start_datetime"],
            "end_datetime": event["end_datetime"]
        }
        for event in sample_events
    ])

    # Générer briefing
    briefing = await briefing_generator.generate_morning_briefing(target_date=date(2026, 2, 17))

    # Assertions: Émojis présents
    assert "🩺" in briefing  # Médecin
    assert "🎓" in briefing  # Enseignant
    assert "🔬" in briefing  # Chercheur

    # Vérifier mapping correct
    assert briefing.count("🩺") == 1  # 1 section médecin
    assert briefing.count("🎓") == 1  # 1 section enseignant
    assert briefing.count("🔬") == 1  # 1 section chercheur


@pytest.mark.asyncio
async def test_briefing_conflicts_section_on_top(briefing_generator, mock_db_pool):
    """Test AC3: Section conflits en haut du briefing (mock conflits)."""
    _, conn = mock_db_pool

    base_date = datetime(2026, 2, 17)

    # Mock: 2 événements qui se chevauchent
    conn.fetch = AsyncMock(return_value=[
        {
            "id": uuid4(),
            "title": "Consultation patient",
            "casquette": "medecin",
            "start_datetime": base_date.replace(hour=14, minute=30),
            "end_datetime": base_date.replace(hour=15, minute=30)
        },
        {
            "id": uuid4(),
            "title": "Cours L2",
            "casquette": "enseignant",
            "start_datetime": base_date.replace(hour=14, minute=0),
            "end_datetime": base_date.replace(hour=16, minute=0)
        }
    ])

    # Mock conflits
    mock_conflicts = [
        {
            "event1": {
                "title": "Consultation patient",
                "casquette": Casquette.MEDECIN,
                "start_datetime": base_date.replace(hour=14, minute=30)
            },
            "event2": {
                "title": "Cours L2",
                "casquette": Casquette.ENSEIGNANT,
                "start_datetime": base_date.replace(hour=14, minute=0)
            },
            "overlap_minutes": 60
        }
    ]

    # Mock _get_conflicts_for_day
    with patch.object(briefing_generator, "_get_conflicts_for_day", return_value=mock_conflicts):
        # Générer briefing
        briefing = await briefing_generator.generate_morning_briefing(target_date=base_date.date())

    # Assertions: Section conflits présente et en haut
    assert "⚠️ **CONFLITS DÉTECTÉS**" in briefing

    # Position section conflits avant sections casquettes
    conflict_pos = briefing.index("⚠️ **CONFLITS DÉTECTÉS**")
    medecin_pos = briefing.index("🩺 **MÉDECIN**")

    assert conflict_pos < medecin_pos, "Section conflits pas en haut du briefing"

    # Vérifier ligne conflit
    assert "médecin ⚡ enseignant" in briefing


# ============================================================================
# Tests Templates
# ============================================================================

def test_format_event_line():
    """Test: Formatage ligne événement (09h00-12h00 : Consultation)."""
    event = {
        "title": "3 consultations cardiologie",
        "start_datetime": datetime(2026, 2, 17, 9, 0),
        "end_datetime": datetime(2026, 2, 17, 12, 0)
    }

    line = _format_event_line(event)

    assert line == "09h00-12h00 : 3 consultations cardiologie"


def test_format_casquette_section():
    """Test: Formatage section casquette avec émojis."""
    events = [
        {
            "title": "Consultation 1",
            "start_datetime": datetime(2026, 2, 17, 9, 0),
            "end_datetime": datetime(2026, 2, 17, 10, 0)
        },
        {
            "title": "Consultation 2",
            "start_datetime": datetime(2026, 2, 17, 10, 30),
            "end_datetime": datetime(2026, 2, 17, 11, 30)
        }
    ]

    lines = _format_casquette_section(Casquette.MEDECIN, events)

    # Assertions
    assert "🩺 **MÉDECIN**" in lines[0]
    assert "• 09h00-10h00 : Consultation 1" in lines[1]
    assert "• 10h30-11h30 : Consultation 2" in lines[2]


def test_format_conflict_line():
    """Test: Formatage ligne conflit avec émojis."""
    base_date = datetime(2026, 2, 17)

    conflict = {
        "event1": {
            "title": "Consultation",
            "casquette": Casquette.MEDECIN,
            "start_datetime": base_date.replace(hour=14, minute=30)
        },
        "event2": {
            "title": "Cours",
            "casquette": Casquette.ENSEIGNANT,
            "start_datetime": base_date.replace(hour=14, minute=0)
        },
        "overlap_minutes": 60
    }

    line = _format_conflict_line(conflict)

    assert "14h30 médecin ⚡ 14h00 enseignant" in line
    assert "1h00 chevauchement" in line


def test_format_briefing_message_empty_events():
    """Test: Briefing sans événements → message approprié."""
    target_date = date(2026, 2, 17)
    grouped_events = {}
    conflicts = []

    message = format_briefing_message(target_date, grouped_events, conflicts)

    assert "📋 **Briefing Lundi 17 février 2026**" in message
    assert "_Aucun événement prévu aujourd'hui_" in message
