"""
Friday 2.0 - Email Adapter (D25 : IMAP Direct remplace EmailEngine)

Architecture:
    - EmailAdapter : Interface abstraite (ABC)
    - IMAPDirectAdapter : Implementation IMAP direct (aioimaplib + aiosmtplib)
    - get_email_adapter() : Factory pattern

Le consumer et le fetcher utilisent cet adaptateur. Si besoin de
rebrancher EmailEngine ou un autre provider, changer UN fichier.

Decision: D25 (2026-02-13) - EmailEngine retire, IMAP direct
Libs: aioimaplib 2.0.1, aiosmtplib
Date: 2026-02-13
Version: 1.0.0
"""

import email
import os
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


# ============================================================================
# Models
# ============================================================================


class EmailMessage(BaseModel):
    """Email recupere via IMAP"""

    message_id: str = Field(..., description="Message-ID header ou UID IMAP")
    account_id: str = Field(..., description="ID compte IMAP source")
    from_address: str = Field(..., description="Adresse expediteur")
    from_name: str = Field("", description="Nom expediteur")
    to_addresses: List[str] = Field(default_factory=list, description="Destinataires")
    subject: str = Field("", description="Sujet")
    body_text: str = Field("", description="Corps texte brut")
    body_html: str = Field("", description="Corps HTML")
    date: str = Field("", description="Date ISO8601")
    has_attachments: bool = Field(False, description="Presence pieces jointes")
    attachments: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Liste PJ [{filename, content_type, size, part_id}]",
    )
    raw_headers: Dict[str, str] = Field(
        default_factory=dict, description="Headers bruts pour threading"
    )


class SendResult(BaseModel):
    """Resultat envoi SMTP"""

    success: bool
    message_id: str = Field("", description="Message-ID genere")
    error: str = Field("", description="Message erreur si echec")


class AccountHealth(BaseModel):
    """Etat sante d'un compte email"""

    account_id: str
    email: str
    status: str  # connected, disconnected, error, auth_failed
    last_sync: Optional[str] = None
    error: Optional[str] = None


class EmailAdapterError(Exception):
    """Erreur adaptateur email"""

    pass


class IMAPConnectionError(EmailAdapterError):
    """Erreur connexion IMAP"""

    pass


class SMTPSendError(EmailAdapterError):
    """Erreur envoi SMTP"""

    pass


# ============================================================================
# Interface abstraite
# ============================================================================


class EmailAdapter(ABC):
    """
    Interface abstraite pour provider email.

    Implementations:
        - IMAPDirectAdapter : IMAP direct via aioimaplib (D25)
        - (future) EmailEngineAdapter : si besoin de revenir a EmailEngine
    """

    @abstractmethod
    async def get_message(
        self, account_id: str, message_id: str
    ) -> EmailMessage:
        """
        Recupere un email complet.

        Args:
            account_id: ID compte IMAP
            message_id: UID IMAP ou Message-ID

        Returns:
            EmailMessage avec body, headers, metadata PJ

        Raises:
            EmailAdapterError: Si fetch echoue
        """
        raise NotImplementedError

    @abstractmethod
    async def download_attachment(
        self, account_id: str, message_id: str, part_id: str
    ) -> bytes:
        """
        Telecharge une piece jointe.

        Args:
            account_id: ID compte IMAP
            message_id: UID IMAP
            part_id: ID de la partie MIME (ex: "1.2")

        Returns:
            Bytes du fichier

        Raises:
            EmailAdapterError: Si download echoue
        """
        raise NotImplementedError

    @abstractmethod
    async def send_message(
        self,
        account_id: str,
        to: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[List[str]] = None,
    ) -> SendResult:
        """
        Envoie un email via SMTP.

        Args:
            account_id: ID compte pour envoi
            to: Destinataire
            subject: Sujet
            body_text: Corps texte
            body_html: Corps HTML (optionnel)
            in_reply_to: Message-ID original (threading)
            references: Liste Message-IDs conversation (threading)

        Returns:
            SendResult

        Raises:
            SMTPSendError: Si envoi echoue apres retries
        """
        raise NotImplementedError

    @abstractmethod
    async def check_health(self) -> List[AccountHealth]:
        """
        Verifie l'etat de tous les comptes.

        Returns:
            Liste AccountHealth par compte
        """
        raise NotImplementedError


# ============================================================================
# Implementation IMAP Direct (D25)
# ============================================================================


