"""
Tests End-to-End - Multi-casquettes & Conflits Calendrier

Story 7.3: Validation scénarios utilisateur complets

Tests critiques :
1. /casquette command Telegram bot (inline buttons)
2. Conflict detection E2E (email → event → conflict → notification)
3. Heartbeat conflicts (check périodique + quiet hours)
4. Full user journey (contexte → email → conflict → résolution)

Requiert PostgreSQL de test avec migrations 007 + 037 appliquées.
"""

import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import asyncpg
import pytest
from agents.src.agents.calendar.conflict_detector import (
    detect_calendar_conflicts,
    get_conflicts_range,
    save_conflict_to_db,
)
from agents.src.agents.calendar.models import CalendarConflict
from agents.src.core.context_manager import ContextManager
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

    try:
        pool = await asyncpg.create_pool(db_url, min_size=2, max_size=5)
    except (OSError, asyncpg.PostgresError):
        pytest.skip("PostgreSQL test instance not available")

    # Cleanup complet
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM knowledge.calendar_conflicts")
        await conn.execute("DELETE FROM knowledge.entities WHERE entity_type = 'EVENT'")
        await conn.execute("DELETE FROM core.user_context")

        # Init singleton user_context
        await conn.execute(
            """
            INSERT INTO core.user_context (id, current_casquette, updated_by)
            VALUES (1, NULL, 'system')
            ON CONFLICT (id) DO NOTHING
            """
        )

    yield pool

    # Cleanup
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM knowledge.calendar_conflicts")
        await conn.execute("DELETE FROM knowledge.entities WHERE entity_type = 'EVENT'")

    await pool.close()


@pytest.fixture
def mock_redis():
    """Mock Redis client pour ContextManager."""
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.setex = AsyncMock()
    redis_mock.delete = AsyncMock()
    redis_mock.ping = AsyncMock()
    return redis_mock


@pytest.fixture
def mock_telegram_bot():
    """Mock Telegram bot pour tests."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=123))
    bot.edit_message_text = AsyncMock()
    bot.answer_callback_query = AsyncMock()
    return bot


async def _insert_event_entity(
    conn,
    title: str,
    casquette: str,
    start_datetime: datetime,
    end_datetime: datetime,
    status: str = "confirmed",
    location: str = "",
    event_type: str = "meeting",
    event_id: str = None,
) -> str:
    """Helper: insère un événement dans knowledge.entities avec JSONB properties."""
    if event_id is None:
        event_id = str(uuid4())

    properties = json.dumps(
        {
            "title": title,
            "casquette": casquette,
            "start_datetime": start_datetime.isoformat(),
            "end_datetime": end_datetime.isoformat(),
            "status": status,
            "location": location,
            "event_type": event_type,
        }
    )

    await conn.execute(
        """
        INSERT INTO knowledge.entities (
            id, name, entity_type, properties, confidence
        ) VALUES ($1, $2, 'EVENT', $3::jsonb, 0.95)
        """,
        event_id,
        title,
        properties,
    )
    return event_id


# ============================================================================
# Test 1 : /casquette Command Telegram
# ============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_casquette_command_telegram(e2e_db, mock_redis, mock_telegram_bot):
    """
    Test E2E 1: /casquette command Telegram bot.

    Scénario complet :
    1. User envoie /casquette enseignant
    2. Handler met à jour contexte DB
    3. Vérifier contexte = enseignant, updated_by = manual
    """
    from bot.handlers.casquette_commands import handle_casquette_command

    # Mock Telegram Update (/casquette enseignant)
    mock_message = MagicMock()
    mock_message.chat.id = 123456789
    mock_message.from_user.id = 123456789
    mock_message.text = "/casquette enseignant"
    mock_message.reply_text = AsyncMock()

    mock_update = MagicMock()
    mock_update.message = mock_message

    # Mock Telegram context avec bot_data
    mock_context = MagicMock()
    mock_context.args = ["enseignant"]
    mock_context.bot_data = {
        "db_pool": e2e_db,
        "redis_client": mock_redis,
    }

    # Patch OWNER_USER_ID pour autoriser l'utilisateur
    with patch.dict("os.environ", {"OWNER_USER_ID": "123456789"}):
        await handle_casquette_command(mock_update, mock_context)

    # Assertions: Bot a répondu
    assert mock_message.reply_text.called

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
    1. Extraire événements depuis email (mock Claude)
    2. Insérer événements dans knowledge.entities
    3. Détecter conflits
    4. Sauvegarder conflit en DB
    5. Envoyer notification Telegram
    """
    from agents.src.agents.calendar.event_detector import extract_events_from_email
    from bot.handlers.conflict_notifications import send_conflict_alert

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
            text=json.dumps(
                {
                    "events_detected": [
                        {
                            "title": "Consultation Dr Dupont",
                            "start_datetime": "2026-02-21T14:30:00+00:00",
                            "end_datetime": "2026-02-21T15:00:00+00:00",
                            "location": "Cabinet",
                            "participants": ["Dr Dupont"],
                            "event_type": "medical",
                            "casquette": "medecin",
                            "confidence": 0.95,
                            "context": "Consultation Dr Dupont demain 14h30",
                        },
                        {
                            "title": "Cours L2 Anatomie",
                            "start_datetime": "2026-02-21T14:00:00+00:00",
                            "end_datetime": "2026-02-21T16:00:00+00:00",
                            "location": "Amphi B",
                            "participants": [],
                            "event_type": "lecture",
                            "casquette": "enseignant",
                            "confidence": 0.92,
                            "context": "Cours L2 Anatomie demain 14h",
                        },
                    ],
                    "confidence_overall": 0.92,
                }
            )
        )
    ]
    mock_client.messages.create.return_value = mock_response

    # Mock anonymize_text
    with patch("agents.src.agents.calendar.event_detector.anonymize_text") as mock_anon:
        mock_anon.return_value = MagicMock(anonymized_text=email_text, mapping={})

        # Étape 1: Extraire événements
        result = await extract_events_from_email(
            email_text=email_text,
            email_id="test-email-conflict",
            metadata={"sender": "test@test.fr", "subject": "Rappels"},
            current_date="2026-02-20",
            anthropic_client=mock_client,
            db_pool=e2e_db,
        )

        assert len(result.events_detected) == 2

    # Étape 2: Insérer événements dans knowledge.entities
    async with e2e_db.acquire() as conn:
        for event in result.events_detected:
            await _insert_event_entity(
                conn,
                title=event.title,
                casquette=event.casquette.value,
                start_datetime=event.start_datetime,
                end_datetime=event.end_datetime,
                location=event.location or "",
                event_type=event.event_type or "meeting",
            )

    # Étape 3: Détecter conflits
    conflicts = await detect_calendar_conflicts(
        target_date=date(2026, 2, 21),
        db_pool=e2e_db,
    )

    assert len(conflicts) == 1
    assert conflicts[0].overlap_minutes == 30  # 14h30-15h00 overlap

    # Étape 4: Sauvegarder conflit en DB
    conflict_id = await save_conflict_to_db(conflicts[0], e2e_db)
    assert conflict_id is not None

    # Étape 5: Envoyer notification Telegram
    await send_conflict_alert(
        bot=mock_telegram_bot,
        conflict=conflicts[0],
        conflict_id=conflict_id,
    )

    # Assertions: Notification envoyée
    assert mock_telegram_bot.send_message.called


