"""
Tests E2E critiques pour Story 2.5 - Draft Reply Email

Ces 3 tests E2E critiques valident le pipeline complet:
1. Email → Classification → Draft → Notification
2. Approve → Envoi EmailEngine + Writing Example stocké
3. Anonymisation Presidio bout-en-bout

Story: 2.5 Brouillon Réponse Email
Tests: H2 fix - Tests E2E minimum avant status=done
"""

import asyncio
import asyncpg
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Ces tests nécessitent PostgreSQL + Redis réels (pas mocks)
pytest.skip("E2E tests requièrent infra complète (PostgreSQL + Redis + EmailEngine mock)", allow_module_level=True)


@pytest.fixture
async def db_pool():
    """Pool PostgreSQL test"""
    pool = await asyncpg.create_pool(
        host="localhost",
        port=5432,
        database="friday_test",
        user="postgres",
        password="postgres",
        min_size=1,
        max_size=5
    )
    yield pool
    await pool.close()


@pytest.fixture
async def clean_db(db_pool):
    """Nettoyer DB avant/après test"""
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE ingestion.emails CASCADE")
        await conn.execute("TRUNCATE TABLE core.action_receipts CASCADE")
        await conn.execute("TRUNCATE TABLE core.writing_examples CASCADE")
    yield
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE ingestion.emails CASCADE")
        await conn.execute("TRUNCATE TABLE core.action_receipts CASCADE")
        await conn.execute("TRUNCATE TABLE core.writing_examples CASCADE")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_email_to_draft_notification(db_pool, clean_db):
    """
    TEST E2E CRITIQUE 1: Email → Classification → Draft → Notification Telegram

    Pipeline complet:
    1. Email reçu (EmailEngine webhook simulé)
    2. Classification (professional/medical/academic)
    3. Génération draft via Claude Sonnet 4.5 (mock)
    4. Notification Telegram topic Actions avec inline buttons

    Validations:
    - Email stocké ingestion.emails
    - Receipt créé status='pending'
    - Notification Telegram envoyée (mock)
    - Latence totale <10s (AC4)
    """
    # Setup mocks
    with patch('agents.src.adapters.llm.get_llm_adapter') as mock_llm, \
         patch('agents.src.tools.anonymize.anonymize_text') as mock_anonymize, \
         patch('agents.src.tools.anonymize.deanonymize_text') as mock_deanonymize, \
         patch('bot.handlers.draft_reply_notifications.send_draft_ready_notification') as mock_telegram:

        # Mock Claude API
        mock_llm_instance = AsyncMock()
        mock_llm_instance.complete = AsyncMock(return_value={
            'content': 'Bonjour,\n\nOui, vous pouvez reprogrammer votre rendez-vous.\n\nCordialement,\nDr. Antonio Lopez'
        })
        mock_llm.return_value = mock_llm_instance

        # Mock Presidio (retourne AnonymizationResult)
        from agents.src.tools.anonymize import AnonymizationResult
        mock_anonymize.side_effect = lambda text: AnonymizationResult(
            anonymized_text=text.replace("John Doe", "[NAME_1]"),
            entities_found=[],
            mapping={"[NAME_1]": "John Doe"},
            confidence_min=1.0
        )
        mock_deanonymize.side_effect = lambda text, mapping: text.replace("[NAME_1]", "John Doe")

        # Mock Telegram notification
        mock_telegram.return_value = None

        # 1. Insérer email dans DB (simulate EmailEngine reception)
        start_time = datetime.utcnow()

        async with db_pool.acquire() as conn:
            email_id = await conn.fetchval(
                """
                INSERT INTO ingestion.emails (
                    account_id, message_id, from_anon, subject_anon, body_anon,
                    category, confidence, priority, received_at, has_attachments
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                "account_1",
                "<msg-123@example.com>",
                "[NAME_1]@example.com",
                "Question about appointment",
                "Can I reschedule my appointment?",
                "professional",  # IMPORTANT: category professionelle → trigger draft
                0.95,
                "normal",
                datetime.utcnow(),
                False
            )

        # 2. Trigger draft_email_reply (simulate consumer.py Phase 7)
        from agents.src.agents.email.draft_reply import draft_email_reply

        email_data = {
            'from': 'john.doe@example.com',
            'from_anon': '[NAME_1]@example.com',
            'to': 'antonio.lopez@example.com',
            'subject': 'Question about appointment',
            'subject_anon': 'Question about appointment',
            'body': 'Can I reschedule my appointment?',
            'body_anon': 'Can I reschedule my appointment?',
            'category': 'professional',
            'message_id': '<msg-123@example.com>',
            'sender_email': 'john.doe@example.com',
            'recipient_email': 'antonio.lopez@example.com'
        }

        result = await draft_email_reply(
            email_id=str(email_id),
            email_data=email_data,
            db_pool=db_pool
        )

        # 3. Validations
        assert result.confidence > 0.5, "Confidence doit être > 0.5"
        assert 'draft_body' in result.payload, "Payload doit contenir draft_body"
        assert len(result.payload['draft_body']) > 10, "Draft body ne doit pas être vide"

        # Vérifier receipt créé
        async with db_pool.acquire() as conn:
            receipt = await conn.fetchrow(
                """
                SELECT * FROM core.action_receipts
                WHERE module = 'email' AND action_type = 'draft_reply'
                ORDER BY created_at DESC LIMIT 1
                """
            )

        assert receipt is not None, "Receipt doit être créé"
        assert receipt['status'] == 'pending', "Receipt status doit être pending (trust=propose)"

        # Vérifier latence <10s (AC4)
        latency = (datetime.utcnow() - start_time).total_seconds()
        assert latency < 10, f"Latence {latency}s > 10s (AC4 violation)"

        # Vérifier Telegram notification appelée
        assert mock_telegram.called, "Notification Telegram doit être envoyée"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_approve_send_email_store_example(db_pool, clean_db):
    """
    TEST E2E CRITIQUE 2: Approve → Envoi EmailEngine + Writing Example stocké

    Workflow Approve:
    1. Receipt status=pending créé (test 1)
    2. Mainteneur clique [Approve]
    3. Callback approve_callback traité
    4. EmailEngine API appelé (mock)
    5. Writing example stocké dans core.writing_examples
    6. Receipt status='executed'

    Validations:
    - Email envoyé via EmailEngine (mock)
    - Writing example inséré en DB
    - Receipt status='executed' + validated_by
    """
    with patch('services.email_processor.emailengine_client.EmailEngineClient.send_message') as mock_send:
        # Mock EmailEngine send_message
        mock_send.return_value = {
            'messageId': '<sent-msg-456@example.com>',
            'queueId': 'queue-789',
            'response': '250 Message accepted'
        }

        # 1. Créer receipt pending avec draft_body
        async with db_pool.acquire() as conn:
            receipt_id = await conn.fetchval(
                """
                INSERT INTO core.action_receipts (
                    module, action_type, status, input_summary, output_summary,
                    confidence, reasoning, payload
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                RETURNING id
                """,
                "email",
                "draft_reply",
                "pending",
                "Email de [NAME_1]: Question about...",
                "Brouillon réponse (120 caractères)",
                0.85,
                "Style cohérent avec exemples",
                {
                    "draft_body": "Bonjour,\n\nOui, vous pouvez reprogrammer.\n\nCordialement,\nDr. Lopez",
                    "email_original_id": str(await conn.fetchval("SELECT uuid_generate_v4()")),
                    "email_type": "professional"
                }
            )

            # Créer email original pour send_email_via_emailengine
            email_id = await conn.fetchval(
                """
                INSERT INTO ingestion.emails (
                    account_id, message_id, from_anon, subject_anon, body_anon,
                    category, confidence, priority, received_at, has_attachments
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                "account_1",
                "<msg-original@example.com>",
                "[NAME_1]@example.com",
                "Question",
                "Can I reschedule?",
                "professional",
                0.95,
                "normal",
                datetime.utcnow(),
                False
            )

            # Mettre à jour receipt avec bon email_id
            await conn.execute(
                "UPDATE core.action_receipts SET payload = payload || $1::jsonb WHERE id = $2",
                {'email_original_id': str(email_id)},
                receipt_id
            )

        # 2. Simuler Approve (via action_executor)
        from bot.action_executor_draft_reply import send_email_via_emailengine
        import httpx

        async with httpx.AsyncClient() as http_client:
            result = await send_email_via_emailengine(
                receipt_id=str(receipt_id),
                db_pool=db_pool,
                http_client=http_client,
                emailengine_url="http://localhost:3000",
                emailengine_secret="test_secret"
            )

        # 3. Validations
        assert result['success'] is True, "Envoi doit réussir"
        assert mock_send.called, "EmailEngine send_message doit être appelé"

        # Vérifier receipt status='executed'
        async with db_pool.acquire() as conn:
            receipt = await conn.fetchrow(
                "SELECT status FROM core.action_receipts WHERE id = $1",
                receipt_id
            )
        assert receipt['status'] == 'executed', "Receipt status doit être 'executed'"

        # Vérifier writing_example stocké
        async with db_pool.acquire() as conn:
            example = await conn.fetchrow(
                """
                SELECT * FROM core.writing_examples
                WHERE sent_by = 'Mainteneur' AND email_type = 'professional'
                ORDER BY created_at DESC LIMIT 1
                """
            )

        assert example is not None, "Writing example doit être stocké"
        assert 'reprogrammer' in example['body'], "Body doit contenir le draft envoyé"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_presidio_anonymization_end_to_end(db_pool, clean_db):
    """
    TEST E2E CRITIQUE 3: Anonymisation Presidio bout-en-bout

    Validation RGPD (AC1 - NFR6, NFR7):
    1. Email contient PII (nom, email, date)
    2. Anonymisation AVANT appel Claude cloud
    3. Dé-anonymisation APRÈS réponse Claude
    4. PII stockée CHIFFRÉE en DB (ingestion.emails_raw)
    5. PII JAMAIS envoyée à Claude en clair

    CRITIQUE: Vérifier que PII n'est JAMAIS loggée ou exposée
    """
    with patch('agents.src.tools.anonymize.anonymize_text') as mock_anonymize, \
         patch('agents.src.tools.anonymize.deanonymize_text') as mock_deanonymize, \
         patch('agents.src.adapters.llm.get_llm_adapter') as mock_llm:

        # Setup: Email avec PII
        email_with_pii = """
        Bonjour Dr. Lopez,

        Je m'appelle Marie Dupont (marie.dupont@example.com).
        Mon numéro de sécu est 1 85 03 75 123 456 78.
        Pouvez-vous me confirmer mon RDV du 15/02/2026 à 14h30?

        Cordialement,
        Marie
        """

        # Mock Presidio anonymize: PII → placeholders
        email_anonymized = """
        Bonjour Dr. Lopez,

        Je m'appelle [NAME_1] ([EMAIL_1]).
        Mon numéro de sécu est [SSN_1].
        Pouvez-vous me confirmer mon RDV du [DATE_1] à [TIME_1]?

        Cordialement,
        [NAME_2]
        """
        from agents.src.tools.anonymize import AnonymizationResult
        mock_anonymize.return_value = AnonymizationResult(
            anonymized_text=email_anonymized,
            entities_found=[{"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.95}],
            mapping={
                "[NAME_1]": "Marie Dupont",
                "[NAME_2]": "Marie",
                "[EMAIL_1]": "marie.dupont@example.com",
                "[SSN_1]": "1 85 03 75 123 456 78",
                "[DATE_1]": "15/02/2026",
                "[TIME_1]": "14h30"
            },
            confidence_min=0.95
        )

        # Mock Claude response (avec placeholders)
        claude_response_anon = """
        Bonjour [NAME_2],

        Je confirme votre rendez-vous du [DATE_1] à [TIME_1].

        Cordialement,
        Dr. Antonio Lopez
        """

        mock_llm_instance = AsyncMock()
        mock_llm_instance.complete = AsyncMock(return_value={'content': claude_response_anon})
        mock_llm.return_value = mock_llm_instance

        # Mock deanonymize: placeholders → PII restaurée (accepte text + mapping)
        claude_response_final = """
        Bonjour Marie,

        Je confirme votre rendez-vous du 15/02/2026 à 14h30.

        Cordialement,
        Dr. Antonio Lopez
        """
        mock_deanonymize.return_value = claude_response_final  # Retourne str directement

        # Execute draft_email_reply
        from agents.src.agents.email.draft_reply import draft_email_reply

        email_data = {
            'from': 'marie.dupont@example.com',
            'from_anon': '[EMAIL_1]',
            'to': 'antonio.lopez@example.com',
            'subject': 'Confirmation RDV',
            'subject_anon': 'Confirmation [MEDICAL_TERM_1]',
            'body': email_with_pii,
            'body_anon': email_anonymized,
            'category': 'medical',
            'message_id': '<msg-pii@example.com>',
            'sender_email': 'marie.dupont@example.com',
            'recipient_email': 'antonio.lopez@example.com'
        }

        email_id = "test-uuid-pii-123"
        result = await draft_email_reply(
            email_id=email_id,
            email_data=email_data,
            db_pool=db_pool
        )

        # VALIDATIONS CRITIQUES RGPD
        # 1. Presidio anonymize appelé AVANT Claude
        assert mock_anonymize.called, "Presidio anonymize DOIT être appelé"

        # 2. Claude reçoit UNIQUEMENT texte anonymisé (vérifier args)
        claude_call_args = mock_llm_instance.complete.call_args
        prompt_sent_to_claude = claude_call_args[1]['messages'][1]['content']  # User prompt

        # CRITICAL: Vérifier que PII n'est PAS dans prompt Claude
        assert 'Marie Dupont' not in prompt_sent_to_claude, "PII nom NE DOIT PAS être envoyée à Claude"
        assert 'marie.dupont@example.com' not in prompt_sent_to_claude, "PII email NE DOIT PAS être envoyée à Claude"
        assert '1 85 03 75 123 456 78' not in prompt_sent_to_claude, "PII SSN NE DOIT PAS être envoyée à Claude"

        # Vérifier que placeholders SONT présents
        assert '[NAME_' in prompt_sent_to_claude or '[EMAIL_' in prompt_sent_to_claude, \
            "Placeholders Presidio DOIVENT être dans prompt Claude"

        # 3. Presidio deanonymize appelé APRÈS Claude
        assert mock_deanonymize.called, "Presidio deanonymize DOIT être appelé"

        # 4. Draft final contient PII restaurée
        draft_final = result.payload['draft_body']
        assert 'Marie' in draft_final, "PII prénom DOIT être restaurée dans draft final"
        assert '15/02/2026' in draft_final, "PII date DOIT être restaurée"

        # 5. Pas de placeholders résiduels dans draft final
        assert '[NAME_' not in draft_final, "Placeholders NE DOIVENT PAS rester dans draft final"
        assert '[DATE_' not in draft_final, "Placeholders NE DOIVENT PAS rester dans draft final"

        print("✅ RGPD TEST PASS: Anonymisation bout-en-bout validée, PII JAMAIS exposée à Claude")
