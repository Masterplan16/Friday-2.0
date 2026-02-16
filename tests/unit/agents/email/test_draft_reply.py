"""
Tests unitaires pour agents.email.draft_reply

Tests le module principal de génération de brouillons emails avec
few-shot learning et correction rules.

Story: 2.5 Brouillon Réponse Email
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from agents.src.agents.email.draft_reply import (
    _call_claude_with_retry,
    _fetch_correction_rules,
    draft_email_reply,
    load_writing_examples,
)
from agents.src.middleware.models import ActionResult
from agents.src.tools.anonymize import AnonymizationResult


def mock_anon_result(text: str) -> AnonymizationResult:
    """Helper pour créer AnonymizationResult mock"""
    return AnonymizationResult(
        anonymized_text=text, entities_found=[], mapping={}, confidence_min=1.0
    )


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg pool"""
    pool = AsyncMock(spec=asyncpg.Pool)
    pool.fetch = AsyncMock()
    pool.fetchrow = AsyncMock()
    pool.execute = AsyncMock()
    return pool


@pytest.fixture
def mock_email_data():
    """Email de test"""
    return {
        "id": "test-email-id-123",
        "from": "john.doe@example.com",
        "from_anon": "[NAME_1]@[DOMAIN_1]",
        "to": "antonio.lopez@example.com",
        "subject": "Question about appointment",
        "subject_anon": "Question about [MEDICAL_TERM_1]",
        "body": "Dear Dr. Lopez, I would like to know if I can reschedule my appointment for next week. Best regards, John Doe",
        "body_anon": "Dear Dr. [NAME_2], I would like to know if I can reschedule my [MEDICAL_TERM_2] for next week. Best regards, [NAME_1]",
        "category": "professional",
        "message_id": "<msg-id-123@example.com>",
        "sender_email": "john.doe@example.com",
        "recipient_email": "antonio.lopez@example.com",
    }


@pytest.fixture
def mock_writing_examples():
    """Exemples de style rédactionnel"""
    return [
        {
            "id": "ex-1",
            "subject": "Re: Request for information",
            "body": "Bonjour,\n\nVoici les informations demandées.\n\nBien cordialement,\nDr. Antonio Lopez",
            "email_type": "professional",
            "created_at": "2026-01-15T10:00:00Z",
        },
        {
            "id": "ex-2",
            "subject": "Re: Meeting confirmation",
            "body": "Bonjour,\n\nJe confirme notre rendez-vous.\n\nCordialement,\nDr. Antonio Lopez",
            "email_type": "professional",
            "created_at": "2026-01-20T14:00:00Z",
        },
        {
            "id": "ex-3",
            "subject": "Re: Question about treatment",
            "body": "Bonjour,\n\nVoici ma réponse à votre question.\n\nBien à vous,\nDr. Antonio Lopez",
            "email_type": "professional",
            "created_at": "2026-01-25T16:00:00Z",
        },
    ]


@pytest.fixture
def mock_correction_rules():
    """Règles de correction actives"""
    return [
        {
            "id": "rule-1",
            "module": "email",
            "scope": "draft_reply",
            "conditions": 'Remplacer "Bien à vous"',
            "output": 'Utiliser "Cordialement"',
            "priority": 1,
            "active": True,
        },
        {
            "id": "rule-2",
            "module": "email",
            "scope": "draft_reply",
            "conditions": "Toujours inclure signature complète",
            "output": "Dr. Antonio Lopez\nMédecin",
            "priority": 2,
            "active": True,
        },
    ]


# ============================================================================
# Tests load_writing_examples
# ============================================================================


@pytest.mark.asyncio
async def test_load_writing_examples_returns_list(mock_db_pool, mock_writing_examples):
    """
    Test: load_writing_examples retourne une liste d'exemples
    """
    mock_db_pool.fetch.return_value = mock_writing_examples

    result = await load_writing_examples(mock_db_pool, email_type="professional", limit=5)

    assert isinstance(result, list)
    assert len(result) == 3
    mock_db_pool.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_load_writing_examples_filters_by_email_type(mock_db_pool):
    """
    Test: load_writing_examples filtre par email_type
    """
    mock_db_pool.fetch.return_value = []

    await load_writing_examples(mock_db_pool, email_type="medical", limit=5)

    # Vérifier que le query contient le filtre email_type
    call_args = mock_db_pool.fetch.call_args
    query = call_args[0][0]
    params = call_args[0][1:]

    assert "email_type" in query.lower()
    assert "medical" in params


