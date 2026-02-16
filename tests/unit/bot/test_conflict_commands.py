"""
Tests Unitaires - Conflict Commands

Story 7.3: Multi-casquettes & Conflits Calendrier (AC7)

Tests :
- /conflits affichage non résolus
- /conflits stats mois
- /stats section conflits (stub Story 1.11)
- Agrégation casquettes pair (médecin ⚡ enseignant)
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from telegram import Update, Message, User, Chat

from bot.handlers.conflict_commands import (
    handle_conflits_command,
    _get_unresolved_conflicts,
    _get_resolved_week_count,
    _get_month_stats,
    _format_dashboard_message,
    _format_conflict_line,
)


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
def mock_telegram_update():
    """Mock Telegram Update avec Message."""
    update = MagicMock(spec=Update)
    message = MagicMock(spec=Message)
    user = MagicMock(spec=User)
    chat = MagicMock(spec=Chat)

    user.id = 123456789
    user.first_name = "Antonio"

    message.from_user = user
    message.chat = chat
    message.reply_text = AsyncMock()

    update.message = message

    return update


@pytest.fixture
def mock_context(mock_db_pool):
    """Mock ContextTypes.DEFAULT_TYPE."""
    context = MagicMock()
    db_pool, conn = mock_db_pool

    context.bot_data = {
        "db_pool": db_pool
    }

    return context


@pytest.fixture
def sample_unresolved_conflicts():
    """Conflits non résolus test."""
    base_date = datetime(2026, 2, 18, 14, 30)

    return [
        {
            "id": str(uuid4()),
            "event1_id": str(uuid4()),
            "event2_id": str(uuid4()),
            "event1_title": "Consultation Dr Dupont",
            "event2_title": "Cours L2 Anatomie",
            "event1_casquette": "medecin",
            "event2_casquette": "enseignant",
            "event1_start": base_date,
            "event2_start": base_date.replace(hour=14, minute=0),
            "overlap_minutes": 30,
            "detected_at": base_date
        },
        {
            "id": str(uuid4()),
            "event1_id": str(uuid4()),
            "event2_id": str(uuid4()),
            "event1_title": "Réunion labo",
            "event2_title": "Séminaire recherche",
            "event1_casquette": "enseignant",
            "event2_casquette": "chercheur",
            "event1_start": base_date.replace(day=19, hour=16, minute=0),
            "event2_start": base_date.replace(day=19, hour=15, minute=30),
            "overlap_minutes": 30,
            "detected_at": base_date
        }
    ]


# ============================================================================
# Tests Command /conflits (AC7)
# ============================================================================

@pytest.mark.asyncio
async def test_conflits_command_affichage_non_resolus(mock_telegram_update, mock_context, mock_db_pool, sample_unresolved_conflicts):
    """Test AC7: /conflits affiche conflits non résolus détaillés."""
    update = mock_telegram_update
    message = update.message

    db_pool, conn = mock_db_pool

    # Mock DB responses
    # 1. Conflits non résolus
    conn.fetch = AsyncMock(side_effect=[
        # _get_unresolved_conflicts
        [
            {
                **conflict,
                "event1_start": conflict["event1_start"].isoformat(),
                "event2_start": conflict["event2_start"].isoformat()
            }
            for conflict in sample_unresolved_conflicts
        ],
        # _get_month_stats - total
        [{"count": 5}],
        # _get_month_stats - by_casquettes
        [
            {"casquette1": "medecin", "casquette2": "enseignant", "count": 3},
            {"casquette1": "enseignant", "casquette2": "chercheur", "count": 2}
        ]
    ])

    # 2. Résolus semaine
    conn.fetchrow = AsyncMock(side_effect=[
        {"count": 8},  # _get_resolved_week_count
        {"count": 5}   # _get_month_stats total (duplicate)
    ])

    # Call handler
    await handle_conflits_command(update, mock_context)

    # Assertions: Message envoyé
    message.reply_text.assert_called_once()
    dashboard = message.reply_text.call_args[0][0]

    # Vérifier contenu dashboard
    assert "DASHBOARD CONFLITS CALENDRIER" in dashboard
    assert "🔴" in dashboard
    assert "Non résolus" in dashboard
    assert "2 conflits" in dashboard

    # Vérifier détails conflits affichés
    assert "Consultation" in dashboard or "Dr Dupont" in dashboard
    assert "Cours" in dashboard or "L2 Anatomie" in dashboard

    # Vérifier stats
    assert "✅" in dashboard
    assert "Résolus cette semaine" in dashboard
    assert "📊" in dashboard
    assert "Stats mois" in dashboard


@pytest.mark.asyncio
async def test_conflits_command_aucun_conflit(mock_telegram_update, mock_context, mock_db_pool):
    """Test AC7: /conflits message approprié si aucun conflit."""
    update = mock_telegram_update
    message = update.message

    db_pool, conn = mock_db_pool

    # Mock DB responses (aucun conflit)
    conn.fetch = AsyncMock(side_effect=[
        [],  # Aucun conflit non résolu
        [{"count": 0}],  # Stats mois total
        []   # Stats by_casquettes
    ])

    conn.fetchrow = AsyncMock(side_effect=[
        {"count": 0},  # Résolus semaine
        {"count": 0}   # Stats total
    ])

    await handle_conflits_command(update, mock_context)

    message.reply_text.assert_called_once()
    dashboard = message.reply_text.call_args[0][0]

    # Assertions: Message "Aucun conflit"
    assert "Aucun conflit non résolu" in dashboard
    assert "✅" in dashboard


@pytest.mark.asyncio
async def test_conflits_stats_mois_agregation_casquettes(mock_db_pool):
    """Test AC7: Agrégation conflits par casquette pair (médecin ⚡ enseignant)."""
    db_pool, conn = mock_db_pool

    # Mock stats mois
    one_month_ago = datetime.now() - timedelta(days=30)

    conn.fetchrow = AsyncMock(return_value={"count": 10})
    conn.fetch = AsyncMock(return_value=[
        {"casquette1": "medecin", "casquette2": "enseignant", "count": 6},
        {"casquette1": "enseignant", "casquette2": "chercheur", "count": 3},
        {"casquette1": "medecin", "casquette2": "chercheur", "count": 1}
    ])

    # Call function
    stats = await _get_month_stats(db_pool)

    # Assertions: Total correct
    assert stats["total"] == 10

    # Assertions: Répartition par casquettes
    assert len(stats["by_casquettes"]) == 3

    # Vérifier format pair avec émojis
    pair1 = stats["by_casquettes"][0]["pair"]
    assert "🩺" in pair1  # Emoji médecin
    assert "🎓" in pair1  # Emoji enseignant
    assert "⚡" in pair1  # Séparateur
    assert stats["by_casquettes"][0]["count"] == 6


def test_format_dashboard_message_multiple_conflits(sample_unresolved_conflicts):
    """Test AC7: Formatage dashboard avec 2 conflits."""
    resolved_week = 5
    month_stats = {
        "total": 12,
        "by_casquettes": [
            {"pair": "🩺 Médecin ⚡ 🎓 Enseignant", "count": 7},
            {"pair": "🎓 Enseignant ⚡ 🔬 Chercheur", "count": 5}
        ]
    }

    dashboard = _format_dashboard_message(
        sample_unresolved_conflicts,
        resolved_week,
        month_stats
    )

    # Assertions: Structure dashboard
    assert "📊" in dashboard
    assert "DASHBOARD CONFLITS CALENDRIER" in dashboard

    # Section non résolus
    assert "🔴" in dashboard
    assert "Non résolus" in dashboard
    assert "2 conflits" in dashboard

    # Section résolus
    assert "✅" in dashboard
    assert "Résolus cette semaine" in dashboard
    assert "5" in dashboard

    # Section stats
    assert "📊" in dashboard
    assert "Stats mois" in dashboard
    assert "12 conflits" in dashboard

    # Répartition casquettes
    assert "Répartition casquettes" in dashboard
    assert "🩺 Médecin ⚡ 🎓 Enseignant" in dashboard
    assert "7" in dashboard


def test_format_dashboard_message_aucun_conflit():
    """Test AC7: Formatage dashboard sans conflits."""
    dashboard = _format_dashboard_message(
        unresolved_conflicts=[],
        resolved_week=3,
        month_stats={"total": 5, "by_casquettes": []}
    )

    # Assertions: Message "Aucun conflit"
    assert "✅" in dashboard
    assert "Aucun conflit non résolu" in dashboard

    # Stats affichées
    assert "Résolus cette semaine" in dashboard
    assert "3" in dashboard
    assert "Stats mois" in dashboard
    assert "5" in dashboard


def test_format_conflict_line():
    """Test AC7: Formatage ligne conflit détaillée."""
    conflict = {
        "id": str(uuid4()),
        "event1_title": "Consultation très longue avec patient Dr Dupont",
        "event2_title": "Cours L2 Anatomie",
        "event1_casquette": "medecin",
        "event2_casquette": "enseignant",
        "event1_start": datetime(2026, 2, 18, 14, 30),
        "overlap_minutes": 45
    }

    line = _format_conflict_line(conflict)

    # Assertions: Format correct
    assert "📅" in line
    assert "18/02" in line
    assert "14h30" in line

    # Émojis casquettes
    assert "🩺" in line
    assert "🎓" in line
    assert "⚡" in line

    # Titres tronqués
    assert "Consultation" in line
    assert "Cours" in line

    # Durée
    assert "45 min" in line


def test_format_conflict_line_long_overlap():
    """Test AC7: Formatage ligne conflit avec chevauchement >1h."""
    conflict = {
        "id": str(uuid4()),
        "event1_title": "Event1",
        "event2_title": "Event2",
        "event1_casquette": "medecin",
        "event2_casquette": "chercheur",
        "event1_start": datetime(2026, 2, 19, 10, 0),
        "overlap_minutes": 90  # 1h30
    }

    line = _format_conflict_line(conflict)

    # Assertions: Durée formatée 1h30
    assert "1h30" in line


# ============================================================================
# Tests Error Handling
# ============================================================================

@pytest.mark.asyncio
async def test_conflits_command_handles_db_error(mock_telegram_update, mock_context, mock_db_pool):
    """Test AC7: /conflits handle erreur DB gracefully."""
    update = mock_telegram_update
    message = update.message

    db_pool, conn = mock_db_pool

    # Mock DB error
    conn.fetch = AsyncMock(side_effect=Exception("DB connection failed"))

    await handle_conflits_command(update, mock_context)

    # Assertions: Message erreur
    message.reply_text.assert_called_once()
    error_message = message.reply_text.call_args[0][0]
    assert "❌" in error_message
    assert "Erreur" in error_message
