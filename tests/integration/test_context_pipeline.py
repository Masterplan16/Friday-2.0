"""
Tests Intégration - Pipeline Context Manager & Conflict Detection

Story 7.3: Validation pipeline complet multi-casquettes

Tests :
1. Pipeline context manager : email + event → auto-detect
2. Conflict detection pipeline : insertion 2 events → trigger detection
3. Context update propagation : manual override → classifier bias
4. Event classification avec contexte chercheur
5. Email classification avec contexte enseignant
6. Multiple contexts dans même journée
7. Conflict resolution pipeline complet
8. Heartbeat check intégration avec conflicts
"""

import pytest
import asyncpg
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from agents.src.core.models import (
    Casquette,
    ContextSource,
    UserContext,
    Event,
    ConflictStatus,
)
from agents.src.core.context_manager import (
    update_context_from_event,
    get_current_context,
    should_update_context,
)
from agents.src.agents.calendar.conflict_detector import (
    detect_conflicts,
    get_unresolved_conflicts,
)
from agents.src.agents.email.classifier import classify_email
from agents.src.agents.calendar.event_detector import extract_events_from_email


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
async def integration_db():
    """
    Database de test pour intégration.

    NOTE: Nécessite PostgreSQL de test avec migrations appliquées.
    """
    # Se connecter à DB test
    db_url = "postgresql://friday_test:test_password@localhost:5433/friday_test"

    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=5)

    # Cleanup avant test
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE core.user_context RESTART IDENTITY CASCADE")
        await conn.execute("TRUNCATE TABLE core.events RESTART IDENTITY CASCADE")
        await conn.execute("TRUNCATE TABLE core.calendar_conflicts RESTART IDENTITY CASCADE")

        # Initialiser singleton user_context
        await conn.execute(
            """
            INSERT INTO core.user_context (id, current_casquette, updated_by)
            VALUES (1, NULL, 'test_init')
            """
        )

    yield pool

    # Cleanup après test
    await pool.close()


@pytest.fixture
def sample_event_consultation():
    """Événement consultation médical."""
    return Event(
        title="Consultation Dr Dupont",
        start_datetime=datetime(2026, 2, 20, 14, 30),
        end_datetime=datetime(2026, 2, 20, 15, 0),
        location="Cabinet médical",
        participants=["Dr Dupont"],
        event_type="medical",
        casquette=Casquette.MEDECIN,
        confidence=0.95,
        context="RDV cardio Dr Dupont",
    )


@pytest.fixture
def sample_event_cours():
    """Événement cours enseignement."""
    return Event(
        title="Cours Anatomie L2",
        start_datetime=datetime(2026, 2, 20, 14, 0),
        end_datetime=datetime(2026, 2, 20, 16, 0),
        location="Amphi B",
        participants=[],
        event_type="lecture",
        casquette=Casquette.ENSEIGNANT,
        confidence=0.92,
        context="Cours L2 Anatomie",
    )


@pytest.fixture
def sample_event_seminaire():
    """Événement séminaire recherche."""
    return Event(
        title="Séminaire cardiologie interventionnelle",
        start_datetime=datetime(2026, 2, 21, 10, 0),
        end_datetime=datetime(2026, 2, 21, 12, 0),
        location="Salle de conférence",
        participants=["Prof Martin", "Dr Chen"],
        event_type="conference",
        casquette=Casquette.CHERCHEUR,
        confidence=0.88,
        context="Séminaire recherche",
    )


# ============================================================================
# Test 1 : Pipeline Context Manager Auto-Detection
# ============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_context_manager_auto_detect(
    integration_db,
    sample_event_consultation,
):
    """
    Test 1: Pipeline complet context manager auto-detection.

    Scénario :
    1. Insérer événement médical à 14h30
    2. Auto-detect contexte → medecin
    3. Vérifier user_context mis à jour
    """
    async with integration_db.acquire() as conn:
        # Insérer événement dans core.events
        event_id = str(uuid4())
        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            event_id,
            sample_event_consultation.title,
            sample_event_consultation.start_datetime,
            sample_event_consultation.end_datetime,
            sample_event_consultation.location,
            sample_event_consultation.event_type,
            sample_event_consultation.casquette.value,
            sample_event_consultation.confidence,
            sample_event_consultation.context,
        )

        # Trigger context manager auto-detection
        updated = await update_context_from_event(
            event_id=event_id,
            event_casquette=sample_event_consultation.casquette,
            event_start=sample_event_consultation.start_datetime,
            db_pool=integration_db,
        )

        # Assertions: Context mis à jour
        assert updated is True

        # Vérifier user_context
        context = await get_current_context(db_pool=integration_db)
        assert context is not None
        assert context.current_casquette == Casquette.MEDECIN
        assert context.updated_by == ContextSource.EVENT