@pytest.mark.asyncio
async def test_load_writing_examples_limits_results(mock_db_pool):
    """
    Test: load_writing_examples respecte la limite
    """
    mock_db_pool.fetch.return_value = []

    await load_writing_examples(mock_db_pool, email_type="professional", limit=10)

    call_args = mock_db_pool.fetch.call_args
    query = call_args[0][0]
    params = call_args[0][1:]

    assert "limit" in query.lower()
    assert 10 in params


# ============================================================================
# Tests draft_email_reply (fonction principale)
# ============================================================================
# NOTE: Les tests format_writing_examples_for_prompt ont été supprimés car
# la fonction était un duplicat (DRY violation) de _format_writing_examples()
# dans prompts_draft_reply.py. Tests de cette fonction dans test_prompts_draft_reply.py.


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.anonymize_text")
@patch("agents.src.agents.email.draft_reply.deanonymize_text")
@patch("agents.src.agents.email.draft_reply._call_claude_with_retry")
@patch("agents.src.agents.email.draft_reply._fetch_correction_rules")
@patch("agents.src.agents.email.draft_reply.load_writing_examples")
async def test_draft_email_reply_success_no_examples(
    mock_load_examples,
    mock_fetch_rules,
    mock_claude,
    mock_deanon,
    mock_anon,
    mock_db_pool,
    mock_email_data,
):
    """
    Test 1: Brouillon généré avec N=0 exemples (style générique)

    Vérifie que le workflow complet fonctionne sans exemples
    """
    # Setup mocks
    from agents.src.tools.anonymize import AnonymizationResult

    mock_anon.return_value = AnonymizationResult(
        anonymized_text=mock_email_data["body_anon"],
        entities_found=[],
        mapping={},
        confidence_min=1.0,
    )
    mock_load_examples.return_value = []  # Pas d'exemples Day 1
    mock_fetch_rules.return_value = []
    mock_claude.return_value = "Bonjour,\n\nOui, vous pouvez reprogrammer votre rendez-vous.\n\nCordialement,\nDr. Antonio Lopez"
    mock_deanon.return_value = "Bonjour,\n\nOui, vous pouvez reprogrammer votre rendez-vous.\n\nCordialement,\nDr. Antonio Lopez"

    # Execute
    result = await draft_email_reply(
        email_id=mock_email_data["id"], email_data=mock_email_data, db_pool=mock_db_pool
    )

    # Assertions
    assert isinstance(result, ActionResult)
    assert result.confidence > 0
    assert result.confidence <= 1.0
    assert "Email de" in result.input_summary
    assert "Brouillon réponse" in result.output_summary
    assert "draft_body" in result.payload

    # Vérifier que Presidio a été appelé (3x pour body + from + subject)
    assert mock_anon.call_count == 3
    assert mock_deanon.call_count == 1

    # Vérifier que Claude a été appelé
    mock_claude.assert_called_once()


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.anonymize_text")
@patch("agents.src.agents.email.draft_reply.deanonymize_text")
@patch("agents.src.agents.email.draft_reply._call_claude_with_retry")
@patch("agents.src.agents.email.draft_reply._fetch_correction_rules")
@patch("agents.src.agents.email.draft_reply.load_writing_examples")
async def test_draft_email_reply_with_few_shot_examples(
    mock_load_examples,
    mock_fetch_rules,
    mock_claude,
    mock_deanon,
    mock_anon,
    mock_db_pool,
    mock_email_data,
    mock_writing_examples,
):
    """
    Test 2: Brouillon généré avec N=3 exemples (few-shot)

    Vérifie que les exemples sont chargés et utilisés
    """
    # Setup mocks
    mock_anon.return_value = mock_anon_result(mock_email_data["body_anon"])
    mock_load_examples.return_value = mock_writing_examples[:3]
    mock_fetch_rules.return_value = []
    mock_claude.return_value = (
        "Bonjour,\n\nOui, reprogrammation possible.\n\nCordialement,\nDr. Antonio Lopez"
    )
    mock_deanon.return_value = (
        "Bonjour,\n\nOui, reprogrammation possible.\n\nCordialement,\nDr. Antonio Lopez"
    )

    # Execute
    result = await draft_email_reply(
        email_id=mock_email_data["id"], email_data=mock_email_data, db_pool=mock_db_pool
    )

    # Assertions
    assert isinstance(result, ActionResult)
    assert result.payload["style_examples_used"] == 3

    # Vérifier que load_writing_examples a été appelé avec les bons params
    mock_load_examples.assert_called_once()
    call_args = mock_load_examples.call_args
    assert call_args[1]["email_type"] == "professional"
    assert call_args[1]["limit"] <= 10  # Max 10 exemples


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.anonymize_text")
async def test_draft_email_reply_presidio_anonymization_applied(
    mock_anon, mock_db_pool, mock_email_data
):
    """
    Test 3: Anonymisation Presidio appliquée

    Vérifie que l'email est anonymisé AVANT appel Claude
    """
    mock_anon.return_value = mock_anon_result(mock_email_data["body_anon"])

    # On ne mock pas les autres fonctions pour tester que Presidio est appelé en premier
    with patch("agents.src.agents.email.draft_reply.load_writing_examples", return_value=[]):
        with patch("agents.src.agents.email.draft_reply._fetch_correction_rules", return_value=[]):
            with patch(
                "agents.src.agents.email.draft_reply._call_claude_with_retry",
                side_effect=Exception("Claude should not be called if Presidio fails"),
            ):
                with patch("agents.src.agents.email.draft_reply.deanonymize_text"):
                    # Execute - devrait échouer car Claude raise exception
                    try:
                        await draft_email_reply(
                            email_id=mock_email_data["id"],
                            email_data=mock_email_data,
                            db_pool=mock_db_pool,
                        )
                    except Exception:
                        pass

                    # Vérifier que Presidio anonymize a été appelé AVANT Claude
                    assert mock_anon.call_count >= 1
                    # Vérifier que le premier appel était avec le body
                    assert mock_anon.call_args_list[0][0][0] == mock_email_data["body"]


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.anonymize_text")
@patch("agents.src.agents.email.draft_reply.deanonymize_text")
@patch("agents.src.agents.email.draft_reply._call_claude_with_retry")
@patch("agents.src.agents.email.draft_reply._fetch_correction_rules")
@patch("agents.src.agents.email.draft_reply.load_writing_examples")
async def test_draft_email_reply_correction_rules_injected(
    mock_load_examples,
    mock_fetch_rules,
    mock_claude,
    mock_deanon,
    mock_anon,
    mock_db_pool,
    mock_email_data,
    mock_correction_rules,
):
    """
    Test 4: Correction rules injectées dans prompt

    Vérifie que les règles actives sont récupérées et utilisées
    """
    # Setup mocks
    mock_anon.return_value = mock_anon_result(mock_email_data["body_anon"])
    mock_load_examples.return_value = []
    mock_fetch_rules.return_value = mock_correction_rules
    mock_claude.return_value = "Brouillon test"
    mock_deanon.return_value = "Brouillon test"

    # Execute
    result = await draft_email_reply(
        email_id=mock_email_data["id"], email_data=mock_email_data, db_pool=mock_db_pool
    )

    # Assertions
    assert result.payload["correction_rules_used"] == 2

    # Vérifier que _fetch_correction_rules a été appelé
    # Vérifier que _fetch_correction_rules a été appelé
    assert mock_fetch_rules.call_count == 1
    # Vérifier les arguments (accepte args ou kwargs)
    call_kwargs = mock_fetch_rules.call_args.kwargs
    assert call_kwargs.get("module") == "email"
    assert call_kwargs.get("scope") == "draft_reply"


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.anonymize_text")
@patch("agents.src.agents.email.draft_reply.deanonymize_text")
@patch("agents.src.agents.email.draft_reply._call_claude_with_retry")
@patch("agents.src.agents.email.draft_reply._fetch_correction_rules")
@patch("agents.src.agents.email.draft_reply.load_writing_examples")
async def test_draft_email_reply_action_result_structure_valid(
    mock_load_examples,
    mock_fetch_rules,
    mock_claude,
    mock_deanon,
    mock_anon,
    mock_db_pool,
    mock_email_data,
):
    """
    Test 5: ActionResult structure valide

    Vérifie que ActionResult contient tous les champs requis
    """
    # Setup mocks
    mock_anon.return_value = mock_anon_result(mock_email_data["body_anon"])
    mock_load_examples.return_value = []
    mock_fetch_rules.return_value = []
    mock_claude.return_value = "Brouillon test complet"
    mock_deanon.return_value = "Brouillon test complet"

    # Execute
    result = await draft_email_reply(
        email_id=mock_email_data["id"], email_data=mock_email_data, db_pool=mock_db_pool
    )

    # Assertions - structure ActionResult
    assert hasattr(result, "input_summary")
    assert hasattr(result, "output_summary")
    assert hasattr(result, "confidence")
    assert hasattr(result, "reasoning")
    assert hasattr(result, "payload")
    assert hasattr(result, "steps")

    # Assertions - types
    assert isinstance(result.input_summary, str)
    assert isinstance(result.output_summary, str)
    assert isinstance(result.confidence, float)
    assert isinstance(result.reasoning, str)
    assert isinstance(result.payload, dict)
    assert isinstance(result.steps, list)

    # Assertions - payload required fields
    assert "email_type" in result.payload
    assert "style_examples_used" in result.payload
    assert "correction_rules_used" in result.payload
    assert "draft_body" in result.payload


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.anonymize_text")
@patch("agents.src.agents.email.draft_reply._call_claude_with_retry")
async def test_draft_email_reply_handles_claude_api_unavailable(
    mock_claude, mock_anon, mock_db_pool, mock_email_data
):
    """
    Test 6: Gestion erreur Claude API indisponible

    Vérifie que l'erreur est propagée correctement
    """
    # Setup mocks
    mock_anon.return_value = mock_anon_result(mock_email_data["body_anon"])
    mock_claude.side_effect = Exception("Claude API unavailable")

    # Execute - devrait raise exception
    with patch("agents.src.agents.email.draft_reply.load_writing_examples", return_value=[]):
        with patch("agents.src.agents.email.draft_reply._fetch_correction_rules", return_value=[]):
            with pytest.raises(Exception) as exc_info:
                await draft_email_reply(
                    email_id=mock_email_data["id"], email_data=mock_email_data, db_pool=mock_db_pool
                )

            assert "Claude API unavailable" in str(exc_info.value)


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.anonymize_text")
async def test_draft_email_reply_handles_presidio_fail_explicit(
    mock_anon, mock_db_pool, mock_email_data
):
    """
    Test 7: Gestion erreur Presidio indisponible (fail-explicit)

    Vérifie que NotImplementedError est raised si Presidio échoue
    """
    # Setup mocks
    mock_anon.side_effect = NotImplementedError("Presidio not available - RGPD fail-explicit")

    # Execute - devrait raise NotImplementedError
    with pytest.raises(NotImplementedError) as exc_info:
        await draft_email_reply(
            email_id=mock_email_data["id"], email_data=mock_email_data, db_pool=mock_db_pool
        )

    assert "Presidio" in str(exc_info.value)
    assert "RGPD" in str(exc_info.value) or "fail-explicit" in str(exc_info.value)


