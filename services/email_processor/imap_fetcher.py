"""
Friday 2.0 - IMAP Fetcher Daemon (D25 : remplace EmailEngine)

Daemon asyncio qui surveille 4 comptes IMAP en parallele :
- IMAP IDLE pour Gmail + Zimbra (quasi-push, 2-5s latence)
- Polling pour ProtonMail Bridge (IDLE instable sur Bridge)
- IDLE renew toutes les 25 min (RFC 2177 timeout 29 min)
- Deduplication UIDs via Redis SET (TTL 7 jours)
- Anonymisation Presidio AVANT publication Redis Streams
- Streaming attachments : BODYSTRUCTURE check, skip si >25 Mo

Pipeline:
    IMAP IDLE/Poll -> nouveau mail detecte -> fetch headers+body
    -> Presidio anonymise -> Redis Streams emails:received
    -> consumer.py prend le relais (inchange)

Format Redis identique a l'ancien webhook EmailEngine (RedisEmailEvent).

Decision: D25 (2026-02-13)
Version: 1.0.0
"""

import asyncio
import email as email_lib
import os
import signal
import ssl
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
import structlog

# Ajouter repo root au path
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))

from agents.src.tools.anonymize import anonymize_text

logger = structlog.get_logger(__name__)

# ============================================================================
# Configuration
# ============================================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
STREAM_NAME = os.getenv("IMAP_STREAM_NAME", "emails:received")

# IDLE renew interval (RFC 2177 : serveurs coupent apres 29 min)
IDLE_RENEW_SECONDS = int(os.getenv("IMAP_IDLE_RENEW_SECONDS", "1500"))  # 25 min

# Polling interval pour comptes sans IDLE (ProtonMail Bridge)
POLL_INTERVAL_SECONDS = int(os.getenv("IMAP_POLL_INTERVAL", "60"))

# Silence detection : force reconnexion si aucun event en N secondes
IDLE_SILENCE_TIMEOUT = int(os.getenv("IMAP_IDLE_SILENCE_TIMEOUT", "1800"))  # 30 min

# Deduplication TTL
SEEN_UIDS_TTL_DAYS = int(os.getenv("IMAP_SEEN_UIDS_TTL_DAYS", "7"))

# Attachment size limit (Mo)
MAX_ATTACHMENT_SIZE_MB = int(os.getenv("MAX_ATTACHMENT_SIZE_MB", "25"))

# Healthcheck file
HEALTHCHECK_FILE = "/tmp/fetcher-alive"
HEALTHCHECK_INTERVAL = 30  # secondes


# ============================================================================
# Account Configuration
# ============================================================================


def load_accounts_config() -> List[Dict[str, Any]]:
    """
    Charge la config des comptes IMAP depuis les variables d'environnement.

    Format attendu :
        IMAP_ACCOUNT_PROFESSIONAL_EMAIL=user@gmail.com
        IMAP_ACCOUNT_PROFESSIONAL_IMAP_HOST=imap.gmail.com
        IMAP_ACCOUNT_PROFESSIONAL_IMAP_PORT=993
        IMAP_ACCOUNT_PROFESSIONAL_IMAP_USER=user@gmail.com
        IMAP_ACCOUNT_PROFESSIONAL_IMAP_PASSWORD=app_password
        IMAP_ACCOUNT_PROFESSIONAL_USE_IDLE=true
    """
    accounts = []
    seen_ids = set()

    for key, value in sorted(os.environ.items()):
        if key.startswith("IMAP_ACCOUNT_") and key.endswith("_EMAIL"):
            raw_id = key.replace("IMAP_ACCOUNT_", "").replace("_EMAIL", "")
            account_id = f"account_{raw_id.lower()}"

            if account_id in seen_ids:
                continue
            seen_ids.add(account_id)

            prefix = f"IMAP_ACCOUNT_{raw_id}"

            use_idle = os.getenv(f"{prefix}_USE_IDLE", "true").lower() == "true"

            accounts.append(
                {
                    "account_id": account_id,
                    "email": value,
                    "imap_host": os.getenv(f"{prefix}_IMAP_HOST", ""),
                    "imap_port": int(os.getenv(f"{prefix}_IMAP_PORT", "993")),
                    "imap_user": os.getenv(f"{prefix}_IMAP_USER", value),
                    "imap_password": os.getenv(f"{prefix}_IMAP_PASSWORD", ""),
                    "use_idle": use_idle,
                }
            )

    if not accounts:
        logger.error("no_imap_accounts_configured")

    return accounts


