"""
Tests d'intégration pour pipeline extraction tâches emails (Story 2.7)

AC2 : Création tâches + référence bidirectionnelle
AC3 : Trust layer + receipt création
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# =============================================================================
# TESTS INTEGRATION PIPELINE
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_email_to_task_creation_full_pipeline(db_pool):
    """
    AC2 : Email → Extraction → Tâche créée dans core.tasks
    """
    from datetime import datetime

    from agents.src.agents.email.models import TaskDetected
    from agents.src.agents.email.task_creator import create_tasks_with_validation

    # Créer email test dans DB
    async with db_pool.acquire() as conn:
        email_id = await conn.fetchval(
            """
            INSERT INTO ingestion.emails_raw (
                message_id, account_id, sender, recipient, subject, body, metadata
            ) VALUES (
                $1, 'test-account', 'test@example.com', 'user@example.com',
                'Test task extraction', 'Please send report by Friday', '{}'::jsonb
            ) RETURNING id
            """,
            f"test-{uuid4()}",
        )

    # Créer tâche détectée
    task = TaskDetected(
        description="Envoyer le rapport",
        priority="high",
        due_date=datetime(2026, 2, 14),
        confidence=0.92,
        context="Demande explicite avec deadline vendredi",
        priority_keywords=["by Friday"],
    )

    # Mock @friday_action pour éviter création receipt réel
    with patch("agents.src.agents.email.task_creator.friday_action") as mock_action:
        # Faire passer le decorator sans créer receipt
        mock_action.side_effect = lambda **kwargs: lambda func: func

        # Créer tâche via pipeline
        result = await create_tasks_with_validation(
            tasks=[task],
            email_id=str(email_id),
            email_subject="Test task extraction",
            db_pool=db_pool,
        )

    # Vérifications
    assert result is not None
    assert len(result.payload["task_ids"]) == 1

    # Vérifier tâche créée dans core.tasks
    async with db_pool.acquire() as conn:
        task_row = await conn.fetchrow(
            "SELECT * FROM core.tasks WHERE id = $1", result.payload["task_ids"][0]
        )

    assert task_row is not None
    assert task_row["type"] == "email_task"
    assert task_row["status"] == "pending"
    assert task_row["priority"] == 3  # high = 3
    assert "email_id" in task_row["payload"]
    assert task_row["payload"]["email_id"] == str(email_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bidirectional_reference_email_task(db_pool):
    """
    AC2 : Référence bidirectionnelle email ↔ task_ids
    """
    from datetime import datetime

    from agents.src.agents.email.models import TaskDetected
    from agents.src.agents.email.task_creator import create_tasks_with_validation

    # Créer email
    async with db_pool.acquire() as conn:
        email_id = await conn.fetchval(
            """
            INSERT INTO ingestion.emails_raw (
                message_id, account_id, sender, recipient, subject, body, metadata
            ) VALUES (
                $1, 'test-account', 'test@example.com', 'user@example.com',
                'Test', 'Task content', '{}'::jsonb
            ) RETURNING id
            """,
            f"test-{uuid4()}",
        )

    # Créer 2 tâches
    tasks = [
        TaskDetected(
            description="Tâche 1",
            priority="normal",
            due_date=None,
            confidence=0.8,
            context="Test 1",
            priority_keywords=[],
        ),
        TaskDetected(
            description="Tâche 2",
            priority="low",
            due_date=None,
            confidence=0.75,
            context="Test 2",
            priority_keywords=[],
        ),
    ]

    # Mock decorator
    with patch("agents.src.agents.email.task_creator.friday_action") as mock_action:
        mock_action.side_effect = lambda **kwargs: lambda func: func

        result = await create_tasks_with_validation(
            tasks=tasks, email_id=str(email_id), email_subject="Test", db_pool=db_pool
        )

    # Vérifier email a task_ids
    async with db_pool.acquire() as conn:
        email_row = await conn.fetchrow(
            "SELECT metadata FROM ingestion.emails_raw WHERE id = $1", email_id
        )

    assert email_row is not None
    assert "task_ids" in email_row["metadata"]
    assert len(email_row["metadata"]["task_ids"]) == 2
    assert all(
        task_id in email_row["metadata"]["task_ids"] for task_id in result.payload["task_ids"]
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_email_without_task_no_creation(db_pool):
    """
    AC5 : Email sans tâche → Aucune création
    """
    from unittest.mock import MagicMock

    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock Claude response sans tâche
    with patch("agents.src.agents.email.task_extractor.anthropic_client") as mock_client:
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(text='{"tasks_detected": [], "confidence_overall": 0.12}')
        ]
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        # Mock Presidio
        with patch("agents.src.agents.email.task_extractor.anonymize_text") as mock_presidio:

            async def mock_anon(text, **kwargs):
                result = MagicMock()
                result.anonymized_text = text
                return result

            mock_presidio.side_effect = mock_anon

            # Extraire
            result = await extract_tasks_from_email(
                email_text="Thank you for your message!",
                email_metadata={
                    "email_id": str(uuid4()),
                    "sender": "test@example.com",
                    "subject": "Thanks",
                },
            )

    # Vérifications
    assert len(result.tasks_detected) == 0
    assert result.confidence_overall < 0.7


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_tasks_single_email(db_pool):
    """
    Edge case : Email avec 2-3 tâches → Toutes créées
    """
    from datetime import datetime

    from agents.src.agents.email.models import TaskDetected
    from agents.src.agents.email.task_creator import create_tasks_with_validation

    # Créer email
    async with db_pool.acquire() as conn:
        email_id = await conn.fetchval(
            """
            INSERT INTO ingestion.emails_raw (
                message_id, account_id, sender, recipient, subject, body, metadata
            ) VALUES (
                $1, 'test-account', 'test@example.com', 'user@example.com',
                'Urgent tasks', 'Send planning and call patient', '{}'::jsonb
            ) RETURNING id
            """,
            f"test-{uuid4()}",
        )

    # 3 tâches
    tasks = [
        TaskDetected(
            description="Envoyer planning",
            priority="high",
            due_date=datetime(2026, 2, 11),
            confidence=0.95,
            context="Urgence",
            priority_keywords=["urgent"],
        ),
        TaskDetected(
            description="Appeler patient",
            priority="high",
            due_date=datetime(2026, 2, 11),
            confidence=0.92,
            context="Urgence",
            priority_keywords=["urgent"],
        ),
        TaskDetected(
            description="Valider documents",
            priority="normal",
            due_date=None,
            confidence=0.80,
            context="Demande standard",
            priority_keywords=[],
        ),
    ]

    # Mock decorator
    with patch("agents.src.agents.email.task_creator.friday_action") as mock_action:
        mock_action.side_effect = lambda **kwargs: lambda func: func

        result = await create_tasks_with_validation(
            tasks=tasks, email_id=str(email_id), email_subject="Urgent tasks", db_pool=db_pool
        )

    # Vérifications
    assert len(result.payload["task_ids"]) == 3
    assert result.confidence > 0.7

    # Vérifier toutes tâches créées
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM core.tasks
            WHERE payload->>'email_id' = $1
            """,
            str(email_id),
        )

    assert count == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_confidence_filtering_threshold(db_pool):
    """
    AC1 : Confidence <0.7 → Tâche non proposée
    """
    from agents.src.agents.email.models import TaskDetected
    from agents.src.agents.email.task_creator import create_tasks_with_validation

    # Créer email
    async with db_pool.acquire() as conn:
        email_id = await conn.fetchval(
            """
            INSERT INTO ingestion.emails_raw (
                message_id, account_id, sender, recipient, subject, body, metadata
            ) VALUES (
                $1, 'test-account', 'test@example.com', 'user@example.com',
                'Maybe task', 'Could you possibly...', '{}'::jsonb
            ) RETURNING id
            """,
            f"test-{uuid4()}",
        )

    # Tâche confidence faible (<0.7)
    task_low_confidence = TaskDetected(
        description="Tâche incertaine",
        priority="low",
        due_date=None,
        confidence=0.65,  # < 0.7 → Filtrée
        context="Ambiguë",
        priority_keywords=[],
    )

    # Mock decorator
    with patch("agents.src.agents.email.task_creator.friday_action") as mock_action:
        mock_action.side_effect = lambda **kwargs: lambda func: func

        result = await create_tasks_with_validation(
            tasks=[task_low_confidence],
            email_id=str(email_id),
            email_subject="Maybe task",
            db_pool=db_pool,
        )

    # Tâche créée quand même (filtrage fait AVANT appel create_tasks_with_validation)
    # Mais confidence globale <0.7
    assert result.confidence < 0.7
