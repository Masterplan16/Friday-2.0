"""
Action Executor pour brouillons emails

Exécute l'envoi email via EmailEngine après validation Approve.
Stocke writing_example pour apprentissage few-shot.

Story: 2.5 Brouillon Réponse Email - Task 5 Subtask 5.3
"""

# TODO(M4 - Story future): Migrer vers structlog pour logs structurés JSON
import logging
from typing import Dict, Optional
import asyncpg
import httpx

# Import EmailEngine client
# TODO(Story future): Refactor imports avec proper PYTHONPATH setup au lieu de sys.path.insert
import sys
from pathlib import Path
repo_root = Path(__file__).parent.parent  # bot/ -> repo root (FIX: était .parent seul)
sys.path.insert(0, str(repo_root))

from services.email_processor.emailengine_client import EmailEngineClient, EmailEngineError

logger = logging.getLogger(__name__)


async def send_email_via_emailengine(
    receipt_id: str,
    db_pool: asyncpg.Pool,
    http_client: httpx.AsyncClient,
    emailengine_url: str,
    emailengine_secret: str
) -> Dict:
    """
    Envoyer email via EmailEngine après validation Approve (Story 2.5 AC5)

    Workflow:
        1. Load receipt depuis core.action_receipts
        2. Vérifier status='approved'
        3. Extract draft_body + email_original_id depuis receipt.payload
        4. Fetch email original depuis ingestion.emails
        5. Determine account_id (compte IMAP source)
        6. Send via EmailEngine (avec threading correct)
        7. UPDATE receipt status='executed'
        8. INSERT writing_example (apprentissage few-shot)

    Args:
        receipt_id: UUID du receipt (core.action_receipts)
        db_pool: Pool connexions PostgreSQL
        http_client: HTTP client pour EmailEngine
        emailengine_url: URL base EmailEngine
        emailengine_secret: Bearer token EmailEngine

    Returns:
        Dict avec résultat EmailEngine:
            - messageId: ID message envoyé
            - success: True/False

    Raises:
        ValueError: Si receipt invalid ou status != 'approved'
        EmailEngineError: Si envoi échoue après retries
        Exception: Autres erreurs

    Example:
        >>> result = await send_email_via_emailengine(
        ...     receipt_id="uuid-123",
        ...     db_pool=pool,
        ...     http_client=client,
        ...     emailengine_url="http://localhost:3000",
        ...     emailengine_secret="secret"
        ... )
        >>> print(result['messageId'])
        "<sent-456@example.com>"
    """

    # =======================================================================
    # BLOC 1: Load receipt + email (acquire connexion courte durée)
    # =======================================================================

    async with db_pool.acquire() as conn:
        # Étape 1 : Load receipt
        receipt = await conn.fetchrow(
            "SELECT * FROM core.action_receipts WHERE id=$1",
            receipt_id
        )

        if not receipt:
            raise ValueError(f"Receipt {receipt_id} not found")

        # Étape 2 : Vérifier status='approved'
        if receipt['status'] != 'approved':
            raise ValueError(
                f"Receipt {receipt_id} status is '{receipt['status']}', "
                f"expected 'approved'"
            )

        # Étape 3 : Extract payload
        payload = receipt['payload']
        draft_body = payload.get('draft_body')
        email_original_id = payload.get('email_original_id')
        email_type = payload.get('email_type', 'professional')

        if not draft_body:
            raise ValueError(f"Receipt {receipt_id} missing draft_body in payload")

        if not email_original_id:
            raise ValueError(f"Receipt {receipt_id} missing email_original_id in payload")

        # Étape 4 : Fetch email original
        email_original = await conn.fetchrow(
            "SELECT * FROM ingestion.emails WHERE id=$1",
            email_original_id
        )

        if not email_original:
            raise ValueError(f"Email original {email_original_id} not found")

    # Extract data needed for EmailEngine (hors DB context)
    recipient_email = email_original['sender_email']
    original_subject = email_original['subject']
    subject = f"Re: {original_subject}"
    in_reply_to = email_original.get('message_id')
    references = [in_reply_to] if in_reply_to else []

    # =======================================================================
    # BLOC 2: Send via EmailEngine (SANS connexion DB - évite pool exhaustion)
    # =======================================================================

    # Create EmailEngine client
    emailengine_client = EmailEngineClient(
        http_client=http_client,
        base_url=emailengine_url,
        secret=emailengine_secret
    )

    account_id = emailengine_client.determine_account_id(dict(email_original))

    # Convert plain text to simple HTML
    body_html = f"<p>{draft_body.replace(chr(10), '<br>')}</p>"

    try:
        result = await emailengine_client.send_message(
            account_id=account_id,
            recipient_email=recipient_email,
            subject=subject,
            body_text=draft_body,
            body_html=body_html,
            in_reply_to=in_reply_to,
            references=references
        )

        logger.info(
            "email_sent_via_emailengine",
            receipt_id=receipt_id,
            message_id=result.get('messageId'),
            recipient=recipient_email
        )

    except EmailEngineError as e:
        logger.error(
            "emailengine_send_failed",
            receipt_id=receipt_id,
            error=str(e),
            exc_info=True
        )
        # UPDATE receipt status='failed' (acquire nouvelle connexion)
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE core.action_receipts
                SET status='failed', executed_at=NOW()
                WHERE id=$1
                """,
                receipt_id
            )
        raise

    # =======================================================================
    # BLOC 3: Update receipt + writing_example (acquire connexion courte durée)
    # =======================================================================

    async with db_pool.acquire() as conn:
        # Étape 7 : UPDATE receipt status='executed'
        await conn.execute(
            """
            UPDATE core.action_receipts
            SET status='executed', executed_at=NOW()
            WHERE id=$1
            """,
            receipt_id
        )

        # Étape 8 : INSERT writing_example (few-shot learning AC5)
        await conn.execute(
            """
            INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
            VALUES ($1, $2, $3, 'Mainteneur')
            """,
            email_type,
            subject,
            draft_body
        )

        logger.info(
            "writing_example_stored",
            receipt_id=receipt_id,
            email_type=email_type
        )

    # =======================================================================
    # Return success
    # =======================================================================

    return {
        'success': True,
        'messageId': result.get('messageId'),
        'recipient': recipient_email,
        'subject': subject
    }