class IMAPDirectAdapter(EmailAdapter):
    """
    Adapter IMAP direct via aioimaplib + aiosmtplib.

    Decision D25 : Remplace EmailEngine (99 EUR/an economises).
    Latence : 2-5s (IMAP IDLE) vs <1s (EmailEngine webhook).

    NOTE: Cette classe est utilisee par le consumer pour fetch/send.
    Le fetcher IMAP (imap_fetcher.py) gere la detection de nouveaux
    mails et publie dans Redis Streams. L'adapter est pour les
    operations on-demand (fetch message complet, download PJ, send).
    """

    def __init__(self, accounts_config: Optional[Dict[str, Dict]] = None):
        """
        Args:
            accounts_config: Config comptes IMAP/SMTP. Si None, charge depuis env vars.
                Format: {
                    "account_professional": {
                        "email": "user@gmail.com",
                        "imap_host": "imap.gmail.com",
                        "imap_port": 993,
                        "imap_user": "user@gmail.com",
                        "imap_password": "app_password",
                        "smtp_host": "smtp.gmail.com",
                        "smtp_port": 587,
                        "auth_method": "app_password"
                    },
                    ...
                }
        """
        self._accounts = accounts_config or self._load_accounts_from_env()
        self._imap_connections: Dict[str, Any] = {}

    def _load_accounts_from_env(self) -> Dict[str, Dict]:
        """Charge config comptes depuis variables d'environnement."""
        accounts = {}

        # Format: IMAP_ACCOUNT_{ID}_EMAIL, IMAP_ACCOUNT_{ID}_HOST, etc.
        # Detecter les comptes configures
        for key, value in os.environ.items():
            if key.startswith("IMAP_ACCOUNT_") and key.endswith("_EMAIL"):
                account_id = key.replace("IMAP_ACCOUNT_", "").replace("_EMAIL", "").lower()
                prefix = f"IMAP_ACCOUNT_{account_id.upper()}"

                accounts[f"account_{account_id}"] = {
                    "email": value,
                    "imap_host": os.getenv(f"{prefix}_IMAP_HOST", ""),
                    "imap_port": int(os.getenv(f"{prefix}_IMAP_PORT", "993")),
                    "imap_user": os.getenv(f"{prefix}_IMAP_USER", value),
                    "imap_password": os.getenv(f"{prefix}_IMAP_PASSWORD", ""),
                    "smtp_host": os.getenv(f"{prefix}_SMTP_HOST", ""),
                    "smtp_port": int(os.getenv(f"{prefix}_SMTP_PORT", "587")),
                    "auth_method": os.getenv(f"{prefix}_AUTH_METHOD", "app_password"),
                }

        if not accounts:
            logger.warning("no_imap_accounts_configured")

        return accounts

    async def get_message(
        self, account_id: str, message_id: str
    ) -> EmailMessage:
        """Fetch email complet via IMAP FETCH."""
        try:
            import aioimaplib

            account = self._get_account(account_id)

            imap = aioimaplib.IMAP4_SSL(
                host=account["imap_host"],
                port=account["imap_port"],
            )
            await imap.wait_hello_from_server()
            await imap.login(account["imap_user"], account["imap_password"])
            await imap.select("INBOX")

            # Fetch par UID
            status, data = await imap.uid(
                "fetch", message_id, "(RFC822)"
            )

            if status != "OK" or not data or not data[0]:
                raise EmailAdapterError(
                    f"IMAP fetch failed for {account_id}/{message_id}: {status}"
                )

            # Parser le message RFC822
            raw_bytes = data[0]
            if isinstance(raw_bytes, tuple):
                raw_bytes = raw_bytes[1]

            msg = email.message_from_bytes(raw_bytes)

            # Extraire body
            body_text = ""
            body_html = ""
            attachments = []

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))

                    if "attachment" in content_disposition:
                        attachments.append({
                            "filename": part.get_filename() or "unnamed",
                            "content_type": content_type,
                            "size": len(part.get_payload(decode=True) or b""),
                            "part_id": part.get("X-Attachment-Id", ""),
                        })
                    elif content_type == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body_text = payload.decode(
                                part.get_content_charset() or "utf-8", errors="replace"
                            )
                    elif content_type == "text/html":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body_html = payload.decode(
                                part.get_content_charset() or "utf-8", errors="replace"
                            )
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    text = payload.decode(
                        msg.get_content_charset() or "utf-8", errors="replace"
                    )
                    if msg.get_content_type() == "text/html":
                        body_html = text
                    else:
                        body_text = text

            # Extraire from
            from_header = msg.get("From", "")
            from_name = ""
            from_address = from_header
            if "<" in from_header and ">" in from_header:
                from_name = from_header.split("<")[0].strip().strip('"')
                from_address = from_header.split("<")[1].split(">")[0]

            # Extraire to
            to_header = msg.get("To", "")
            to_addresses = [
                addr.strip() for addr in to_header.split(",") if addr.strip()
            ]

            result = EmailMessage(
                message_id=message_id,
                account_id=account_id,
                from_address=from_address,
                from_name=from_name,
                to_addresses=to_addresses,
                subject=msg.get("Subject", ""),
                body_text=body_text,
                body_html=body_html,
                date=msg.get("Date", ""),
                has_attachments=len(attachments) > 0,
                attachments=attachments,
                raw_headers={
                    "message-id": msg.get("Message-ID", ""),
                    "in-reply-to": msg.get("In-Reply-To", ""),
                    "references": msg.get("References", ""),
                },
            )

            await imap.logout()
            return result

        except ImportError:
            raise EmailAdapterError(
                "aioimaplib not installed. Run: pip install aioimaplib>=2.0.1"
            )
        except EmailAdapterError:
            raise
        except Exception as e:
            logger.error(
                "imap_get_message_failed",
                account_id=account_id,
                message_id=message_id,
                error=str(e),
            )
            raise EmailAdapterError(f"IMAP get_message failed: {e}") from e

    async def download_attachment(
        self, account_id: str, message_id: str, part_id: str
    ) -> bytes:
        """Download piece jointe via IMAP FETCH BODY[part_id]."""
        try:
            import aioimaplib

            account = self._get_account(account_id)

            imap = aioimaplib.IMAP4_SSL(
                host=account["imap_host"],
                port=account["imap_port"],
            )
            await imap.wait_hello_from_server()
            await imap.login(account["imap_user"], account["imap_password"])
            await imap.select("INBOX")

            # Fetch la partie specifique
            status, data = await imap.uid(
                "fetch", message_id, f"(BODY[{part_id}])"
            )

            if status != "OK" or not data or not data[0]:
                raise EmailAdapterError(
                    f"IMAP attachment fetch failed: {status}"
                )

            raw_bytes = data[0]
            if isinstance(raw_bytes, tuple):
                raw_bytes = raw_bytes[1]

            await imap.logout()
            return raw_bytes

        except ImportError:
            raise EmailAdapterError(
                "aioimaplib not installed. Run: pip install aioimaplib>=2.0.1"
            )
        except EmailAdapterError:
            raise
        except Exception as e:
            logger.error(
                "imap_download_attachment_failed",
                account_id=account_id,
                message_id=message_id,
                part_id=part_id,
                error=str(e),
            )
            raise EmailAdapterError(f"IMAP download_attachment failed: {e}") from e

    async def send_message(
        self,
        account_id: str,
        to: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[List[str]] = None,
    ) -> SendResult:
        """Envoie email via SMTP (aiosmtplib). Delegue a smtp_sender."""
        try:
            from services.email_processor.smtp_sender import send_email

            account = self._get_account(account_id)

            return await send_email(
                smtp_host=account["smtp_host"],
                smtp_port=account["smtp_port"],
                smtp_user=account["imap_user"],
                smtp_password=account["imap_password"],
                from_addr=account["email"],
                to_addr=to,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                in_reply_to=in_reply_to,
                references=references,
            )

        except ImportError:
            raise SMTPSendError(
                "smtp_sender module not found. Ensure services/email_processor/smtp_sender.py exists."
            )
        except Exception as e:
            logger.error(
                "smtp_send_failed",
                account_id=account_id,
                to=to,
                error=str(e),
            )
            raise SMTPSendError(f"SMTP send failed: {e}") from e

    async def check_health(self) -> List[AccountHealth]:
        """Teste connexion IMAP pour chaque compte."""
        results = []

        for account_id, config in self._accounts.items():
            try:
                import aioimaplib

                imap = aioimaplib.IMAP4_SSL(
                    host=config["imap_host"],
                    port=config["imap_port"],
                )
                await imap.wait_hello_from_server()
                await imap.login(config["imap_user"], config["imap_password"])
                await imap.logout()

                results.append(
                    AccountHealth(
                        account_id=account_id,
                        email=config["email"],
                        status="connected",
                    )
                )

            except Exception as e:
                results.append(
                    AccountHealth(
                        account_id=account_id,
                        email=config.get("email", "unknown"),
                        status="error",
                        error=str(e),
                    )
                )

        return results

    def _get_account(self, account_id: str) -> Dict:
        """Recupere config d'un compte par ID."""
        if account_id not in self._accounts:
            raise EmailAdapterError(
                f"Account '{account_id}' not configured. "
                f"Available: {list(self._accounts.keys())}"
            )
        return self._accounts[account_id]

    def get_account_email(self, account_id: str) -> str:
        """Retourne l'email d'un compte."""
        return self._get_account(account_id)["email"]

    def list_accounts(self) -> List[str]:
        """Liste les IDs de comptes configures."""
        return list(self._accounts.keys())


# ============================================================================
# Factory
# ============================================================================


def get_email_adapter(
    provider: Optional[str] = None,
    accounts_config: Optional[Dict[str, Dict]] = None,
) -> EmailAdapter:
    """
    Factory pour creer un adapter email.

    Args:
        provider: Provider email (defaut: env var EMAIL_PROVIDER ou "imap_direct")
        accounts_config: Config comptes (optionnel, charge depuis env sinon)

    Returns:
        EmailAdapter configure

    Raises:
        NotImplementedError: Si provider non supporte
    """
    provider = provider or os.getenv("EMAIL_PROVIDER", "imap_direct")

    if provider == "imap_direct":
        return IMAPDirectAdapter(accounts_config=accounts_config)

    raise NotImplementedError(
        f"Email provider '{provider}' not supported. "
        f"Available: 'imap_direct'. "
        f"Set EMAIL_PROVIDER=imap_direct in environment."
    )