# ============================================================================
# Test 2 : Pipeline Conflict Detection
# ============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_conflict_detection(
    integration_db,
    sample_event_consultation,
    sample_event_cours,
):
    """
    Test 2: Pipeline conflict detection.

    Scénario :
    1. Insérer 2 événements qui se chevauchent (consultation 14h30 + cours 14h)
    2. Trigger conflict detection
    3. Vérifier conflict inséré dans calendar_conflicts
    """
    async with integration_db.acquire() as conn:
        # Insérer événement 1 (consultation)
        event1_id = str(uuid4())
        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            event1_id,
            sample_event_consultation.title,
            sample_event_consultation.start_datetime,
            sample_event_consultation.end_datetime,
            sample_event_consultation.location,
            sample_event_consultation.event_type,
            sample_event_consultation.casquette.value,
            sample_event_consultation.confidence,
            sample_event_consultation.context,
        )

        # Insérer événement 2 (cours, chevauche événement 1)
        event2_id = str(uuid4())
        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            event2_id,
            sample_event_cours.title,
            sample_event_cours.start_datetime,
            sample_event_cours.end_datetime,
            sample_event_cours.location,
            sample_event_cours.event_type,
            sample_event_cours.casquette.value,
            sample_event_cours.confidence,
            sample_event_cours.context,
        )

        # Trigger conflict detection
        conflicts_detected = await detect_conflicts(
            start_date=datetime(2026, 2, 20).date(),
            end_date=datetime(2026, 2, 21).date(),
            db_pool=integration_db,
        )

        # Assertions: 1 conflit détecté
        assert len(conflicts_detected) == 1

        conflict = conflicts_detected[0]
        assert conflict.event1_id == event1_id or conflict.event2_id == event1_id
        assert conflict.overlap_minutes == 30  # 14h30-15h vs 14h-16h = 30 min overlap

        # Vérifier conflit dans DB
        conflicts_db = await get_unresolved_conflicts(db_pool=integration_db)
        assert len(conflicts_db) == 1


# ============================================================================
# Test 3 : Context Update Propagation
# ============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_context_update_propagation_to_classifier(
    integration_db,
):
    """
    Test 3: Context update propagation vers classifier.

    Scénario :
    1. Mettre contexte manuel = chercheur
    2. Classifier email ambigu
    3. Vérifier bias vers recherche
    """
    async with integration_db.acquire() as conn:
        # Update contexte manuel = chercheur
        await conn.execute(
            """
            UPDATE core.user_context
            SET current_casquette = 'chercheur',
                updated_by = 'manual',
                updated_at = NOW()
            WHERE id = 1
            """
        )

    # Mock LLM adapter
    with patch("agents.src.agents.email.classifier.get_llm_adapter") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_get_llm.return_value = mock_llm

        # Simuler bias vers recherche
        mock_llm.complete.return_value = "recherche"

        # Classifier email ambigu
        result = await classify_email(
            email_text="Réunion équipe pour discuter des résultats de l'étude",
            email_id="test-email-001",
            metadata={"sender": "equipe@labo.fr", "subject": "Réunion"},
            db_pool=integration_db,
        )

        # Assertions: Classification recherche (biaisée)
        assert result.category == "recherche"

        # Vérifier que prompt contenait contexte chercheur
        prompt_call = mock_llm.complete.call_args[1]["prompt"]
        assert "CONTEXTE ACTUEL" in prompt_call
        assert "Chercheur" in prompt_call or "chercheur" in prompt_call.lower()


