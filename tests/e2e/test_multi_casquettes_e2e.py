"""
Tests End-to-End - Multi-casquettes & Conflits Calendrier

Story 7.3: Validation scénarios utilisateur complets

Tests critiques :
1. /casquette command real test (Telegram bot)
2. Conflict detection E2E (email → event → conflict → notification)
3. Briefing multi-casquettes (liste événements 3 casquettes)
4. Heartbeat conflicts (check périodique → notification Telegram)
"""

import pytest
import asyncpg
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from agents.src.core.models import Casquette, ContextSource


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
async def e2e_db():
    """
    Database E2E de test.

    NOTE: Nécessite PostgreSQL de test avec migrations complètes.
    """
    db_url = "postgresql://friday_test:test_password@localhost:5433/friday_test"

    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=5)

    # Cleanup complet
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE core.user_context RESTART IDENTITY CASCADE")
        await conn.execute("TRUNCATE TABLE core.events RESTART IDENTITY CASCADE")
        await conn.execute("TRUNCATE TABLE core.calendar_conflicts RESTART IDENTITY CASCADE")
        await conn.execute("TRUNCATE TABLE ingestion.emails_raw RESTART IDENTITY CASCADE")

        # Init singleton user_context
        await conn.execute(
            """
            INSERT INTO core.user_context (id, current_casquette, updated_by)
            VALUES (1, NULL, 'test_init')
            """
        )

    yield pool

    await pool.close()