# ============================================================================
# Tests AC2: Few-shot learning confidence levels
# ============================================================================


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.anonymize_text")
@patch("agents.src.agents.email.draft_reply.deanonymize_text")
@patch("agents.src.agents.email.draft_reply._call_claude_with_retry")
@patch("agents.src.agents.email.draft_reply._fetch_correction_rules")
@patch("agents.src.agents.email.draft_reply.load_writing_examples")
async def test_draft_email_reply_confidence_high_with_examples(
    mock_load_examples,
    mock_fetch_rules,
    mock_claude,
    mock_deanon,
    mock_anon,
    mock_db_pool,
    mock_email_data,
    mock_writing_examples,
):
    """
    Test 8: Confidence 0.85 avec >= 3 exemples (AC2)

    Vérifie que confidence = 0.85 quand writing_examples >= 3
    """
    # Setup mocks
    mock_anon.return_value = mock_anon_result(mock_email_data["body_anon"])
    mock_load_examples.return_value = mock_writing_examples  # 3 exemples
    mock_fetch_rules.return_value = []
    mock_claude.return_value = "Brouillon test"
    mock_deanon.return_value = "Brouillon test"

    # Execute
    result = await draft_email_reply(
        email_id=mock_email_data["id"], email_data=mock_email_data, db_pool=mock_db_pool
    )

    # Assertions - confidence devrait être 0.85 car >= 3 exemples
    assert result.confidence == 0.85
    assert result.payload["style_examples_used"] >= 3


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.anonymize_text")
@patch("agents.src.agents.email.draft_reply.deanonymize_text")
@patch("agents.src.agents.email.draft_reply._call_claude_with_retry")
@patch("agents.src.agents.email.draft_reply._fetch_correction_rules")
@patch("agents.src.agents.email.draft_reply.load_writing_examples")
async def test_draft_email_reply_confidence_low_without_examples(
    mock_load_examples,
    mock_fetch_rules,
    mock_claude,
    mock_deanon,
    mock_anon,
    mock_db_pool,
    mock_email_data,
):
    """
    Test 9: Confidence 0.70 avec < 3 exemples (AC2)

    Vérifie que confidence = 0.70 quand writing_examples < 3
    """
    # Setup mocks
    mock_anon.return_value = mock_anon_result(mock_email_data["body_anon"])
    mock_load_examples.return_value = []  # 0 exemples
    mock_fetch_rules.return_value = []
    mock_claude.return_value = "Brouillon test"
    mock_deanon.return_value = "Brouillon test"

    # Execute
    result = await draft_email_reply(
        email_id=mock_email_data["id"], email_data=mock_email_data, db_pool=mock_db_pool
    )

    # Assertions - confidence devrait être 0.70 car 0 exemples
    assert result.confidence == 0.70
    assert result.payload["style_examples_used"] == 0


