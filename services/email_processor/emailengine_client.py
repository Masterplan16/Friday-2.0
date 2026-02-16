"""
[DEPRECATED D25] EmailEngine API Client Wrapper

DEPRECATED (2026-02-13): Ce fichier est remplace par agents/src/adapters/email.py
(IMAPDirectAdapter + get_email_adapter()). Garder temporairement pour reference
et pour les tests existants qui l'importent. A supprimer dans cleanup final.

Remplace par:
    - agents/src/adapters/email.py (adapter IMAP direct)
    - services/email_processor/smtp_sender.py (envoi SMTP)
    - services/email_processor/imap_fetcher.py (detection nouveaux mails)

Ancien wrapper pour EmailEngine API incluant:
- Récupération emails (get_message)
- Download pièces jointes (download_attachment)
- Envoi emails (send_message) - Story 2.5

Story: 2.1 (get_message, download_attachment), 2.5 (send_message)
"""

import asyncio
from typing import Dict, List, Optional
import httpx

# ============================================================================
# Configuration (M1 FIX - extracted from hardcoded method)
# ============================================================================

# TODO(Story future): Migrer vers config/DB au lieu de constante
# Mapping recipient email → EmailEngine account_id pour envoi réponses
DEFAULT_ACCOUNT_MAPPING = {
    "antonio.lopez@example.com": "account_professional",
    "dr.lopez@hospital.fr": "account_medical",
    "lopez@university.fr": "account_academic",
    "personal@gmail.com": "account_personal",
}