# ============================================================================
# Test 4 : Event Classification avec Contexte Chercheur
# ============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_event_classification_with_context_chercheur(
    integration_db,
):
    """
    Test 4: Détection événement avec contexte chercheur.

    Scénario :
    1. Mettre contexte = chercheur
    2. Détecter événement ambigu "colloque"
    3. Vérifier casquette = chercheur (biaisé)
    """
    async with integration_db.acquire() as conn:
        # Update contexte = chercheur
        await conn.execute(
            """
            UPDATE core.user_context
            SET current_casquette = 'chercheur',
                updated_by = 'time',
                updated_at = NOW()
            WHERE id = 1
            """
        )

    # Mock Anthropic client
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"events_detected": [{"title": "Colloque cardiologie", "start_datetime": "2026-03-10T09:00:00", "end_datetime": "2026-03-12T18:00:00", "location": "Lyon", "participants": [], "event_type": "conference", "casquette": "chercheur", "confidence": 0.90, "context": "Colloque européen"}], "confidence_overall": 0.90}'
        )
    ]
    mock_client.messages.create.return_value = mock_response

    # Mock anonymize_text
    with patch("agents.src.agents.calendar.event_detector.anonymize_text") as mock_anon:
        mock_anon.return_value = MagicMock(
            anonymized_text="Colloque européen cardiologie du 10 au 12 mars à Lyon",
            mapping={}
        )

        # Détecter événement
        result = await extract_events_from_email(
            email_text="Colloque européen cardiologie du 10 au 12 mars à Lyon",
            email_id="test-event-001",
            metadata={"sender": "conf@esccardio.org", "subject": "Colloque"},
            current_date="2026-02-15",
            anthropic_client=mock_client,
            db_pool=integration_db,
        )

        # Assertions: Événement avec casquette = chercheur
        assert len(result.events_detected) == 1
        assert result.events_detected[0].casquette == Casquette.CHERCHEUR


# ============================================================================
# Test 5 : Email Classification avec Contexte Enseignant
# ============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_email_classification_with_context_enseignant(
    integration_db,
):
    """
    Test 5: Classification email avec contexte enseignant.

    Scénario :
    1. Mettre contexte = enseignant
    2. Classifier email ambigu "examen"
    3. Vérifier catégorie = universite (biaisé)
    """
    async with integration_db.acquire() as conn:
        # Update contexte = enseignant
        await conn.execute(
            """
            UPDATE core.user_context
            SET current_casquette = 'enseignant',
                updated_by = 'time',
                updated_at = NOW()
            WHERE id = 1
            """
        )

    # Mock LLM adapter
    with patch("agents.src.agents.email.classifier.get_llm_adapter") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_get_llm.return_value = mock_llm

        # Simuler bias vers universite
        mock_llm.complete.return_value = "universite"

        # Classifier email ambigu "examen"
        result = await classify_email(
            email_text="Rappel : examen final L2 Anatomie le 15 mars",
            email_id="test-email-002",
            metadata={"sender": "scolarite@univ.fr", "subject": "Examen"},
            db_pool=integration_db,
        )

        # Assertions: Classification universite (biaisée)
        assert result.category == "universite"


# ============================================================================
# Test 6 : Multiple Contexts dans Même Journée
# ============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_contexts_same_day(
    integration_db,
    sample_event_consultation,
    sample_event_seminaire,
):
    """
    Test 6: Multiple contexts dans même journée.

    Scénario :
    1. Événement medecin 14h30 → contexte = medecin
    2. Événement chercheur 10h (lendemain) → contexte = chercheur
    3. Vérifier priorité "event" (dernier événement = chercheur)
    """
    async with integration_db.acquire() as conn:
        # Insérer événement 1 (consultation médical)
        event1_id = str(uuid4())
        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            event1_id,
            sample_event_consultation.title,
            sample_event_consultation.start_datetime,
            sample_event_consultation.end_datetime,
            sample_event_consultation.location,
            sample_event_consultation.event_type,
            sample_event_consultation.casquette.value,
            sample_event_consultation.confidence,
            sample_event_consultation.context,
        )

        # Update context depuis événement 1
        await update_context_from_event(
            event_id=event1_id,
            event_casquette=sample_event_consultation.casquette,
            event_start=sample_event_consultation.start_datetime,
            db_pool=integration_db,
        )

        # Vérifier contexte = medecin
        context = await get_current_context(db_pool=integration_db)
        assert context.current_casquette == Casquette.MEDECIN

        # Insérer événement 2 (séminaire chercheur, lendemain)
        event2_id = str(uuid4())
        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            event2_id,
            sample_event_seminaire.title,
            sample_event_seminaire.start_datetime,
            sample_event_seminaire.end_datetime,
            sample_event_seminaire.location,
            sample_event_seminaire.event_type,
            sample_event_seminaire.casquette.value,
            sample_event_seminaire.confidence,
            sample_event_seminaire.context,
        )

        # Update context depuis événement 2 (plus récent)
        await update_context_from_event(
            event_id=event2_id,
            event_casquette=sample_event_seminaire.casquette,
            event_start=sample_event_seminaire.start_datetime,
            db_pool=integration_db,
        )

        # Vérifier contexte = chercheur (dernier événement)
        context = await get_current_context(db_pool=integration_db)
        assert context.current_casquette == Casquette.CHERCHEUR
        assert context.updated_by == ContextSource.EVENT


