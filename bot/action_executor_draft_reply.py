"""
Action Executor pour brouillons emails

Execute l'envoi email via adapter IMAP/SMTP apres validation Approve.
Stocke writing_example pour apprentissage few-shot.

D25 (2026-02-13): Refactore pour utiliser email adapter (IMAP direct)
au lieu de EmailEngineClient.

Story: 2.5 Brouillon Reponse Email - Task 5 Subtask 5.3
Story: 2.6 Envoi Emails Approuves - Task 1.2 (notifications)
"""

# TODO(M4 - Story future): Migrer vers structlog pour logs structurés JSON
import html
import logging
from datetime import datetime
from typing import Dict, Optional

import asyncpg
import httpx
from telegram import Bot

# Import email adapter (D25: remplace EmailEngineClient)
try:
    from agents.src.adapters.email import EmailAdapterError, SMTPSendError, get_email_adapter
except ImportError:
    get_email_adapter = None  # type: ignore[assignment,misc]
    EmailAdapterError = Exception  # type: ignore[assignment,misc]
    SMTPSendError = Exception  # type: ignore[assignment,misc]
from bot.handlers.draft_reply_notifications import (
    send_email_confirmation_notification,
    send_email_failure_notification,
)

try:
    from agents.src.tools.anonymize import anonymize_text
except ImportError:
    anonymize_text = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Account name mapping for notifications (Story 2.6 AC3)
ACCOUNT_NAME_MAPPING = {
    "account_professional": "professional",
    "account_medical": "medical",
    "account_academic": "academic",
    "account_personal": "personal",
}