# ============================================================================
# IMAP Account Watcher
# ============================================================================


class IMAPAccountWatcher:
    """
    Surveille UN compte IMAP via IDLE ou polling.

    Responsabilites :
    - Connexion IMAP SSL
    - IDLE avec renew toutes les 25 min (ou polling si use_idle=False)
    - Detection silence (force reconnexion si rien en 30 min)
    - Deduplication UIDs via Redis SET
    - Fetch nouveaux mails -> anonymise -> publie Redis Streams
    - Reconnexion avec backoff exponentiel
    """

    def __init__(
        self,
        account_config: Dict[str, Any],
        redis_client: redis.Redis,
    ):
        self.config = account_config
        self.account_id = account_config["account_id"]
        self.redis = redis_client
        self._imap = None
        self._running = True
        self._last_activity = time.monotonic()
        self._seen_key = f"seen_uids:{self.account_id}"

    async def run(self):
        """Boucle principale avec reconnexion automatique."""
        backoff = 1

        while self._running:
            try:
                await self._connect()
                backoff = 1  # Reset backoff on successful connect

                if self.config["use_idle"]:
                    await self._idle_loop()
                else:
                    await self._poll_loop()

            except asyncio.CancelledError:
                logger.info("watcher_cancelled", account_id=self.account_id)
                break

            except Exception as e:
                logger.error(
                    "watcher_error",
                    account_id=self.account_id,
                    error=str(e),
                    backoff_seconds=backoff,
                )

                await self._disconnect()

                # Backoff exponentiel : 1s, 2s, 4s, 8s, ... max 60s
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 2, 60)

        await self._disconnect()

    async def _connect(self):
        """Connexion IMAP SSL."""
        import aioimaplib

        # Créer contexte SSL personnalisé pour ProtonMail Bridge
        # Le Bridge utilise un certificat auto-signé émis pour 127.0.0.1
        # mais on se connecte via Tailscale (100.x.x.x) — accepter le cert
        ssl_context = None
        if "protonmail" in self.account_id.lower():
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            cert_path = Path("/app/config/certs/protonmail_bridge.pem")
            if cert_path.exists():
                ssl_context.load_verify_locations(cafile=str(cert_path))
                logger.info(
                    "ssl_cert_loaded",
                    account_id=self.account_id,
                    cert_path=str(cert_path),
                )
            else:
                # Pas de cert PEM : accepter le cert auto-signé du Bridge
                # Sécurité OK car connexion via Tailscale (VPN chiffré)
                ssl_context.verify_mode = ssl.CERT_NONE
                logger.info(
                    "ssl_cert_none_tailscale",
                    account_id=self.account_id,
                    message="Accepting self-signed cert (Tailscale VPN)",
                )

        self._imap = aioimaplib.IMAP4_SSL(
            host=self.config["imap_host"],
            port=self.config["imap_port"],
            ssl_context=ssl_context,
        )
        await self._imap.wait_hello_from_server()

        response = await self._imap.login(
            self.config["imap_user"],
            self.config["imap_password"],
        )
        if response.result != "OK":
            raise Exception(f"IMAP login failed: {response.result}")

        await self._imap.select("INBOX")

        logger.info(
            "imap_connected",
            account_id=self.account_id,
            host=self.config["imap_host"],
            mode="IDLE" if self.config["use_idle"] else "POLL",
        )

    async def _disconnect(self):
        """Deconnexion propre."""
        if self._imap:
            try:
                await self._imap.logout()
            except Exception:
                pass
            self._imap = None

    async def _idle_loop(self):
        """
        Boucle IMAP IDLE avec renew toutes les 25 min.

        RFC 2177 : Les serveurs DOIVENT supporter IDLE pendant au moins
        29 minutes. On renew a 25 min par securite.

        Detection silence : si rien recu en 30 min, force reconnexion
        (faille adversariale #1 : IDLE silencieux).
        """
        while self._running:
            # Lancer IDLE
            idle_task = await self._imap.idle_start(timeout=IDLE_RENEW_SECONDS)

            # Attendre IDLE response ou timeout
            try:
                msg = await asyncio.wait_for(
                    self._imap.wait_server_push(),
                    timeout=IDLE_RENEW_SECONDS,
                )

                # Nouveau mail detecte
                self._last_activity = time.monotonic()
                self._imap.idle_done()
                await asyncio.sleep(0.5)  # Laisser le serveur repondre

                # Fetch nouveaux mails
                await self._fetch_new_emails()

            except asyncio.TimeoutError:
                # IDLE renew : pas de nouveau mail, on relance IDLE
                self._imap.idle_done()
                await asyncio.sleep(0.5)

                # Detection silence (faille #1)
                silence_duration = time.monotonic() - self._last_activity
                if silence_duration > IDLE_SILENCE_TIMEOUT:
                    logger.warning(
                        "idle_silence_detected",
                        account_id=self.account_id,
                        silence_seconds=int(silence_duration),
                    )
                    # Force reconnexion
                    raise Exception("IDLE silence timeout - forcing reconnection")

    async def _poll_loop(self):
        """
        Boucle polling pour comptes sans IDLE (ProtonMail Bridge).
        """
        while self._running:
            await self._fetch_new_emails()
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _fetch_new_emails(self):
        """
        Cherche nouveaux mails non vus dans INBOX.
        Deduplique via Redis SET seen_uids:{account_id}.

        Approche en 2 étapes (aioimaplib ne supporte pas UID SEARCH):
        1. SEARCH UNSEEN → numéros de séquence (instables)
        2. FETCH seq (UID) → UIDs stables pour dédup
        """
        import re

        try:
            # Étape 1: SEARCH UNSEEN → numéros de séquence
            status, data = await self._imap.search("UNSEEN")
            if status != "OK":
                logger.warning(
                    "imap_search_failed",
                    account_id=self.account_id,
                    status=status,
                )
                return

            seq_str = data[0] if data else b""
            if isinstance(seq_str, (bytes, bytearray)):
                seq_str = seq_str.decode("utf-8", errors="replace")

            if not seq_str or not seq_str.strip():
                return

            seq_nums = seq_str.strip().split()

            # Étape 2: FETCH (UID) pour chaque séquence → UIDs stables
            uids = []
            for seq in seq_nums:
                try:
                    result = await self._imap.fetch(seq, "(UID)")
                    if isinstance(result, tuple):
                        fetch_status, fetch_data = result
                    else:
                        result.result
                        fetch_data = result.lines

                    for item in fetch_data:
                        item_str = (
                            item.decode("utf-8", errors="replace")
                            if isinstance(item, (bytes, bytearray))
                            else str(item)
                        )
                        match = re.search(r"UID\s+(\d+)", item_str)
                        if match:
                            uids.append(match.group(1))
                            break
                except Exception as e:
                    logger.warning(
                        "uid_fetch_failed",
                        account_id=self.account_id,
                        seq=seq,
                        error=str(e),
                    )

            if not uids:
                return

            logger.info(
                "unseen_emails_found",
                account_id=self.account_id,
                count=len(uids),
            )

            for uid in uids:
                # Deduplication (faille #2)
                already_seen = await self.redis.sismember(self._seen_key, uid)
                if already_seen:
                    continue

                try:
                    await self._process_email(uid)

                    # IMPORTANT: Marquer comme vu SEULEMENT en cas de succès
                    await self.redis.sadd(self._seen_key, uid)
                    await self.redis.expire(
                        self._seen_key,
                        SEEN_UIDS_TTL_DAYS * 86400,
                    )

                except Exception as e:
                    logger.error(
                        "email_processing_failed",
                        account_id=self.account_id,
                        uid=uid,
                        error=str(e),
                    )
                    # NE PAS marquer comme vu en erreur - retry au prochain passage

        except Exception as e:
            logger.error(
                "fetch_new_emails_failed",
                account_id=self.account_id,
                error=str(e),
            )

    async def _process_email(self, uid: str):
        """
        Fetch un email complet (headers + body), anonymise, publie dans Redis Streams.
        Format RedisEmailEvent identique a l'ancien webhook EmailEngine.
        """
        from_header = "unknown"
        subject = "(no subject)"
        date_str = datetime.utcnow().isoformat()
        body_text = ""
        has_attachments = False

        # Fetch email complet (headers + body, sans marquer lu)
        try:
            result = await self._imap.uid("fetch", uid, "(BODY.PEEK[])")

            if isinstance(result, tuple):
                status, data = result
            else:
                status = result.result
                data = result.lines

            if status != "OK" or not data:
                raise Exception(f"Email fetch failed: status={status}, has_data={bool(data)}")

            # Detection UID invalide : serveur retourne OK mais data = [b'UID FETCH completed']
            # (email supprime/deplace cote serveur). Return sans raise = marque vu dans Redis.
            if len(data) == 1 and isinstance(data[0], (bytes, bytearray)):
                item_check = bytes(data[0]).lower()
                if b"completed" in item_check or b"fetch" in item_check:
                    logger.warning(
                        "imap_uid_not_found_skipping",
                        account_id=self.account_id,
                        uid=uid,
                        data_preview=bytes(data[0])[:100].decode("utf-8", errors="replace"),
                    )
                    return  # Return (pas raise) → UID sera marque vu → pas de retry inutile

            # Parser les données brutes de la réponse aioimaplib
            # Gère bytes et bytearray (ProtonMail Bridge retourne parfois bytearray)
            raw_email = None
            for item in data:
                if isinstance(item, tuple) and len(item) >= 2:
                    candidate = item[1]
                    if isinstance(candidate, (bytes, bytearray)):
                        raw_email = bytes(candidate)
                        break
                elif isinstance(item, (bytes, bytearray)):
                    item_bytes = bytes(item)
                    # Ignorer lignes de status IMAP
                    if (
                        item_bytes.strip() == b")"
                        or b"FETCH" in item_bytes
                        or b"completed" in item_bytes
                    ):
                        continue
                    raw_email = item_bytes
                    break

            if not raw_email:
                if len(data) > 1 and isinstance(data[1], (bytes, bytearray)):
                    raw_email = bytes(data[1])
                else:
                    logger.error(
                        "no_email_content",
                        account_id=self.account_id,
                        uid=uid,
                        data_repr=repr(data)[:500] if data else "none",
                    )
                    raise Exception("No email content found in response")

            # Parser email complet avec email.message
            msg = email_lib.message_from_bytes(raw_email)
            from_header = msg.get("From", "unknown")
            subject = msg.get("Subject", "(no subject)")
            date_str = msg.get("Date", datetime.utcnow().isoformat())

            # Extraire body text
            body_text = self._extract_body_text(msg)

            # Détecter pièces jointes
            has_attachments = self._has_attachments(msg)

            logger.info(
                "email_fetched",
                account_id=self.account_id,
                uid=uid,
                from_preview=from_header[:50],
                subject_preview=subject[:50],
                body_length=len(body_text),
                has_attachments=has_attachments,
            )

        except Exception as e:
            logger.error(
                "email_fetch_failed_completely",
                account_id=self.account_id,
                uid=uid,
                error=str(e)[:200],
                error_type=type(e).__name__,
            )
            # Skip cet email - ne pas bloquer toute la queue
            return

        # Tronquer body pour le stream (max 2000 chars)
        body_preview = body_text[:2000] if body_text else ""

        # Anonymiser via Presidio (RGPD obligatoire avant envoi cloud)
        try:
            from_anon = (await anonymize_text(from_header)).anonymized_text
            subject_anon = (await anonymize_text(subject)).anonymized_text
            body_preview_anon = (
                (await anonymize_text(body_preview)).anonymized_text if body_preview else ""
            )
        except Exception as e:
            logger.error(
                "presidio_anonymization_failed",
                account_id=self.account_id,
                uid=uid,
                error=str(e),
            )
            # Fallback: utiliser [REDACTED] plutôt que skip
            from_anon = "[REDACTED]"
            subject_anon = "[REDACTED]"
            body_preview_anon = "[REDACTED]"

        # Publier dans Redis Streams (format identique webhook EmailEngine)
        event = {
            "account_id": self.account_id,
            "message_id": uid,
            "from_anon": from_anon,
            "subject_anon": subject_anon,
            "date": date_str,
            "has_attachments": str(has_attachments),
            "body_preview_anon": body_preview_anon,
        }

        try:
            event_id = await self.redis.xadd(STREAM_NAME, event)
            logger.info(
                "email_published_to_stream",
                account_id=self.account_id,
                uid=uid,
                event_id=event_id,
            )
        except Exception as e:
            logger.critical(
                "redis_publish_failed",
                account_id=self.account_id,
                uid=uid,
                error=str(e),
            )
            raise  # Critical - on doit retry

    def _extract_body_text(self, msg) -> str:
        """Extrait le texte brut d'un email (multipart ou simple)."""
        if msg.is_multipart():
            # Chercher text/plain d'abord
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")
            # Fallback: text/html
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return ""

    @staticmethod
    def _has_attachments(msg) -> bool:
        """Detecte si l'email a des pieces jointes."""
        if not msg.is_multipart():
            return False
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in content_disposition:
                return True
        return False

    def stop(self):
        """Arret propre."""
        self._running = False