class EmailEngineClient:
    """
    Client wrapper pour EmailEngine API v1

    EmailEngine est un serveur IMAP/SMTP qui expose une API REST pour
    gérer les emails. Ce wrapper simplifie l'interaction avec l'API.

    Attributes:
        http_client: Client HTTP asyncpg pour requêtes API
        base_url: URL base EmailEngine (ex: http://localhost:3000)
        secret: Bearer token pour authentification

    Example:
        >>> client = EmailEngineClient(
        ...     http_client=httpx.AsyncClient(),
        ...     base_url="http://localhost:3000",
        ...     secret="secret_token_123"
        ... )
        >>> email = await client.get_message("account_id/message_id")
        >>> print(email['subject'])
    """

    def __init__(self, http_client: httpx.AsyncClient, base_url: str, secret: str):
        """
        Initialize EmailEngine client

        Args:
            http_client: HTTP client asyncpg (partagé, pas créé ici)
            base_url: URL base EmailEngine sans trailing slash
            secret: Bearer token pour authentification API
        """
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")  # Remove trailing slash if present
        self.secret = secret

    # ========================================================================
    # READ Operations (Story 2.1, 2.4)
    # ========================================================================

    async def get_message(self, message_id: str, account_id: Optional[str] = None) -> Dict:
        """
        Récupère email complet via EmailEngine API

        Args:
            message_id: ID message EmailEngine
            account_id: ID compte IMAP (optionnel, extrait de message_id si format "account/message")

        Returns:
            Dict avec email data:
                - id: message ID
                - subject: sujet
                - from: expéditeur
                - to: destinataires
                - text: corps texte
                - html: corps HTML
                - attachments: liste pièces jointes
                - etc.

        Raises:
            Exception: Si fetch échoue (status != 200)

        Example:
            >>> email = await client.get_message("account1/msg123")
            >>> print(email['subject'])
            "Question about appointment"
        """
        # Extract account_id from message_id format (account_id/message_id)
        if not account_id:
            if "/" in message_id:
                account_id, msg_id = message_id.split("/", 1)
            else:
                # Fallback: utiliser env var ou premier compte
                account_id = "main"  # TODO: Config
                msg_id = message_id
        else:
            msg_id = message_id

        response = await self.http_client.get(
            f"{self.base_url}/v1/account/{account_id}/message/{msg_id}",
            headers={"Authorization": f"Bearer {self.secret}"},
            timeout=30.0,
        )

        if response.status_code != 200:
            raise Exception(
                f"EmailEngine get_message failed: {response.status_code} - {response.text[:200]}"
            )

        return response.json()

    async def download_attachment(
        self, email_id: str, attachment_id: str, account_id: Optional[str] = None
    ) -> bytes:
        """
        Télécharge pièce jointe via EmailEngine API

        Args:
            email_id: ID email source
            attachment_id: ID attachment (from attachments[].id)
            account_id: ID compte IMAP (optionnel)

        Returns:
            Bytes du fichier

        Raises:
            Exception: Si download échoue (status != 200)

        Example:
            >>> data = await client.download_attachment("account1/msg123", "att456")
            >>> len(data)
            15234  # bytes
        """
        # Extract account_id (voir get_message())
        if not account_id:
            if "/" in email_id:
                account_id, msg_id = email_id.split("/", 1)
            else:
                account_id = "main"  # TODO: Config
                msg_id = email_id
        else:
            msg_id = email_id

        response = await self.http_client.get(
            f"{self.base_url}/v1/account/{account_id}/attachment/{attachment_id}",
            headers={"Authorization": f"Bearer {self.secret}"},
            timeout=60.0,  # Timeout plus long pour download
        )

        if response.status_code != 200:
            raise Exception(f"EmailEngine download_attachment failed: {response.status_code}")

        return response.content

    # ========================================================================
    # WRITE Operations (Story 2.5 - Envoi emails)
    # ========================================================================

    async def send_message(
        self,
        account_id: str,
        recipient_email: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[List[str]] = None,
        max_retries: int = 3,
    ) -> Dict:
        """
        Envoyer email via EmailEngine API (Story 2.5 AC5)

        Utilise endpoint POST /v1/account/{accountId}/submit pour envoyer
        un email via le compte IMAP spécifié.

        Args:
            account_id: ID compte IMAP utilisé pour envoi
            recipient_email: Email destinataire (to)
            subject: Sujet email
            body_text: Corps email (texte brut)
            body_html: Corps email (HTML, optionnel)
            in_reply_to: Message-ID email original (threading)
            references: Liste Message-IDs conversation (threading)
            max_retries: Nombre max tentatives retry (défaut: 3)

        Returns:
            Dict avec réponse EmailEngine:
                - messageId: ID message envoyé
                - queueId: ID queue SMTP
                - response: Statut SMTP

        Raises:
            EmailEngineError: Si envoi échoue après max_retries

        Threading Email:
            Pour threading correct (email apparaît dans même conversation):
            - in_reply_to: <message-id> de l'email original
            - references: [<message-id>, ...]  (liste IDs conversation)

        Retry Logic:
            - Tentative 1: Appel direct
            - Tentative 2: Attendre 1s, retry
            - Tentative 3: Attendre 2s, retry
            - Échec: Raise EmailEngineError

        Example:
            >>> result = await client.send_message(
            ...     account_id="account1",
            ...     recipient_email="john@example.com",
            ...     subject="Re: Your question",
            ...     body_text="Bonjour,\\n\\nVoici ma réponse.\\n\\nCordialement,\\nDr. Lopez",
            ...     in_reply_to="<msg-123@example.com>",
            ...     references=["<msg-123@example.com>"]
            ... )
            >>> print(result['messageId'])
            "<sent-456@example.com>"
        """

        # Build payload
        payload = {"to": [{"address": recipient_email}], "subject": subject, "text": body_text}

        # Optional fields
        if body_html:
            payload["html"] = body_html

        if in_reply_to:
            payload["inReplyTo"] = in_reply_to

        if references:
            payload["references"] = references

        # Retry logic avec backoff exponentiel
        for attempt in range(1, max_retries + 1):
            try:
                response = await self.http_client.post(
                    f"{self.base_url}/v1/account/{account_id}/submit",
                    headers={
                        "Authorization": f"Bearer {self.secret}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=30.0,
                )

                if response.status_code == 200:
                    return response.json()

                # Si erreur, continuer retry
                error_text = response.text[:200]

                if attempt == max_retries:
                    raise EmailEngineError(
                        f"EmailEngine send_message failed after {max_retries} attempts: "
                        f"{response.status_code} - {error_text}"
                    )

            except httpx.TimeoutException as e:
                if attempt == max_retries:
                    raise EmailEngineError(
                        f"EmailEngine send_message timeout after {max_retries} attempts: {str(e)}"
                    ) from e

            except httpx.HTTPError as e:
                if attempt == max_retries:
                    raise EmailEngineError(
                        f"EmailEngine send_message HTTP error after {max_retries} attempts: {str(e)}"
                    ) from e

            # Backoff exponentiel: 1s, 2s
            await asyncio.sleep(2 ** (attempt - 1))

        # Ne devrait jamais arriver ici
        raise EmailEngineError("Unexpected error in send_message retry loop")

    # ========================================================================
    # Helpers
    # ========================================================================

    def determine_account_id(self, email_original: Dict) -> str:
        """
        Déterminer le compte IMAP source pour réponse (Story 2.5 Subtask 4.2)

        Logique :
            - Identifier le compte qui a reçu l'email original
            - Mapping recipient → account_id
            - Fallback : compte par défaut si indéterminable

        Args:
            email_original: Email original (from ingestion.emails)

        Returns:
            Account ID pour envoi réponse

        Example:
            >>> email = {'recipient_email': 'antonio.lopez@example.com'}
            >>> account_id = client.determine_account_id(email)
            >>> print(account_id)
            "account_professional"
        """

        # Logique : identifier le compte qui a reçu l'email
        # Mapping recipient → account_id
        recipient = email_original.get("recipient_email") or email_original.get("to")

        # M1 FIX: Utilise constante globale au lieu de mapping local hardcodé
        # Fallback compte par défaut si recipient inconnu
        return DEFAULT_ACCOUNT_MAPPING.get(recipient, "account_professional")


# ============================================================================
# Custom Exceptions
# ============================================================================


class EmailEngineError(Exception):
    """
    Exception personnalisée pour erreurs EmailEngine API

    Raised quand une opération EmailEngine échoue après tous les retries.
    """

    pass