async def send_email_via_emailengine(
    receipt_id: str,
    db_pool: asyncpg.Pool,
    http_client: Optional[httpx.AsyncClient] = None,
    emailengine_url: str = "",
    emailengine_secret: str = "",
    bot: Optional[Bot] = None,
) -> Dict:
    """
    Envoyer email apres validation Approve (Story 2.5 AC5)

    D25: Utilise adapter IMAP/SMTP au lieu de EmailEngine.
    Signature gardee pour compatibilite (http_client/url/secret ignores).

    Workflow (Story 2.6 modifie):
        1. Load receipt depuis core.action_receipts
        2. Verifier status='approved'
        3. Extract draft_body + email_original_id depuis receipt.payload
        4. Fetch email original depuis ingestion.emails
        5. Determine account_id (compte IMAP source)
        6. Send via adapter SMTP (avec threading correct)
        7. [Story 2.6] Notification confirmation topic Email (AC3)
        8. UPDATE receipt status='executed'
        9. INSERT writing_example (apprentissage few-shot)

    Args:
        receipt_id: UUID du receipt (core.action_receipts)
        db_pool: Pool connexions PostgreSQL
        http_client: [DEPRECATED D25] Ignore, garde pour compat
        emailengine_url: [DEPRECATED D25] Ignore
        emailengine_secret: [DEPRECATED D25] Ignore
        bot: Instance Telegram Bot (optionnel, pour notifications Story 2.6)

    Returns:
        Dict avec resultat envoi:
            - messageId: ID message envoye
            - success: True/False

    Raises:
        ValueError: Si receipt invalid ou status != 'approved'
        SMTPSendError: Si envoi echoue apres retries
        Exception: Autres erreurs
    """

    # =======================================================================
    # BLOC 1: Load receipt + email (acquire connexion courte durée)
    # =======================================================================

    async with db_pool.acquire() as conn:
        # Étape 1 : Load receipt
        receipt = await conn.fetchrow("SELECT * FROM core.action_receipts WHERE id=$1", receipt_id)

        if not receipt:
            raise ValueError(f"Receipt {receipt_id} not found")

        # Étape 2 : Vérifier status='approved'
        if receipt["status"] != "approved":
            raise ValueError(
                f"Receipt {receipt_id} status is '{receipt['status']}', " f"expected 'approved'"
            )

        # Étape 3 : Extract payload
        payload = receipt["payload"]
        draft_body = payload.get("draft_body")
        email_original_id = payload.get("email_original_id")
        email_type = payload.get("email_type", "professional")

        if not draft_body:
            raise ValueError(f"Receipt {receipt_id} missing draft_body in payload")

        if not email_original_id:
            raise ValueError(f"Receipt {receipt_id} missing email_original_id in payload")

        # Étape 4 : Fetch email original
        email_original = await conn.fetchrow(
            "SELECT * FROM ingestion.emails WHERE id=$1", email_original_id
        )

        if not email_original:
            raise ValueError(f"Email original {email_original_id} not found")

    # Extract data needed for EmailEngine (hors DB context)
    recipient_email = email_original["sender_email"]
    original_subject = email_original["subject"]
    subject = f"Re: {original_subject}"
    in_reply_to = email_original.get("message_id")
    references = [in_reply_to] if in_reply_to else []

    # =======================================================================
    # BLOC 2: Send via adapter SMTP (D25: remplace EmailEngine)
    # =======================================================================

    # Determine account_id depuis email original
    account_id = _determine_account_id(dict(email_original))

    # Convert plain text to simple HTML (escape HTML + convert newlines)
    escaped_body = html.escape(draft_body).replace("\n", "<br>")
    body_html = f"<p>{escaped_body}</p>"

    try:
        email_adapter = get_email_adapter()
        send_result = await email_adapter.send_message(
            account_id=account_id,
            to=recipient_email,
            subject=subject,
            body_text=draft_body,
            body_html=body_html,
            in_reply_to=in_reply_to,
            references=references,
        )

        if not send_result.success:
            raise SMTPSendError(f"SMTP send failed: {send_result.error}")

        result = {"messageId": send_result.message_id, "success": True}

        logger.info(
            "email_sent_via_adapter",
            receipt_id=receipt_id,
            message_id=send_result.message_id,
            recipient=recipient_email,
        )

        # ========================================================================
        # AJOUT Story 2.6 : Notification confirmation (AC3)
        # ========================================================================

        if bot:
            # Anonymiser recipient + subject pour notification
            try:
                recipient_anon_result = await anonymize_text(recipient_email)
                recipient_anon = recipient_anon_result.anonymized_text

                subject_anon_result = await anonymize_text(subject)
                subject_anon = subject_anon_result.anonymized_text

                # Déterminer nom compte (professional/medical/academic/personal)
                account_name = ACCOUNT_NAME_MAPPING.get(account_id, account_id)

                # Envoyer notification topic Email
                await send_email_confirmation_notification(
                    bot=bot,
                    receipt_id=receipt_id,
                    recipient_anon=recipient_anon,
                    subject_anon=subject_anon,
                    account_name=account_name,
                    sent_at=datetime.now(),
                )

            except Exception as notif_error:
                # Échec notification ne bloque pas workflow (AC3)
                logger.warning(
                    "email_confirmation_notification_failed",
                    receipt_id=receipt_id,
                    error=str(notif_error),
                )

    except (SMTPSendError, EmailAdapterError) as e:
        logger.error("smtp_send_failed", receipt_id=receipt_id, error=str(e), exc_info=True)
        # UPDATE receipt status='failed' (acquire nouvelle connexion)
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE core.action_receipts
                SET status='failed', executed_at=NOW()
                WHERE id=$1
                """,
                receipt_id,
            )

        # ========================================================================
        # AJOUT Story 2.6 : Notification échec (AC5)
        # ========================================================================

        if bot:
            # Anonymiser recipient pour notification
            try:
                recipient_anon_result = await anonymize_text(recipient_email)
                recipient_anon = recipient_anon_result.anonymized_text

                # Envoyer notification topic System
                await send_email_failure_notification(
                    bot=bot,
                    receipt_id=receipt_id,
                    error_message=str(e),
                    recipient_anon=recipient_anon,
                )

            except Exception as notif_error:
                # Log error mais ne raise pas (notification = best effort)
                logger.error(
                    "email_failure_notification_failed",
                    receipt_id=receipt_id,
                    error=str(notif_error),
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
            receipt_id,
        )

        # Étape 8 : INSERT writing_example (few-shot learning AC5)
        await conn.execute(
            """
            INSERT INTO core.writing_examples (email_type, subject, body, sent_by)
            VALUES ($1, $2, $3, 'Mainteneur')
            """,
            email_type,
            subject,
            draft_body,
        )

        logger.info("writing_example_stored", receipt_id=receipt_id, email_type=email_type)

    # =======================================================================
    # Return success
    # =======================================================================

    return {
        "success": True,
        "messageId": result.get("messageId"),
        "recipient": recipient_email,
        "subject": subject,
    }


def _determine_account_id(email_original: Dict) -> str:
    """
    Determine le compte IMAP source pour reponse.

    Mapping recipient → account_id. Fallback: account_medical.

    Args:
        email_original: Email original (dict from DB row)

    Returns:
        Account ID pour envoi reponse
    """
    recipient = email_original.get("recipient_email") or email_original.get("to")

    # Mapping configurable (a terme: depuis DB ou config)
    import os

    mapping_str = os.getenv("ACCOUNT_EMAIL_MAPPING", "")
    if mapping_str:
        # Format: "email1:account1,email2:account2"
        mapping = {}
        for pair in mapping_str.split(","):
            if ":" in pair:
                email, account = pair.strip().split(":", 1)
                mapping[email.strip()] = account.strip()
        if recipient and recipient in mapping:
            return mapping[recipient]

    # Fallback par defaut
    return "account_medical"