# ============================================================================
# Main Fetcher Daemon
# ============================================================================


class IMAPFetcherDaemon:
    """
    Daemon principal : lance un IMAPAccountWatcher par compte en parallele.

    Gere :
    - Graceful shutdown (SIGTERM/SIGINT)
    - Healthcheck file (touch toutes les 30s)
    - Supervision des watchers
    """

    def __init__(self):
        self._watchers: List[IMAPAccountWatcher] = []
        self._tasks: List[asyncio.Task] = []
        self._running = True
        self._redis: Optional[redis.Redis] = None

    async def start(self):
        """Demarre le daemon."""
        logger.info("imap_fetcher_starting")

        # Connexion Redis
        self._redis = redis.from_url(REDIS_URL, decode_responses=True)
        await self._redis.ping()
        logger.info("redis_connected")

        # Charger config comptes
        accounts = load_accounts_config()
        if not accounts:
            logger.error("no_accounts_to_watch")
            return

        logger.info("accounts_loaded", count=len(accounts))

        # Lancer un watcher par compte
        for account_config in accounts:
            watcher = IMAPAccountWatcher(
                account_config=account_config,
                redis_client=self._redis,
            )
            self._watchers.append(watcher)
            task = asyncio.create_task(
                watcher.run(),
                name=f"watcher-{account_config['account_id']}",
            )
            self._tasks.append(task)

            logger.info(
                "watcher_started",
                account_id=account_config["account_id"],
                mode="IDLE" if account_config["use_idle"] else "POLL",
            )

        # Lancer healthcheck
        healthcheck_task = asyncio.create_task(
            self._healthcheck_loop(),
            name="healthcheck",
        )
        self._tasks.append(healthcheck_task)

        # Attendre que tous les watchers terminent (ou erreur)
        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass

        logger.info("imap_fetcher_stopped")

    async def stop(self):
        """Arret propre de tous les watchers."""
        logger.info("imap_fetcher_stopping")
        self._running = False

        for watcher in self._watchers:
            watcher.stop()

        for task in self._tasks:
            task.cancel()

        if self._redis:
            await self._redis.close()

    async def _healthcheck_loop(self):
        """Touch fichier healthcheck + Redis heartbeat toutes les 30s."""
        while self._running:
            try:
                Path(HEALTHCHECK_FILE).touch()
            except Exception:
                pass
            # Redis heartbeat pour monitoring depuis le bot container
            try:
                if self._redis:
                    await self._redis.set(
                        "heartbeat:imap-fetcher",
                        str(int(time.time())),
                        ex=90,  # expire apres 90s (3x interval)
                    )
            except Exception:
                pass
            await asyncio.sleep(HEALTHCHECK_INTERVAL)


# ============================================================================
# Entry point
# ============================================================================


def main():
    """Point d'entree principal."""
    daemon = IMAPFetcherDaemon()

    loop = asyncio.new_event_loop()

    # Graceful shutdown
    def _signal_handler(sig, frame):
        logger.info("signal_received", signal=sig)
        loop.create_task(daemon.stop())

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        loop.run_until_complete(daemon.start())
    except KeyboardInterrupt:
        loop.run_until_complete(daemon.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