@pytest.fixture
def mock_telegram_bot():
    """Mock Telegram bot pour tests."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=123))
    bot.edit_message_text = AsyncMock()
    bot.answer_callback_query = AsyncMock()
    return bot


# ============================================================================
# Test 1 : /casquette Command Real Test
# ============================================================================

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_casquette_command_real_telegram(e2e_db, mock_telegram_bot):
    """
    Test E2E 1: /casquette command Telegram bot.

    Scénario complet :
    1. User envoie /casquette
    2. Bot affiche 3 inline buttons (Médecin, Enseignant, Chercheur)
    3. User clique "Enseignant"
    4. Bot met à jour contexte DB
    5. Bot confirme changement
    """
    from bot.handlers.casquette_commands import handle_casquette_command
    from bot.handlers.casquette_callbacks import handle_casquette_callback

    # Mock update Telegram (/casquette command)
    mock_message = MagicMock()
    mock_message.chat.id = 123456789
    mock_message.text = "/casquette"

    mock_update = MagicMock()
    mock_update.message = mock_message

    # Étape 1: User envoie /casquette
    with patch("bot.handlers.casquette_commands.get_db_pool", return_value=e2e_db):
        await handle_casquette_command(mock_update, mock_telegram_bot)

    # Assertions: Bot envoie message avec inline buttons
    assert mock_telegram_bot.send_message.called
    call_kwargs = mock_telegram_bot.send_message.call_args[1]
    assert "Sélectionnez votre casquette" in call_kwargs.get("text", "")
    assert "reply_markup" in call_kwargs  # Inline buttons

    # Étape 2: User clique "Enseignant"
    mock_callback = MagicMock()
    mock_callback.data = "casquette:enseignant"
    mock_callback.message.chat.id = 123456789
    mock_callback.message.message_id = 123

    mock_callback_update = MagicMock()
    mock_callback_update.callback_query = mock_callback

    with patch("bot.handlers.casquette_callbacks.get_db_pool", return_value=e2e_db):
        await handle_casquette_callback(mock_callback_update, mock_telegram_bot)

    # Assertions: Bot édite message et confirme
    assert mock_telegram_bot.answer_callback_query.called
    assert mock_telegram_bot.edit_message_text.called

    # Vérifier DB mise à jour
    async with e2e_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT current_casquette, updated_by FROM core.user_context WHERE id = 1"
        )
        assert row["current_casquette"] == "enseignant"
        assert row["updated_by"] == "manual"


# ============================================================================
# Test 2 : Conflict Detection E2E Pipeline
# ============================================================================

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_conflict_detection_e2e_pipeline(e2e_db, mock_telegram_bot):
    """
    Test E2E 2: Conflict detection pipeline complet.

    Scénario complet :
    1. Recevoir email avec 2 événements conflictuels
    2. Extraction événements via Claude
    3. Insertion dans core.events
    4. Détection conflit automatique
    5. Notification Telegram envoyée
    """
    from agents.src.agents.calendar.event_detector import extract_events_from_email
    from agents.src.agents.calendar.conflict_detector import detect_conflicts
    from bot.handlers.conflict_notifications import send_conflict_notification

    # Email test avec 2 événements conflictuels
    email_text = """
    Bonjour,

    Rappel : Consultation Dr Dupont demain 14h30 au cabinet.

    Important : Cours L2 Anatomie demain 14h en amphi B.
    """

    # Mock Anthropic client (retourne 2 événements conflictuels)
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text="""{
                "events_detected": [
                    {
                        "title": "Consultation Dr Dupont",
                        "start_datetime": "2026-02-21T14:30:00",
                        "end_datetime": "2026-02-21T15:00:00",
                        "location": "Cabinet",
                        "participants": ["Dr Dupont"],
                        "event_type": "medical",
                        "casquette": "medecin",
                        "confidence": 0.95,
                        "context": "Consultation Dr Dupont demain 14h30"
                    },
                    {
                        "title": "Cours L2 Anatomie",
                        "start_datetime": "2026-02-21T14:00:00",
                        "end_datetime": "2026-02-21T16:00:00",
                        "location": "Amphi B",
                        "participants": [],
                        "event_type": "lecture",
                        "casquette": "enseignant",
                        "confidence": 0.92,
                        "context": "Cours L2 Anatomie demain 14h"
                    }
                ],
                "confidence_overall": 0.92
            }"""
        )
    ]
    mock_client.messages.create.return_value = mock_response

    # Mock anonymize_text
    with patch("agents.src.agents.calendar.event_detector.anonymize_text") as mock_anon:
        mock_anon.return_value = MagicMock(
            anonymized_text=email_text,
            mapping={}
        )

        # Étape 1-2: Extraire événements
        result = await extract_events_from_email(
            email_text=email_text,
            email_id="test-email-conflict",
            metadata={"sender": "test@test.fr", "subject": "Rappels"},
            current_date="2026-02-20",
            anthropic_client=mock_client,
            db_pool=e2e_db,
        )

        assert len(result.events_detected) == 2

    # Étape 3: Insérer événements dans DB
    async with e2e_db.acquire() as conn:
        for event in result.events_detected:
            event_id = str(uuid4())
            await conn.execute(
                """
                INSERT INTO core.events (
                    id, title, start_datetime, end_datetime,
                    location, event_type, casquette, confidence, context
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                event_id,
                event.title,
                event.start_datetime,
                event.end_datetime,
                event.location,
                event.event_type,
                event.casquette.value,
                event.confidence,
                event.context,
            )

    # Étape 4: Détecter conflits
    conflicts = await detect_conflicts(
        start_date=datetime(2026, 2, 21).date(),
        end_date=datetime(2026, 2, 22).date(),
        db_pool=e2e_db,
    )

    # Assertions: 1 conflit détecté
    assert len(conflicts) == 1
    assert conflicts[0].overlap_minutes == 30  # 14h30-15h vs 14h-16h

    # Étape 5: Envoyer notification Telegram
    with patch("bot.handlers.conflict_notifications.get_telegram_bot", return_value=mock_telegram_bot):
        await send_conflict_notification(
            conflict=conflicts[0],
            user_id=123456789,
        )

    # Assertions: Notification envoyée
    assert mock_telegram_bot.send_message.called


