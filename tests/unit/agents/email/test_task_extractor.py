"""
Tests unitaires pour l'extraction de tâches depuis emails (Story 2.7)

AC1 : Détection automatique tâches implicites
AC6 : Extraction dates relatives
AC7 : Priorisation automatique depuis mots-clés
AC5 : Gestion emails sans tâche
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.src.agents.email.models import TaskDetected, TaskExtractionResult


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_anthropic_client():
    """Mock du client Anthropic pour éviter appels API réels"""
    with patch("agents.src.agents.email.task_extractor.anthropic_client") as mock:
        yield mock


@pytest.fixture
def mock_presidio():
    """Mock de Presidio pour anonymisation"""
    with patch("agents.src.agents.email.task_extractor.anonymize_text") as mock:
        # Par défaut, retourne un AnonymizationResult mock avec texte non anonymisé
        async def mock_anonymize(text, **kwargs):
            from unittest.mock import MagicMock
            result = MagicMock()
            result.anonymized_text = text  # Retourner texte tel quel en tests
            return result
        mock.side_effect = mock_anonymize
        yield mock


@pytest.fixture
def current_date_str():
    """Date actuelle pour tests (fixe)"""
    return "2026-02-11"


@pytest.fixture
def current_day_str():
    """Jour de la semaine actuel (fixe)"""
    return "Mardi"


# =============================================================================
# TESTS AC1 : DÉTECTION TÂCHES EXPLICITES (5 tests)
# =============================================================================


@pytest.mark.asyncio
async def test_extract_explicit_task_simple_request(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC1 : Demande explicite simple → 1 tâche détectée
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Envoyer le rapport", "priority": "normal", "due_date": "2026-02-13", "confidence": 0.95, "context": "Demande explicite", "priority_keywords": []}], "confidence_overall": 0.95}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Peux-tu m'envoyer le rapport avant jeudi ?",
        email_metadata={"email_id": "test-123", "sender": "test@example.com", "subject": "Rapport"},
        current_date=current_date_str,
    )

    # Assertions
    assert isinstance(result, TaskExtractionResult)
    assert len(result.tasks_detected) == 1
    assert result.tasks_detected[0].description == "Envoyer le rapport"
    assert result.tasks_detected[0].priority == "normal"
    assert result.tasks_detected[0].confidence >= 0.7
    assert result.confidence_overall >= 0.7


@pytest.mark.asyncio
async def test_extract_explicit_task_with_person_name(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC1 : Demande explicite avec nom de personne → Tâche avec description claire
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Rappeler Jean Dupont", "priority": "high", "due_date": null, "confidence": 0.92, "context": "Demande explicite de rappel", "priority_keywords": ["urgent"]}], "confidence_overall": 0.92}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Urgent : rappelle Jean Dupont dès que possible",
        email_metadata={"email_id": "test-456", "sender": "test@example.com", "subject": "Rappel"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 1
    assert "Rappeler" in result.tasks_detected[0].description
    assert result.tasks_detected[0].priority == "high"


@pytest.mark.asyncio
async def test_extract_explicit_task_confirm_action(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC1 : Demande de confirmation → 1 tâche détectée
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Confirmer participation au séminaire", "priority": "normal", "due_date": "2026-02-15", "confidence": 0.88, "context": "Demande de confirmation explicite", "priority_keywords": []}], "confidence_overall": 0.88}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Merci de me confirmer ta participation au séminaire du 15 février",
        email_metadata={"email_id": "test-789", "sender": "test@example.com", "subject": "Séminaire"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 1
    assert "Confirmer" in result.tasks_detected[0].description


@pytest.mark.asyncio
async def test_extract_implicit_task_self_commitment(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC1 : Engagement implicite (auto-tâche) → 1 tâche détectée
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Recontacter pour le dossier", "priority": "normal", "due_date": "2026-02-12", "confidence": 0.80, "context": "Engagement implicite - auto-tâche", "priority_keywords": ["demain"]}], "confidence_overall": 0.80}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Je te recontacte demain pour le dossier",
        email_metadata={"email_id": "test-abc", "sender": "test@example.com", "subject": "Dossier"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 1
    assert result.tasks_detected[0].confidence >= 0.7


@pytest.mark.asyncio
async def test_extract_reminder_task(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC1 : Rappel explicite → 1 tâche détectée
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Valider la facture", "priority": "normal", "due_date": null, "confidence": 0.85, "context": "Rappel explicite", "priority_keywords": []}], "confidence_overall": 0.85}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="N'oublie pas de valider la facture",
        email_metadata={"email_id": "test-def", "sender": "test@example.com", "subject": "Facture"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 1
    assert "Valider" in result.tasks_detected[0].description


# =============================================================================
# TESTS AC6 : EXTRACTION DATES RELATIVES (5 tests)
# =============================================================================


@pytest.mark.asyncio
async def test_extract_task_date_tomorrow(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC6 : Date relative 'demain' → Convertie en date absolue
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude avec date convertie
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Envoyer document", "priority": "normal", "due_date": "2026-02-12", "confidence": 0.90, "context": "Demande avec date demain", "priority_keywords": ["demain"]}], "confidence_overall": 0.90}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Envoie-moi ça demain",
        email_metadata={"email_id": "test-date-1", "sender": "test@example.com", "subject": "Document"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 1
    task = result.tasks_detected[0]
    assert task.due_date is not None
    assert task.due_date.strftime("%Y-%m-%d") == "2026-02-12"  # Demain depuis 2026-02-11


@pytest.mark.asyncio
async def test_extract_task_date_next_thursday(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC6 : Date relative 'jeudi prochain' → Convertie en date absolue
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "RDV jeudi prochain", "priority": "normal", "due_date": "2026-02-13", "confidence": 0.88, "context": "RDV avec date jeudi", "priority_keywords": []}], "confidence_overall": 0.88}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="RDV jeudi prochain",
        email_metadata={"email_id": "test-date-2", "sender": "test@example.com", "subject": "RDV"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 1
    assert result.tasks_detected[0].due_date.strftime("%Y-%m-%d") == "2026-02-13"


@pytest.mark.asyncio
async def test_extract_task_date_in_3_days(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC6 : Date relative 'dans 3 jours' → Convertie en date absolue
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Finaliser dossier", "priority": "normal", "due_date": "2026-02-14", "confidence": 0.85, "context": "Deadline dans 3 jours", "priority_keywords": []}], "confidence_overall": 0.85}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Finaliser le dossier dans 3 jours",
        email_metadata={"email_id": "test-date-3", "sender": "test@example.com", "subject": "Dossier"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 1
    assert result.tasks_detected[0].due_date.strftime("%Y-%m-%d") == "2026-02-14"


@pytest.mark.asyncio
async def test_extract_task_date_before_friday(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC6 : Date relative 'avant vendredi' → Convertie en deadline vendredi
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Valider facture", "priority": "high", "due_date": "2026-02-14", "confidence": 0.92, "context": "Deadline avant vendredi", "priority_keywords": ["avant vendredi"]}], "confidence_overall": 0.92}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Valider la facture avant vendredi",
        email_metadata={"email_id": "test-date-4", "sender": "test@example.com", "subject": "Facture"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 1
    assert result.tasks_detected[0].due_date.strftime("%Y-%m-%d") == "2026-02-14"


@pytest.mark.asyncio
async def test_extract_task_date_next_week(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC6 : Date relative 'la semaine prochaine' → Convertie en lundi suivant
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Préparer présentation", "priority": "normal", "due_date": "2026-02-17", "confidence": 0.80, "context": "Deadline semaine prochaine", "priority_keywords": []}], "confidence_overall": 0.80}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Préparer la présentation pour la semaine prochaine",
        email_metadata={"email_id": "test-date-5", "sender": "test@example.com", "subject": "Présentation"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 1
    # Lundi de la semaine prochaine depuis 2026-02-11 (mardi) = 2026-02-17
    assert result.tasks_detected[0].due_date.strftime("%Y-%m-%d") == "2026-02-17"


# =============================================================================
# TESTS AC7 : PRIORISATION AUTOMATIQUE (3 tests)
# =============================================================================


@pytest.mark.asyncio
async def test_extract_task_priority_high_urgent(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC7 : Mots-clés urgents → Priorité HIGH
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Envoyer dossier", "priority": "high", "due_date": "2026-02-11", "confidence": 0.95, "context": "Demande urgente ASAP", "priority_keywords": ["urgent", "ASAP"]}], "confidence_overall": 0.95}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="URGENT : Envoie le dossier ASAP",
        email_metadata={"email_id": "test-priority-1", "sender": "test@example.com", "subject": "Urgent"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 1
    task = result.tasks_detected[0]
    assert task.priority == "high"
    assert task.priority_keywords is not None
    assert any(keyword in ["urgent", "ASAP", "asap"] for keyword in task.priority_keywords)


@pytest.mark.asyncio
async def test_extract_task_priority_normal_default(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC7 : Pas d'indicateur urgence → Priorité NORMAL (défaut)
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Envoyer rapport", "priority": "normal", "due_date": null, "confidence": 0.85, "context": "Demande simple sans urgence", "priority_keywords": []}], "confidence_overall": 0.85}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Peux-tu m'envoyer le rapport ?",
        email_metadata={"email_id": "test-priority-2", "sender": "test@example.com", "subject": "Rapport"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 1
    assert result.tasks_detected[0].priority == "normal"


@pytest.mark.asyncio
async def test_extract_task_priority_low_when_convenient(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC7 : Mots-clés 'pas urgent' → Priorité LOW
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Regarder document", "priority": "low", "due_date": null, "confidence": 0.75, "context": "Tâche non urgente", "priority_keywords": ["quand tu peux"]}], "confidence_overall": 0.75}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Quand tu peux, regarde ce document",
        email_metadata={"email_id": "test-priority-3", "sender": "test@example.com", "subject": "Document"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 1
    assert result.tasks_detected[0].priority == "low"


# =============================================================================
# TESTS AC5 : EMAILS SANS TÂCHE (2 tests)
# =============================================================================


@pytest.mark.asyncio
async def test_extract_no_task_newsletter(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC5 : Newsletter → Aucune tâche détectée
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [], "confidence_overall": 0.12}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Newsletter hebdomadaire : Actualités médicales...",
        email_metadata={"email_id": "test-notask-1", "sender": "newsletter@example.com", "subject": "Newsletter"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 0
    assert result.confidence_overall < 0.7  # Confidence faible


@pytest.mark.asyncio
async def test_extract_no_task_simple_thank_you(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    AC5 : Email de remerciement simple → Aucune tâche détectée
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [], "confidence_overall": 0.08}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Merci pour ton message, j'ai bien reçu le document. Bonne journée !",
        email_metadata={"email_id": "test-notask-2", "sender": "test@example.com", "subject": "Merci"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 0
    assert result.confidence_overall < 0.3


# =============================================================================
# TESTS EDGE CASES
# =============================================================================


@pytest.mark.asyncio
async def test_extract_multiple_tasks_single_email(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    Edge case : Email avec 2 tâches → 2 tâches détectées
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude avec 2 tâches
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [{"description": "Envoyer planning", "priority": "high", "due_date": "2026-02-11", "confidence": 0.95, "context": "Demande urgente", "priority_keywords": ["urgent", "ASAP"]}, {"description": "Rappeler patient", "priority": "high", "due_date": "2026-02-11", "confidence": 0.92, "context": "Demande urgente contexte", "priority_keywords": ["urgent"]}], "confidence_overall": 0.94}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    result = await extract_tasks_from_email(
        email_text="Urgent : peux-tu m'envoyer le planning ASAP et rappeler le patient ?",
        email_metadata={"email_id": "test-multi-1", "sender": "test@example.com", "subject": "Urgent"},
        current_date=current_date_str,
    )

    # Assertions
    assert len(result.tasks_detected) == 2
    assert all(task.confidence >= 0.7 for task in result.tasks_detected)
    assert result.confidence_overall >= 0.7


@pytest.mark.asyncio
async def test_presidio_anonymization_called(
    mock_anthropic_client, mock_presidio, current_date_str
):
    """
    RGPD : Presidio DOIT être appelé avant appel Claude
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock réponse Claude
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"tasks_detected": [], "confidence_overall": 0.5}'
        )
    ]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    # Test
    email_text = "Rappelle Jean Dupont au 06.12.34.56.78"
    await extract_tasks_from_email(
        email_text=email_text,
        email_metadata={"email_id": "test-rgpd-1", "sender": "test@example.com", "subject": "Rappel"},
        current_date=current_date_str,
    )

    # Assertions
    mock_presidio.assert_called_once_with(email_text, language="fr")