# ============================================================================
# Test 7 : Conflict Resolution Pipeline Complet
# ============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_conflict_resolution_pipeline(
    integration_db,
    sample_event_consultation,
    sample_event_cours,
):
    """
    Test 7: Pipeline résolution conflit complet.

    Scénario :
    1. Détecter conflit (consultation vs cours)
    2. Résoudre conflit (cancel event2)
    3. Vérifier statut = resolved
    4. Vérifier événement supprimé
    """
    async with integration_db.acquire() as conn:
        # Insérer 2 événements conflictuels
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
            sample_event_consultation.title,
            sample_event_consultation.start_datetime,
            sample_event_consultation.end_datetime,
            sample_event_consultation.location,
            sample_event_consultation.event_type,
            sample_event_consultation.casquette.value,
            sample_event_consultation.confidence,
            sample_event_consultation.context,
        )

        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            event2_id,
            sample_event_cours.title,
            sample_event_cours.start_datetime,
            sample_event_cours.end_datetime,
            sample_event_cours.location,
            sample_event_cours.event_type,
            sample_event_cours.casquette.value,
            sample_event_cours.confidence,
            sample_event_cours.context,
        )

        # Détecter conflit
        conflicts = await detect_conflicts(
            start_date=datetime(2026, 2, 20).date(),
            end_date=datetime(2026, 2, 21).date(),
            db_pool=integration_db,
        )

        assert len(conflicts) == 1
        conflict_id = conflicts[0].id

        # Résoudre conflit : cancel event2
        await conn.execute(
            """
            UPDATE core.calendar_conflicts
            SET resolved = TRUE,
                resolution_type = 'cancel',
                cancelled_event_id = $1,
                resolved_at = NOW()
            WHERE id = $2
            """,
            event2_id,
            conflict_id,
        )

        # Supprimer événement 2 (annulé)
        await conn.execute(
            "UPDATE core.events SET deleted = TRUE WHERE id = $1",
            event2_id,
        )

        # Vérifier conflit résolu
        resolved_conflict = await conn.fetchrow(
            "SELECT * FROM core.calendar_conflicts WHERE id = $1",
            conflict_id,
        )

        assert resolved_conflict["resolved"] is True
        assert resolved_conflict["resolution_type"] == "cancel"
        assert resolved_conflict["cancelled_event_id"] == event2_id

        # Vérifier événement supprimé
        deleted_event = await conn.fetchrow(
            "SELECT deleted FROM core.events WHERE id = $1",
            event2_id,
        )
        assert deleted_event["deleted"] is True


# ============================================================================
# Test 8 : Heartbeat Check Intégration Conflicts
# ============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_heartbeat_check_integration_conflicts(
    integration_db,
    sample_event_consultation,
    sample_event_cours,
):
    """
    Test 8: Heartbeat check intégration avec conflicts.

    Scénario :
    1. Insérer 2 événements conflictuels (demain)
    2. Appeler heartbeat check calendar_conflicts
    3. Vérifier notification générée
    """
    from agents.src.core.heartbeat_checks.calendar_conflicts import (
        check_calendar_conflicts,
    )

    async with integration_db.acquire() as conn:
        # Insérer 2 événements conflictuels (demain)
        tomorrow = datetime.now() + timedelta(days=1)

        event1_start = tomorrow.replace(hour=14, minute=30, second=0, microsecond=0)
        event2_start = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)

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
            "Consultation Dr Dupont",
            event1_start,
            event1_start + timedelta(minutes=30),
            "Cabinet",
            "medical",
            "medecin",
            0.95,
            "RDV",
        )

        await conn.execute(
            """
            INSERT INTO core.events (
                id, title, start_datetime, end_datetime,
                location, event_type, casquette, confidence, context
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            event2_id,
            "Cours L2",
            event2_start,
            event2_start + timedelta(hours=2),
            "Amphi",
            "lecture",
            "enseignant",
            0.92,
            "Cours",
        )

        # Détecter conflit
        await detect_conflicts(
            start_date=tomorrow.date(),
            end_date=(tomorrow + timedelta(days=1)).date(),
            db_pool=integration_db,
        )

    # Appeler heartbeat check
    context = {
        "time": datetime.now(),
        "hour": 14,
        "is_weekend": False,
        "quiet_hours": False,
    }

    result = await check_calendar_conflicts(context, db_pool=integration_db)

    # Assertions: Notification générée
    assert result.notify is True
    assert "conflit" in result.message.lower()
    assert result.action == "view_conflicts"
    assert result.payload["conflict_count"] == 1