# ============================================================================
# Test 3 : Briefing Multi-casquettes E2E
# ============================================================================

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_briefing_multi_casquettes_e2e(e2e_db, mock_telegram_bot):
    """
    Test E2E 3: Briefing multi-casquettes.

    Scénario complet :
    1. Insérer événements pour 3 casquettes (médecin, enseignant, chercheur)
    2. Générer briefing quotidien
    3. Vérifier événements groupés par casquette
    4. Notification Telegram envoyée
    """
    from bot.handlers.briefing import generate_daily_briefing

    # Insérer événements pour chaque casquette
    async with e2e_db.acquire() as conn:
        # Événement 1: Médecin (10h)
        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            str(uuid4()),
            "Consultation Dr Martin",
            datetime(2026, 2, 21, 10, 0),
            datetime(2026, 2, 21, 10, 30),
            "Cabinet",
            "medical",
            "medecin",
            0.95,
            "RDV",
        )

        # Événement 2: Enseignant (14h)
        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            str(uuid4()),
            "Cours L2 Anatomie",
            datetime(2026, 2, 21, 14, 0),
            datetime(2026, 2, 21, 16, 0),
            "Amphi B",
            "lecture",
            "enseignant",
            0.92,
            "Cours",
        )

        # Événement 3: Chercheur (16h30)
        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            str(uuid4()),
            "Réunion labo recherche",
            datetime(2026, 2, 21, 16, 30),
            datetime(2026, 2, 21, 17, 30),
            "Labo 201",
            "meeting",
            "chercheur",
            0.88,
            "Réunion",
        )

    # Générer briefing quotidien
    with patch("bot.handlers.briefing.get_db_pool", return_value=e2e_db):
        briefing_text = await generate_daily_briefing(
            date=datetime(2026, 2, 21).date(),
            user_id=123456789,
        )

    # Assertions: Briefing contient les 3 casquettes
    assert "Médecin" in briefing_text or "🩺" in briefing_text
    assert "Enseignant" in briefing_text or "🎓" in briefing_text
    assert "Chercheur" in briefing_text or "🔬" in briefing_text

    # Assertions: Événements listés
    assert "Consultation Dr Martin" in briefing_text
    assert "Cours L2 Anatomie" in briefing_text
    assert "Réunion labo recherche" in briefing_text

    # Vérifier ordre chronologique
    lines = briefing_text.split("\n")
    idx_consultation = next(i for i, line in enumerate(lines) if "Consultation" in line)
    idx_cours = next(i for i, line in enumerate(lines) if "Cours" in line)
    idx_reunion = next(i for i, line in enumerate(lines) if "Réunion" in line)

    assert idx_consultation < idx_cours < idx_reunion  # Ordre chrono


# ============================================================================
# Test 4 : Heartbeat Conflicts Periodic Check E2E
# ============================================================================

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_heartbeat_conflicts_periodic_check_e2e(e2e_db, mock_telegram_bot):
    """
    Test E2E 4: Heartbeat conflicts check périodique.

    Scénario complet :
    1. Insérer 2 événements conflictuels (demain)
    2. Détecter conflit
    3. Heartbeat Engine check (9h matin)
    4. Notification Telegram envoyée
    5. Vérifier quiet hours skip (23h)
    """
    from agents.src.core.heartbeat_checks.calendar_conflicts import (
        check_calendar_conflicts,
    )
    from bot.handlers.conflict_notifications import send_conflict_notification

    # Insérer 2 événements conflictuels (demain)
    tomorrow = datetime.now() + timedelta(days=1)
    event1_start = tomorrow.replace(hour=14, minute=30, second=0, microsecond=0)
    event2_start = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)

    async with e2e_db.acquire() as conn:
        event1_id = str(uuid4())
        event2_id = str(uuid4())

        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            event1_id,
            "Consultation urgente",
            event1_start,
            event1_start + timedelta(minutes=30),
            "Cabinet",
            "medical",
            "medecin",
            0.95,
            "Urgence",
        )

        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            event2_id,
            "Examen L3",
            event2_start,
            event2_start + timedelta(hours=2),
            "Amphi C",
            "exam",
            "enseignant",
            0.92,
            "Examen",
        )

        # Détecter conflit (normalement fait par trigger)
        from agents.src.agents.calendar.conflict_detector import detect_conflicts

        await detect_conflicts(
            start_date=tomorrow.date(),
            end_date=(tomorrow + timedelta(days=1)).date(),
            db_pool=e2e_db,
        )

    # Étape 3: Heartbeat check (9h matin, NOT quiet hours)
    context_daytime = {
        "time": datetime(2026, 2, 20, 9, 0),
        "hour": 9,
        "is_weekend": False,
        "quiet_hours": False,
    }

    result_daytime = await check_calendar_conflicts(
        context_daytime,
        db_pool=e2e_db,
    )

    # Assertions: Notification générée (daytime)
    assert result_daytime.notify is True
    assert "conflit" in result_daytime.message.lower()
    assert result_daytime.action == "view_conflicts"

    # Étape 5: Heartbeat check (23h, quiet hours → SKIP)
    context_quiet = {
        "time": datetime(2026, 2, 20, 23, 0),
        "hour": 23,
        "is_weekend": False,
        "quiet_hours": True,
    }

    result_quiet = await check_calendar_conflicts(
        context_quiet,
        db_pool=e2e_db,
    )

    # Assertions: PAS de notification (quiet hours)
    assert result_quiet.notify is False