# ============================================================================
# Tests token estimation & payload
# ============================================================================


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.anonymize_text")
@patch("agents.src.agents.email.draft_reply.deanonymize_text")
@patch("agents.src.agents.email.draft_reply._call_claude_with_retry")
@patch("agents.src.agents.email.draft_reply._fetch_correction_rules")
@patch("agents.src.agents.email.draft_reply.load_writing_examples")
async def test_draft_email_reply_token_estimation_in_payload(
    mock_load_examples,
    mock_fetch_rules,
    mock_claude,
    mock_deanon,
    mock_anon,
    mock_db_pool,
    mock_email_data,
):
    """
    Test 10: Payload contient prompt_tokens et response_tokens estimés

    Vérifie que l'estimation des tokens est présente dans payload
    """
    # Setup mocks
    mock_anon.return_value = mock_anon_result(mock_email_data["body_anon"])
    mock_load_examples.return_value = []
    mock_fetch_rules.return_value = []
    mock_claude.return_value = "Bonjour,\n\nVoici ma réponse.\n\nCordialement,\nDr. Antonio Lopez"
    mock_deanon.return_value = "Bonjour,\n\nVoici ma réponse.\n\nCordialement,\nDr. Antonio Lopez"

    # Execute
    result = await draft_email_reply(
        email_id=mock_email_data["id"], email_data=mock_email_data, db_pool=mock_db_pool
    )

    # Assertions - payload contient tokens estimés
    assert "prompt_tokens" in result.payload
    assert "response_tokens" in result.payload
    assert isinstance(result.payload["prompt_tokens"], int)
    assert isinstance(result.payload["response_tokens"], int)
    assert result.payload["prompt_tokens"] > 0
    assert result.payload["response_tokens"] > 0


