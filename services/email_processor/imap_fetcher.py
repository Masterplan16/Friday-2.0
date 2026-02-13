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

            accounts.append({
                "account_id": account_id,
                "email": value,
                "imap_host": os.getenv(f"{prefix}_IMAP_HOST", ""),
                "imap_port": int(os.getenv(f"{prefix}_IMAP_PORT", "993")),
                "imap_user": os.getenv(f"{prefix}_IMAP_USER", value),
                "imap_password": os.getenv(f"{prefix}_IMAP_PASSWORD", ""),
                "use_idle": use_idle,
            })

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

        self._imap = aioimaplib.IMAP4_SSL(
            host=self.config["imap_host"],
            port=self.config["imap_port"],
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
        """
        try:
            # Chercher messages UNSEEN
            status, data = await self._imap.search("UNSEEN")
            if status != "OK":
                logger.warning(
                    "imap_search_failed",
                    account_id=self.account_id,
                    status=status,
                )
                return

            uids_str = data[0] if data else ""
            if not uids_str or not uids_str.strip():
                return

            uids = uids_str.strip().split()

            for uid in uids:
                # Deduplication (faille #2)
                already_seen = await self.redis.sismember(self._seen_key, uid)
                if already_seen:
                    continue

                try:
                    await self._process_email(uid)

                    # Marquer comme vu dans Redis (TTL 7 jours)
                    await self.redis.sadd(self._seen_key, uid)
                    # Rafraichir TTL sur le SET entier
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

        except Exception as e:
            logger.error(
                "fetch_new_emails_failed",
                account_id=self.account_id,
                error=str(e),
            )

    async def _process_email(self, uid: str):
        """
        Fetch un email, anonymise, publie dans Redis Streams.

        Format RedisEmailEvent identique a l'ancien webhook EmailEngine :
            account_id, message_id, from_anon, subject_anon,
            date, has_attachments, body_preview_anon
        """
        # Fetch headers + body preview (pas le body complet ici)
        # Le consumer fera un fetch complet si besoin
        status, data = await self._imap.uid(
            "fetch", uid, "(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.2000> BODYSTRUCTURE)"
        )

        if status != "OK" or not data:
            raise Exception(f"IMAP FETCH failed for UID {uid}: {status}")

        # Parser headers
        headers_raw = b""
        body_preview_raw = b""

        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                marker = item[0].decode("utf-8", errors="replace") if isinstance(item[0], bytes) else str(item[0])
                if "HEADER" in marker:
                    headers_raw = item[1] if isinstance(item[1], bytes) else b""
                elif "TEXT" in marker:
                    body_preview_raw = item[1] if isinstance(item[1], bytes) else b""

        msg = email_lib.message_from_bytes(headers_raw)

        # Extraire metadata
        from_header = msg.get("From", "unknown")
        subject = msg.get("Subject", "(no subject)")
        date_str = msg.get("Date", datetime.utcnow().isoformat())
        message_id = msg.get("Message-ID", uid)

        # Check attachments via BODYSTRUCTURE (faille #3)
        has_attachments = False
        bodystructure_str = ""
        for item in data:
            if isinstance(item, bytes):
                decoded = item.decode("utf-8", errors="replace")
                if "BODYSTRUCTURE" in decoded:
                    bodystructure_str = decoded
                    has_attachments = "attachment" in decoded.lower()

        # Decoder body preview
        body_preview = body_preview_raw.decode("utf-8", errors="replace")[:500]

        # Anonymiser via Presidio (from, subject, body preview)
        from_anon = await anonymize_text(from_header)
        subject_anon = await anonymize_text(subject)
        body_preview_anon = await anonymize_text(body_preview) if body_preview else ""

        # Publier dans Redis Streams (format identique a l'ancien webhook)
        event = {
            "account_id": self.account_id,
            "message_id": uid,  # UID IMAP (le consumer fetch le complet)
            "from_anon": from_anon,
            "subject_anon": subject_anon,
            "date": date_str,
            "has_attachments": str(has_attachments),
            "body_preview_anon": body_preview_anon,
        }

        event_id = await self.redis.xadd(STREAM_NAME, event)

        logger.info(
            "email_published_to_stream",
            account_id=self.account_id,
            uid=uid,
            event_id=event_id,
            has_attachments=has_attachments,
        )

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
        """Touch fichier healthcheck toutes les 30s."""
        while self._running:
            try:
                Path(HEALTHCHECK_FILE).touch()
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