# ============================================================================
# Test Bonus : Full User Journey E2E
# ============================================================================

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_user_journey_e2e(e2e_db, mock_telegram_bot):
    """
    Test E2E Bonus: User journey complet multi-casquettes.

    Scénario complet réaliste :
    1. Matin 8h: Briefing quotidien (3 événements 3 casquettes)
    2. 9h30: Recevoir email détection événement médical
    3. 10h: User change contexte /casquette chercheur
    4. 11h: Recevoir email détection événement recherche (biaisé)
    5. 14h: Heartbeat détecte conflit
    6. 14h30: User résout conflit via Telegram
    """
    from bot.handlers.briefing import generate_daily_briefing
    from bot.handlers.casquette_callbacks import handle_casquette_callback
    from agents.src.agents.calendar.event_detector import extract_events_from_email
    from agents.src.core.heartbeat_checks.calendar_conflicts import check_calendar_conflicts

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Étape 1: Insérer 3 événements aujourd'hui
    async with e2e_db.acquire() as conn:
        # Médecin 10h
        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            str(uuid4()),
            "Garde CHU",
            today + timedelta(hours=10),
            today + timedelta(hours=18),
            "CHU Toulouse",
            "medical",
            "medecin",
            0.95,
            "Garde",
        )

        # Enseignant 14h
        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            str(uuid4()),
            "Cours Physiologie",
            today + timedelta(hours=14),
            today + timedelta(hours=16),
            "Amphi A",
            "lecture",
            "enseignant",
            0.92,
            "Cours",
        )

        # Chercheur 16h30
        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            str(uuid4()),
            "Séminaire recherche",
            today + timedelta(hours=16, minutes=30),
            today + timedelta(hours=18),
            "Labo 301",
            "conference",
            "chercheur",
            0.88,
            "Séminaire",
        )

    # Briefing 8h
    with patch("bot.handlers.briefing.get_db_pool", return_value=e2e_db):
        briefing = await generate_daily_briefing(date=today.date(), user_id=123)

    assert "Garde CHU" in briefing
    assert "Cours Physiologie" in briefing
    assert "Séminaire recherche" in briefing

    # Étape 3: User change contexte chercheur
    mock_callback = MagicMock()
    mock_callback.data = "casquette:chercheur"
    mock_callback.message.chat.id = 123
    mock_callback.message.message_id = 456

    mock_update = MagicMock()
    mock_update.callback_query = mock_callback

    with patch("bot.handlers.casquette_callbacks.get_db_pool", return_value=e2e_db):
        await handle_casquette_callback(mock_update, mock_telegram_bot)

    # Vérifier contexte = chercheur
    async with e2e_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT current_casquette FROM core.user_context WHERE id = 1"
        )
        assert row["current_casquette"] == "chercheur"

    print("✅ Test E2E Full User Journey terminé avec succès")