# ============================================================================
# Tests steps detail
# ============================================================================


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.anonymize_text")
@patch("agents.src.agents.email.draft_reply.deanonymize_text")
@patch("agents.src.agents.email.draft_reply._call_claude_with_retry")
@patch("agents.src.agents.email.draft_reply._fetch_correction_rules")
@patch("agents.src.agents.email.draft_reply.load_writing_examples")
async def test_draft_email_reply_steps_detail_complete(
    mock_load_examples,
    mock_fetch_rules,
    mock_claude,
    mock_deanon,
    mock_anon,
    mock_db_pool,
    mock_email_data,
):
    """
    Test 11: Steps detail contient les 7 étapes documentées

    Vérifie que ActionResult.steps contient toutes les étapes du workflow
    """
    # Setup mocks
    mock_anon.return_value = mock_anon_result(mock_email_data["body_anon"])
    mock_load_examples.return_value = []
    mock_fetch_rules.return_value = []
    mock_claude.return_value = "Brouillon complet"
    mock_deanon.return_value = "Brouillon complet"

    # Execute
    result = await draft_email_reply(
        email_id=mock_email_data["id"], email_data=mock_email_data, db_pool=mock_db_pool
    )

    # Assertions - steps contient 7 étapes
    assert len(result.steps) == 7

    # Vérifier noms des steps attendus
    expected_steps = [
        "Anonymize email source",
        "Load writing examples",
        "Load correction rules",
        "Build prompts",
        "Generate with Claude Sonnet 4.5",
        "Deanonymize draft",
        "Validate draft",
    ]

    actual_steps = [step.description for step in result.steps]
    assert actual_steps == expected_steps

    # Vérifier que chaque step a confidence et details
    for step in result.steps:
        assert hasattr(step, "confidence")
        assert hasattr(step, "description")
        assert 0 <= step.confidence <= 1.0
        assert len(step.description) > 0