# ============================================================================
# Test 3 : Heartbeat Conflicts Periodic Check E2E
# ============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_heartbeat_conflicts_periodic_check_e2e(e2e_db):
    """
    Test E2E 3: Heartbeat conflicts check périodique.

    Scénario complet :
    1. Insérer 2 événements conflictuels (demain)
    2. Heartbeat Engine check (9h matin, NOT quiet hours) → notification
    3. Heartbeat Engine check (23h, quiet hours) → SKIP
    """
    from agents.src.core.heartbeat_checks.calendar_conflicts import check_calendar_conflicts

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    event1_start = tomorrow.replace(hour=14, minute=30, second=0, microsecond=0)
    event2_start = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)

    async with e2e_db.acquire() as conn:
        await _insert_event_entity(
            conn,
            title="Consultation urgente",
            casquette="medecin",
            start_datetime=event1_start,
            end_datetime=event1_start + timedelta(minutes=30),
            event_type="medical",
        )

        await _insert_event_entity(
            conn,
            title="Examen L3",
            casquette="enseignant",
            start_datetime=event2_start,
            end_datetime=event2_start + timedelta(hours=2),
            event_type="exam",
        )

    # Check daytime (9h matin, NOT quiet hours)
    context_daytime = {
        "time": datetime(2026, 2, 20, 9, 0, tzinfo=timezone.utc),
        "hour": 9,
        "is_weekend": False,
        "quiet_hours": False,
    }

    result_daytime = await check_calendar_conflicts(
        context_daytime,
        db_pool=e2e_db,
    )

    assert result_daytime.notify is True
    assert "conflit" in result_daytime.message.lower()
    assert result_daytime.action == "view_conflicts"

    # Check quiet hours (23h → SKIP)
    context_quiet = {
        "time": datetime(2026, 2, 20, 23, 0, tzinfo=timezone.utc),
        "hour": 23,
        "is_weekend": False,
        "quiet_hours": True,
    }

    result_quiet = await check_calendar_conflicts(
        context_quiet,
        db_pool=e2e_db,
    )

    assert result_quiet.notify is False


