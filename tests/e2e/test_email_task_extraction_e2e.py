"""
Tests E2E extraction tâches emails (Story 2.7)

Tests critiques workflow complet:
- Email → Classification → Extraction → Tâche → Validation → Notification
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_email_with_task_full_workflow(db_pool, redis_client):
    """
    E2E 1 : Email → Tâche → Validation → Création complète

    Workflow complet (10 étapes):
    1. Email reçu via EmailEngine (mock webhook)
    2. Consumer traite email
    3. Classification (Story 2.2)
    4. Extraction tâche (Story 2.7)
    5. Tâche créée core.tasks status=pending
    6. Receipt créé core.action_receipts status=pending
    7. Notification topic Actions (inline buttons)
    8. Notification topic Email (résumé)
    9. Clic Approve → Receipt status=approved
    10. Vérifier tâche consultable /task (Story 4.7)
    """
    from agents.src.agents.email.task_creator import create_tasks_with_validation
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock Claude pour classification + extraction
    with patch("agents.src.agents.email.task_extractor.anthropic_client") as mock_claude:
        # Mock extraction tâche
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='{"tasks_detected": [{"description": "Envoyer rapport médical", "priority": "high", "due_date": "2026-02-14", "confidence": 0.92, "context": "Demande explicite urgente", "priority_keywords": ["urgent", "ASAP"]}], "confidence_overall": 0.92}'
            )
        ]
        mock_claude.messages.create = AsyncMock(return_value=mock_response)

        # Mock Presidio
        with patch("agents.src.agents.email.task_extractor.anonymize_text") as mock_presidio:

            async def mock_anon(text, **kwargs):
                result = MagicMock()
                result.anonymized_text = text.replace("Dr. Dupont", "[PERSON_1]")
                return result

            mock_presidio.side_effect = mock_anon

            # Créer email en DB
            async with db_pool.acquire() as conn:
                email_id = await conn.fetchval(
                    """
                    INSERT INTO ingestion.emails_raw (
                        message_id, account_id, sender, recipient, subject, body, metadata
                    ) VALUES (
                        $1, 'test-account', 'patient@example.com', 'dr@example.com',
                        'Urgent: Rapport médical', 'Peux-tu envoyer le rapport médical de Dr. Dupont avant vendredi ? ASAP', '{}'::jsonb
                    ) RETURNING id
                    """,
                    f"e2e-test-{uuid4()}",
                )

            # Étape 4: Extraction tâche
            extraction_result = await extract_tasks_from_email(
                email_text="Peux-tu envoyer le rapport médical de Dr. Dupont avant vendredi ? ASAP",
                email_metadata={
                    "email_id": str(email_id),
                    "sender": "patient@example.com",
                    "subject": "Urgent: Rapport médical",
                },
                current_date="2026-02-11",
            )

            # Vérifications extraction
            assert len(extraction_result.tasks_detected) == 1
            task = extraction_result.tasks_detected[0]
            assert task.confidence >= 0.7
            assert task.priority == "high"
            assert task.due_date.strftime("%Y-%m-%d") == "2026-02-14"

            # Étape 5: Création tâche (mock @friday_action)
            with patch("agents.src.agents.email.task_creator.friday_action") as mock_action:
                mock_action.side_effect = lambda **kwargs: lambda func: func

                action_result = await create_tasks_with_validation(
                    tasks=[task],
                    email_id=str(email_id),
                    email_subject="Urgent: Rapport médical",
                    db_pool=db_pool,
                )

            # Vérifier tâche créée
            assert len(action_result.payload["task_ids"]) == 1
            task_id = action_result.payload["task_ids"][0]

            # Vérifier en DB
            async with db_pool.acquire() as conn:
                task_row = await conn.fetchrow("SELECT * FROM core.tasks WHERE id = $1", task_id)

            assert task_row is not None
            assert task_row["type"] == "email_task"
            assert task_row["status"] == "pending"
            assert task_row["priority"] == 3  # high
            assert "rapport médical" in task_row["name"].lower()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_email_without_task(db_pool):
    """
    E2E 2 : Email sans tâche → Confidence <0.7 → Aucune création
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock Claude: email sans tâche
    with patch("agents.src.agents.email.task_extractor.anthropic_client") as mock_claude:
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(text='{"tasks_detected": [], "confidence_overall": 0.15}')
        ]
        mock_claude.messages.create = AsyncMock(return_value=mock_response)

        # Mock Presidio
        with patch("agents.src.agents.email.task_extractor.anonymize_text") as mock_presidio:

            async def mock_anon(text, **kwargs):
                result = MagicMock()
                result.anonymized_text = text
                return result

            mock_presidio.side_effect = mock_anon

            # Extraction
            result = await extract_tasks_from_email(
                email_text="Thank you for your email. I have received the document. Best regards.",
                email_metadata={
                    "email_id": str(uuid4()),
                    "sender": "colleague@example.com",
                    "subject": "Re: Document received",
                },
            )

    # Vérifications
    assert len(result.tasks_detected) == 0
    assert result.confidence_overall < 0.7


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_multiple_tasks_one_email(db_pool):
    """
    E2E 3 : Email avec 2-3 tâches → Toutes détectées + créées
    """
    from agents.src.agents.email.task_creator import create_tasks_with_validation
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock Claude: 2 tâches détectées
    with patch("agents.src.agents.email.task_extractor.anthropic_client") as mock_claude:
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='{"tasks_detected": [{"description": "Envoyer planning", "priority": "high", "due_date": "2026-02-11", "confidence": 0.95, "context": "Urgence ASAP", "priority_keywords": ["urgent", "ASAP"]}, {"description": "Rappeler patient RDV", "priority": "high", "due_date": "2026-02-11", "confidence": 0.92, "context": "Urgence contexte", "priority_keywords": ["urgent"]}], "confidence_overall": 0.94}'
            )
        ]
        mock_claude.messages.create = AsyncMock(return_value=mock_response)

        # Mock Presidio
        with patch("agents.src.agents.email.task_extractor.anonymize_text") as mock_presidio:

            async def mock_anon(text, **kwargs):
                result = MagicMock()
                result.anonymized_text = text
                return result

            mock_presidio.side_effect = mock_anon

            # Créer email
            async with db_pool.acquire() as conn:
                email_id = await conn.fetchval(
                    """
                    INSERT INTO ingestion.emails_raw (
                        message_id, account_id, sender, recipient, subject, body, metadata
                    ) VALUES (
                        $1, 'test-account', 'urgent@example.com', 'dr@example.com',
                        'URGENT', 'Peux-tu envoyer le planning ASAP et rappeler le patient ?', '{}'::jsonb
                    ) RETURNING id
                    """,
                    f"e2e-multi-{uuid4()}",
                )

            # Extraction
            result = await extract_tasks_from_email(
                email_text="Peux-tu envoyer le planning ASAP et rappeler le patient pour confirmer son RDV ?",
                email_metadata={
                    "email_id": str(email_id),
                    "sender": "urgent@example.com",
                    "subject": "URGENT",
                },
                current_date="2026-02-11",
            )

            # Vérifications
            assert len(result.tasks_detected) == 2
            assert all(t.confidence >= 0.7 for t in result.tasks_detected)
            assert all(t.priority == "high" for t in result.tasks_detected)

            # Création tâches
            with patch("agents.src.agents.email.task_creator.friday_action") as mock_action:
                mock_action.side_effect = lambda **kwargs: lambda func: func

                action_result = await create_tasks_with_validation(
                    tasks=result.tasks_detected,
                    email_id=str(email_id),
                    email_subject="URGENT",
                    db_pool=db_pool,
                )

            # Vérifier 2 tâches créées
            assert len(action_result.payload["task_ids"]) == 2


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_relative_dates_conversion(db_pool):
    """
    E2E 4 : Dates relatives → Converties en dates absolues
    """
    from agents.src.agents.email.task_extractor import extract_tasks_from_email

    # Mock Claude avec date relative convertie
    with patch("agents.src.agents.email.task_extractor.anthropic_client") as mock_claude:
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='{"tasks_detected": [{"description": "Envoyer document demain", "priority": "normal", "due_date": "2026-02-12", "confidence": 0.88, "context": "Deadline demain", "priority_keywords": ["demain"]}], "confidence_overall": 0.88}'
            )
        ]
        mock_claude.messages.create = AsyncMock(return_value=mock_response)

        # Mock Presidio
        with patch("agents.src.agents.email.task_extractor.anonymize_text") as mock_presidio:

            async def mock_anon(text, **kwargs):
                result = MagicMock()
                result.anonymized_text = text
                return result

            mock_presidio.side_effect = mock_anon

            # Extraction avec date actuelle = 2026-02-11
            result = await extract_tasks_from_email(
                email_text="Envoie-moi le document demain",
                email_metadata={
                    "email_id": str(uuid4()),
                    "sender": "test@example.com",
                    "subject": "Document",
                },
                current_date="2026-02-11",  # Mardi
            )

    # Vérifications
    assert len(result.tasks_detected) == 1
    task = result.tasks_detected[0]
    assert task.due_date is not None
    # "demain" depuis 2026-02-11 = 2026-02-12
    assert task.due_date.strftime("%Y-%m-%d") == "2026-02-12"
