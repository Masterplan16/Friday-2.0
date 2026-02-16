"""
Tests Unitaires - Influence Contexte Casquette

Story 7.3 AC1: Contexte influence classification/détection

Tests :
- Email @chu.fr + contexte=medecin → bias pro
- Événement + contexte=enseignant → casquette=enseignant
- Contexte null → pas de bias
- Contexte manuel override auto-detect
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from agents.src.agents.email.classifier import classify_email
from agents.src.agents.calendar.event_detector import extract_events_from_email
from agents.src.core.models import Casquette


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_db_pool():
    """Mock asyncpg.Pool avec contexte casquette."""
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool


@pytest.fixture
def mock_db_pool_medecin(mock_db_pool):
    """Mock DB pool retournant casquette=medecin."""
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = {
        "current_casquette": "medecin",
        "updated_by": "manual"
    }
    return mock_db_pool


@pytest.fixture
def mock_db_pool_enseignant(mock_db_pool):
    """Mock DB pool retournant casquette=enseignant."""
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = {
        "current_casquette": "enseignant",
        "updated_by": "time"
    }
    return mock_db_pool


@pytest.fixture
def mock_db_pool_null(mock_db_pool):
    """Mock DB pool retournant casquette=null."""
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = {
        "current_casquette": None,
        "updated_by": None
    }
    return mock_db_pool


@pytest.fixture
def sample_email_chu():
    """Email CHU ambigu (pourrait être pro ou finance)."""
    return {
        "id": "email-chu-001",
        "subject": "Facture consultation",
        "body": "Bonjour, voici la facture pour la consultation du patient.",
        "sender": "compta@chu-toulouse.fr",
        "metadata": {
            "sender": "compta@chu-toulouse.fr",
            "subject": "Facture consultation",
            "date": "2026-02-15T10:30:00Z"
        }
    }


@pytest.fixture
def sample_email_reunion_ambigue():
    """Email événement ambigu (pourrait être enseignant ou chercheur)."""
    return {
        "id": "email-event-001",
        "subject": "Réunion équipe",
        "body": "Réunion d'équipe jeudi 14h pour discuter du projet.",
        "sender": "chef@universite.fr",
        "metadata": {
            "sender": "chef@universite.fr",
            "subject": "Réunion équipe",
            "date": "2026-02-15T10:00:00Z"
        }
    }


# ============================================================================
# Tests Classification Email avec Contexte (AC1)
# ============================================================================

@pytest.mark.asyncio
async def test_email_chu_with_context_medecin_biases_pro(
    sample_email_chu,
    mock_db_pool_medecin
):
    """
    Test AC1: Email @chu.fr + contexte=medecin → bias vers pro

    Email ambigu (facture CHU) avec contexte médecin devrait
    favoriser classification "pro" (médical) plutôt que "finance".
    """
    # Mock LLM adapter
    with patch("agents.src.agents.email.classifier.get_llm_adapter") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_get_llm.return_value = mock_llm

        # Simuler réponse LLM biaisée par contexte
        mock_llm.complete.return_value = "pro"

        # Appeler classify_email avec db_pool (va fetch contexte=medecin)
        result = await classify_email(
            email_text=sample_email_chu["body"],
            email_id=sample_email_chu["id"],
            metadata=sample_email_chu["metadata"],
            db_pool=mock_db_pool_medecin
        )

        # Assertions: Classification pro
        assert result.category == "pro"

        # Vérifier que le prompt contenait le context hint
        prompt_call = mock_llm.complete.call_args[1]["prompt"]
        assert "CONTEXTE ACTUEL" in prompt_call
        assert "casquette Médecin" in prompt_call or "médecin" in prompt_call.lower()
        assert "LÉGÈREMENT" in prompt_call


@pytest.mark.asyncio
async def test_email_chu_without_context_no_bias(
    sample_email_chu
):
    """
    Test AC1: Email @chu.fr SANS contexte → pas de bias

    Même email sans contexte casquette devrait rester objectif
    (pourrait classifier finance au lieu de pro).
    """
    # Mock LLM adapter
    with patch("agents.src.agents.email.classifier.get_llm_adapter") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_get_llm.return_value = mock_llm

        # Simuler réponse LLM objective (finance car facture)
        mock_llm.complete.return_value = "finance"

        # Appeler classify_email SANS db_pool (pas de contexte)
        result = await classify_email(
            email_text=sample_email_chu["body"],
            email_id=sample_email_chu["id"],
            metadata=sample_email_chu["metadata"],
            db_pool=None  # Pas de contexte
        )

        # Assertions: Classification finance (objectif)
        assert result.category == "finance"

        # Vérifier que le prompt NE contenait PAS de context hint
        prompt_call = mock_llm.complete.call_args[1]["prompt"]
        assert "CONTEXTE ACTUEL" not in prompt_call


# ============================================================================
# Tests Détection Événements avec Contexte (AC1)
# ============================================================================

@pytest.mark.asyncio
async def test_event_reunion_with_context_enseignant_biases_casquette(
    sample_email_reunion_ambigue,
    mock_db_pool_enseignant
):
    """
    Test AC1: Événement ambigu + contexte=enseignant → casquette=enseignant

    Événement "réunion équipe" ambigu avec contexte enseignant
    devrait favoriser casquette=enseignant plutôt que chercheur.
    """
    # Mock Anthropic client
    mock_client = AsyncMock()

    # Simuler réponse Claude biaisée par contexte
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"events_detected": [{"title": "Réunion équipe", "start_datetime": "2026-02-20T14:00:00", "end_datetime": "2026-02-20T15:00:00", "location": null, "participants": [], "event_type": "meeting", "casquette": "enseignant", "confidence": 0.85, "context": "Réunion équipe jeudi 14h"}], "confidence_overall": 0.85}'
        )
    ]
    mock_client.messages.create.return_value = mock_response

    # Mock anonymize_text
    with patch("agents.src.agents.calendar.event_detector.anonymize_text") as mock_anon:
        mock_anon.return_value = MagicMock(
            anonymized_text=sample_email_reunion_ambigue["body"],
            mapping={}
        )

        # Appeler extract_events_from_email avec db_pool
        result = await extract_events_from_email(
            email_text=sample_email_reunion_ambigue["body"],
            email_id=sample_email_reunion_ambigue["id"],
            metadata=sample_email_reunion_ambigue["metadata"],
            current_date="2026-02-15",
            anthropic_client=mock_client,
            db_pool=mock_db_pool_enseignant
        )

        # Assertions: Événement avec casquette=enseignant
        assert len(result.events_detected) == 1
        assert result.events_detected[0].casquette == Casquette.ENSEIGNANT

        # Vérifier que le prompt contenait le context hint
        prompt_call = mock_client.messages.create.call_args[1]["messages"][0]["content"]
        assert "CONTEXTE ACTUEL" in prompt_call
        assert "Enseignant" in prompt_call or "enseignant" in prompt_call.lower()


@pytest.mark.asyncio
async def test_event_reunion_without_context_no_bias(
    sample_email_reunion_ambigue
):
    """
    Test AC1: Événement ambigu SANS contexte → pas de bias

    Même événement sans contexte casquette devrait rester objectif
    (pourrait classifier chercheur au lieu d'enseignant).
    """
    # Mock Anthropic client
    mock_client = AsyncMock()

    # Simuler réponse Claude objective (chercheur car "projet")
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"events_detected": [{"title": "Réunion équipe", "start_datetime": "2026-02-20T14:00:00", "end_datetime": "2026-02-20T15:00:00", "location": null, "participants": [], "event_type": "meeting", "casquette": "chercheur", "confidence": 0.82, "context": "Réunion équipe projet"}], "confidence_overall": 0.82}'
        )
    ]
    mock_client.messages.create.return_value = mock_response

    # Mock anonymize_text
    with patch("agents.src.agents.calendar.event_detector.anonymize_text") as mock_anon:
        mock_anon.return_value = MagicMock(
            anonymized_text=sample_email_reunion_ambigue["body"],
            mapping={}
        )

        # Appeler extract_events_from_email SANS db_pool
        result = await extract_events_from_email(
            email_text=sample_email_reunion_ambigue["body"],
            email_id=sample_email_reunion_ambigue["id"],
            metadata=sample_email_reunion_ambigue["metadata"],
            current_date="2026-02-15",
            anthropic_client=mock_client,
            db_pool=None  # Pas de contexte
        )

        # Assertions: Événement avec casquette=chercheur (objectif)
        assert len(result.events_detected) == 1
        assert result.events_detected[0].casquette == Casquette.CHERCHEUR

        # Vérifier que le prompt NE contenait PAS de context hint
        prompt_call = mock_client.messages.create.call_args[1]["messages"][0]["content"]
        assert "CONTEXTE ACTUEL" not in prompt_call


# ============================================================================
# Tests Contexte Manuel Override (AC1)
# ============================================================================

@pytest.mark.asyncio
async def test_email_with_explicit_casquette_overrides_db(
    sample_email_chu,
    mock_db_pool_medecin
):
    """
    Test AC1: Contexte manuel explicite override DB

    Si current_casquette passé explicitement, ne doit PAS fetch depuis DB.
    """
    # Mock LLM adapter
    with patch("agents.src.agents.email.classifier.get_llm_adapter") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_get_llm.return_value = mock_llm
        mock_llm.complete.return_value = "recherche"

        # Appeler classify_email avec current_casquette=chercheur explicite
        # (même si DB a medecin)
        result = await classify_email(
            email_text=sample_email_chu["body"],
            email_id=sample_email_chu["id"],
            metadata=sample_email_chu["metadata"],
            db_pool=mock_db_pool_medecin,
            current_casquette=Casquette.CHERCHEUR  # Override explicite
        )

        # Assertions: DB NE DOIT PAS avoir été appelée
        conn = mock_db_pool_medecin.acquire.return_value.__aenter__.return_value
        conn.fetchrow.assert_not_called()

        # Vérifier que le prompt contenait contexte chercheur (pas medecin)
        prompt_call = mock_llm.complete.call_args[1]["prompt"]
        assert "CONTEXTE ACTUEL" in prompt_call
        assert "Chercheur" in prompt_call or "chercheur" in prompt_call.lower()


@pytest.mark.asyncio
async def test_event_with_explicit_casquette_overrides_db(
    sample_email_reunion_ambigue,
    mock_db_pool_enseignant
):
    """
    Test AC1: Contexte manuel explicite override DB (événements)

    Si current_casquette passé explicitement, ne doit PAS fetch depuis DB.
    """
    # Mock Anthropic client
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"events_detected": [{"title": "Réunion labo", "start_datetime": "2026-02-20T14:00:00", "end_datetime": "2026-02-20T15:00:00", "location": null, "participants": [], "event_type": "meeting", "casquette": "chercheur", "confidence": 0.88, "context": "Réunion équipe"}], "confidence_overall": 0.88}'
        )
    ]
    mock_client.messages.create.return_value = mock_response

    # Mock anonymize_text
    with patch("agents.src.agents.calendar.event_detector.anonymize_text") as mock_anon:
        mock_anon.return_value = MagicMock(
            anonymized_text=sample_email_reunion_ambigue["body"],
            mapping={}
        )

        # Appeler avec current_casquette=chercheur explicite (DB a enseignant)
        result = await extract_events_from_email(
            email_text=sample_email_reunion_ambigue["body"],
            email_id=sample_email_reunion_ambigue["id"],
            metadata=sample_email_reunion_ambigue["metadata"],
            current_date="2026-02-15",
            anthropic_client=mock_client,
            db_pool=mock_db_pool_enseignant,
            current_casquette=Casquette.CHERCHEUR  # Override explicite
        )

        # Assertions: DB NE DOIT PAS avoir été appelée
        conn = mock_db_pool_enseignant.acquire.return_value.__aenter__.return_value
        conn.fetchrow.assert_not_called()

        # Vérifier que le prompt contenait contexte chercheur (pas enseignant)
        prompt_call = mock_client.messages.create.call_args[1]["messages"][0]["content"]
        assert "CONTEXTE ACTUEL" in prompt_call
        assert "Chercheur" in prompt_call or "chercheur" in prompt_call.lower()