# ============================================================================
# Tests error handling
# ============================================================================


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.anonymize_text")
@patch("agents.src.agents.email.draft_reply.deanonymize_text")
@patch("agents.src.agents.email.draft_reply._call_claude_with_retry")
@patch("agents.src.agents.email.draft_reply._fetch_correction_rules")
@patch("agents.src.agents.email.draft_reply.load_writing_examples")
async def test_draft_email_reply_empty_draft_raises_value_error(
    mock_load_examples,
    mock_fetch_rules,
    mock_claude,
    mock_deanon,
    mock_anon,
    mock_db_pool,
    mock_email_data,
):
    """
    Test 12: Brouillon vide raise ValueError

    Vérifie que ValueError est raised si brouillon généré est vide
    """
    # Setup mocks
    mock_anon.return_value = mock_anon_result(mock_email_data["body_anon"])
    mock_load_examples.return_value = []
    mock_fetch_rules.return_value = []
    mock_claude.return_value = ""  # Brouillon vide
    mock_deanon.return_value = ""

    # Execute - devrait raise ValueError
    with pytest.raises(ValueError) as exc_info:
        await draft_email_reply(
            email_id=mock_email_data["id"], email_data=mock_email_data, db_pool=mock_db_pool
        )

    assert "Brouillon vide" in str(exc_info.value) or "trop court" in str(exc_info.value)


# ============================================================================
# Tests retry logic _call_claude_with_retry
# ============================================================================


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.get_llm_adapter")
async def test_call_claude_with_retry_success_first_attempt(mock_get_adapter):
    """
    Test 13: _call_claude_with_retry succès 1ère tentative

    Vérifie que retry logic fonctionne sans retry si succès immédiat
    """
    # Setup mock adapter
    mock_adapter = AsyncMock()
    mock_adapter.complete.return_value = {"content": "Brouillon généré avec succès"}
    mock_get_adapter.return_value = mock_adapter

    # Execute
    result = await _call_claude_with_retry(
        system_prompt="System test",
        user_prompt="User test",
        temperature=0.7,
        max_tokens=2000,
        max_retries=3,
    )

    # Assertions
    assert result == "Brouillon généré avec succès"
    assert mock_adapter.complete.call_count == 1  # Succès 1ère tentative


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.get_llm_adapter")
async def test_call_claude_with_retry_success_after_retries(mock_get_adapter):
    """
    Test 14: _call_claude_with_retry succès après 2 échecs

    Vérifie que retry logic retry jusqu'au succès
    """
    # Setup mock adapter
    mock_adapter = AsyncMock()

    # 1ère et 2ème tentatives échouent, 3ème réussit
    mock_adapter.complete.side_effect = [
        Exception("Temporary error 1"),
        Exception("Temporary error 2"),
        {"content": "Succès après retries"},
    ]
    mock_get_adapter.return_value = mock_adapter

    # Execute
    result = await _call_claude_with_retry(
        system_prompt="System test",
        user_prompt="User test",
        temperature=0.7,
        max_tokens=2000,
        max_retries=3,
    )

    # Assertions
    assert result == "Succès après retries"
    assert mock_adapter.complete.call_count == 3  # 2 échecs + 1 succès


@pytest.mark.asyncio
@patch("agents.src.agents.email.draft_reply.get_llm_adapter")
async def test_call_claude_with_retry_fail_after_max_retries(mock_get_adapter):
    """
    Test 15: _call_claude_with_retry raise après max_retries échecs

    Vérifie que Exception est raised après max_retries tentatives
    """
    # Setup mock adapter
    mock_adapter = AsyncMock()

    # Toutes les tentatives échouent
    mock_adapter.complete.side_effect = Exception("Persistent error")
    mock_get_adapter.return_value = mock_adapter

    # Execute - devrait raise Exception
    with pytest.raises(Exception) as exc_info:
        await _call_claude_with_retry(
            system_prompt="System test",
            user_prompt="User test",
            temperature=0.7,
            max_tokens=2000,
            max_retries=3,
        )

    # Assertions
    assert "Claude API failed after 3 attempts" in str(exc_info.value)
    assert mock_adapter.complete.call_count == 3
