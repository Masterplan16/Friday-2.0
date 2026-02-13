"""
Friday 2.0 - SMTP Sender (D25 : remplace EmailEngine send_message)

Envoi email async via aiosmtplib avec :
- Threading conversation (In-Reply-To + References headers)
- MIME multipart (text/plain + text/html + pieces jointes)
- Retry backoff exponentiel (3 tentatives transitoires)
- Bounces : erreurs permanentes (550, 553) = pas de retry
- Support TLS/STARTTLS

Decision: D25 (2026-02-13)
Version: 1.0.0
"""

import asyncio
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from typing import List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)

# Codes SMTP permanents (pas de retry)
PERMANENT_SMTP_ERRORS = {
    550,  # Mailbox not found
    551,  # User not local
    552,  # Storage allocation exceeded
    553,  # Mailbox name not allowed
    554,  # Transaction failed
    556,  # Domain does not accept mail
}


class SMTPSendError(Exception):
    """Erreur envoi SMTP apres tous les retries."""

    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


async def send_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    from_addr: str,
    to_addr: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[List[str]] = None,
    attachments: Optional[List[Tuple[str, bytes, str]]] = None,
    max_retries: int = 3,
) -> "SendResult":
    """
    Envoie un email via SMTP avec aiosmtplib.

    Args:
        smtp_host: Serveur SMTP
        smtp_port: Port SMTP (587 pour STARTTLS, 465 pour SSL)
        smtp_user: Utilisateur SMTP
        smtp_password: Mot de passe SMTP
        from_addr: Adresse expediteur
        to_addr: Adresse destinataire
        subject: Sujet
        body_text: Corps texte brut
        body_html: Corps HTML (optionnel)
        in_reply_to: Message-ID original pour threading (faille #7)
        references: Liste Message-IDs conversation pour threading (faille #7)
        attachments: Liste [(filename, data_bytes, content_type)] (faille #7)
        max_retries: Nombre max tentatives (defaut 3)

    Returns:
        SendResult (from adapters.email)

    Raises:
        SMTPSendError: Si envoi echoue apres retries
    """
    from agents.src.adapters.email import SendResult

    # Construire le message MIME
    msg = _build_mime_message(
        from_addr=from_addr,
        to_addr=to_addr,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        in_reply_to=in_reply_to,
        references=references,
        attachments=attachments,
    )

    generated_message_id = msg["Message-ID"]

    # Retry avec backoff exponentiel
    for attempt in range(1, max_retries + 1):
        try:
            import aiosmtplib

            # Determiner mode SSL
            use_tls = smtp_port == 465
            start_tls = smtp_port == 587

            response = await aiosmtplib.send(
                msg,
                hostname=smtp_host,
                port=smtp_port,
                username=smtp_user,
                password=smtp_password,
                use_tls=use_tls,
                start_tls=start_tls,
                timeout=30,
            )

            logger.info(
                "smtp_send_success",
                to=to_addr,
                subject=subject[:50],
                message_id=generated_message_id,
                attempt=attempt,
            )

            return SendResult(
                success=True,
                message_id=generated_message_id,
            )

        except ImportError:
            raise SMTPSendError(
                "aiosmtplib not installed. Run: pip install aiosmtplib>=2.0.0",
                permanent=True,
            )

        except Exception as e:
            error_str = str(e)

            # Verifier si erreur permanente (pas de retry)
            is_permanent = _is_permanent_error(e)

            if is_permanent:
                logger.error(
                    "smtp_permanent_error",
                    to=to_addr,
                    error=error_str,
                    attempt=attempt,
                )
                return SendResult(
                    success=False,
                    message_id=generated_message_id,
                    error=f"Permanent SMTP error: {error_str}",
                )

            if attempt == max_retries:
                logger.error(
                    "smtp_max_retries_exceeded",
                    to=to_addr,
                    error=error_str,
                    max_retries=max_retries,
                )
                return SendResult(
                    success=False,
                    message_id=generated_message_id,
                    error=f"SMTP failed after {max_retries} attempts: {error_str}",
                )

            # Backoff exponentiel : 1s, 2s
            backoff = 2 ** (attempt - 1)
            logger.warning(
                "smtp_retry",
                to=to_addr,
                error=error_str,
                attempt=attempt,
                next_retry_seconds=backoff,
            )
            await asyncio.sleep(backoff)

    # Ne devrait jamais arriver ici
    return SendResult(
        success=False,
        message_id=generated_message_id,
        error="Unexpected error in retry loop",
    )


def _build_mime_message(
    from_addr: str,
    to_addr: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[List[str]] = None,
    attachments: Optional[List[Tuple[str, bytes, str]]] = None,
) -> MIMEMultipart:
    """
    Construit un message MIME complet avec threading et pieces jointes.

    Threading (faille #7 corrigee) :
    - In-Reply-To : Message-ID de l'email auquel on repond
    - References : Liste de Message-IDs de la conversation

    MIME multipart (faille #7) :
    - text/plain obligatoire
    - text/html optionnel
    - pieces jointes optionnelles
    """
    # Si PJ ou HTML : multipart/mixed (ou multipart/alternative)
    has_attachments = attachments and len(attachments) > 0

    if has_attachments:
        msg = MIMEMultipart("mixed")
        # Body dans une sous-partie alternative
        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(body_text, "plain", "utf-8"))
        if body_html:
            body_part.attach(MIMEText(body_html, "html", "utf-8"))
        msg.attach(body_part)

        # Pieces jointes
        for filename, data, content_type in attachments:
            maintype, subtype = content_type.split("/", 1) if "/" in content_type else ("application", "octet-stream")
            attachment = MIMEApplication(data, _subtype=subtype)
            attachment.add_header(
                "Content-Disposition", "attachment", filename=filename
            )
            msg.attach(attachment)

    elif body_html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    else:
        # Simple texte
        msg = MIMEMultipart()
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

    # Headers standards
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1] if "@" in from_addr else "friday.local")

    # Threading headers (faille #7)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to

    if references:
        msg["References"] = " ".join(references)

    return msg


def _is_permanent_error(error: Exception) -> bool:
    """
    Verifie si une erreur SMTP est permanente (pas de retry).

    Codes 5xx permanents : 550, 551, 552, 553, 554, 556
    """
    error_str = str(error)

    for code in PERMANENT_SMTP_ERRORS:
        if str(code) in error_str:
            return True

    return False