# ============================================================================
# Test 4 : Full User Journey E2E
# ============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_user_journey_e2e(e2e_db, mock_redis, mock_telegram_bot):
    """
    Test E2E 4: User journey complet multi-casquettes.

    Scénario complet réaliste :
    1. User change contexte /casquette chercheur
    2. Recevoir email → extraction événement (biaisé chercheur)
    3. Insérer événements conflictuels
    4. Heartbeat détecte conflit
    5. Résolution conflit via DB
    """
    from agents.src.agents.calendar.event_detector import extract_events_from_email
    from agents.src.core.heartbeat_checks.calendar_conflicts import check_calendar_conflicts
    from bot.handlers.casquette_commands import handle_casquette_command

    # Étape 1: User change contexte chercheur via /casquette
    mock_message = MagicMock()
    mock_message.chat.id = 123
    mock_message.from_user.id = 123
    mock_message.text = "/casquette chercheur"
    mock_message.reply_text = AsyncMock()

    mock_update = MagicMock()
    mock_update.message = mock_message

    mock_context = MagicMock()
    mock_context.args = ["chercheur"]
    mock_context.bot_data = {
        "db_pool": e2e_db,
        "redis_client": mock_redis,
    }

    with patch.dict("os.environ", {"OWNER_USER_ID": "123"}):
        await handle_casquette_command(mock_update, mock_context)

    # Vérifier contexte = chercheur
    async with e2e_db.acquire() as conn:
        row = await conn.fetchrow("SELECT current_casquette FROM core.user_context WHERE id = 1")
        assert row["current_casquette"] == "chercheur"

    # Étape 2: Recevoir email → extraction événement
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text=json.dumps(
                {
                    "events_detected": [
                        {
                            "title": "Séminaire recherche",
                            "start_datetime": "2026-02-21T16:30:00+00:00",
                            "end_datetime": "2026-02-21T18:00:00+00:00",
                            "location": "Labo 301",
                            "participants": [],
                            "event_type": "conference",
                            "casquette": "chercheur",
                            "confidence": 0.88,
                            "context": "Séminaire labo",
                        }
                    ],
                    "confidence_overall": 0.88,
                }
            )
        )
    ]
    mock_client.messages.create.return_value = mock_response

    with patch("agents.src.agents.calendar.event_detector.anonymize_text") as mock_anon:
        mock_anon.return_value = MagicMock(
            anonymized_text="Séminaire recherche vendredi 16h30", mapping={}
        )

        result = await extract_events_from_email(
            email_text="Séminaire recherche vendredi 16h30",
            email_id="test-journey",
            current_date="2026-02-20",
            anthropic_client=mock_client,
            db_pool=e2e_db,
        )
        assert len(result.events_detected) == 1

    # Étape 3: Insérer événements conflictuels dans knowledge.entities
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)

    async with e2e_db.acquire() as conn:
        # Événement 1: Garde CHU (médecin) 10h-18h
        await _insert_event_entity(
            conn,
            title="Garde CHU",
            casquette="medecin",
            start_datetime=tomorrow.replace(hour=10, minute=0),
            end_datetime=tomorrow.replace(hour=18, minute=0),
            event_type="medical",
        )

        # Événement 2: Cours (enseignant) 14h-16h → chevauche garde
        await _insert_event_entity(
            conn,
            title="Cours Physiologie",
            casquette="enseignant",
            start_datetime=tomorrow.replace(hour=14, minute=0),
            end_datetime=tomorrow.replace(hour=16, minute=0),
            event_type="lecture",
        )

    # Étape 4: Heartbeat détecte conflit
    heartbeat_ctx = {
        "time": datetime.now(timezone.utc),
        "hour": 9,
        "is_weekend": False,
        "quiet_hours": False,
    }

    hb_result = await check_calendar_conflicts(heartbeat_ctx, db_pool=e2e_db)
    assert hb_result.notify is True
    assert hb_result.payload["conflict_count"] == 1

    # Étape 5: Résolution conflit via DB
    # Sauvegarder d'abord le conflit
    conflicts = await get_conflicts_range(
        start_date=tomorrow.date(),
        end_date=(tomorrow + timedelta(days=1)).date(),
        db_pool=e2e_db,
    )
    assert len(conflicts) == 1

    conflict_id = await save_conflict_to_db(conflicts[0], e2e_db)
    assert conflict_id is not None

    # Résoudre le conflit
    async with e2e_db.acquire() as conn:
        await conn.execute(
            """
            UPDATE knowledge.calendar_conflicts
            SET resolved = TRUE, resolution_action = 'move', resolved_at = NOW()
            WHERE id = $1
            """,
            conflict_id,
        )

        # Vérifier résolution
        resolved = await conn.fetchrow(
            "SELECT resolved, resolution_action FROM knowledge.calendar_conflicts WHERE id = $1",
            conflict_id,
        )
        assert resolved["resolved"] is True
        assert resolved["resolution_action"] == "move"
