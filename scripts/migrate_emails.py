#!/usr/bin/env python3
"""
Friday 2.0 - Migration progressive emails via IMAP direct (D25 rewrite).

Remplace l'ancien script EmailEngine REST (deprecated D25).
Pipeline complet : IMAP fetch → anonymize → classify (Haiku) → store DB.

Usage (dans le container email-processor) :
    # Sample check (10 emails)
    python /app/scripts/migrate_emails.py --since 2026-01-01 --limit 10

    # Migration 2026 complete
    python /app/scripts/migrate_emails.py --since 2026-01-01 --until 2027-01-01

    # Un seul compte
    python /app/scripts/migrate_emails.py --since 2026-01-01 --account account_gmail1

    # Reprendre apres interruption
    python /app/scripts/migrate_emails.py --since 2026-01-01 --resume

Via docker exec :
    docker exec friday-email-processor python /app/scripts/migrate_emails.py --since 2026-01-01 --limit 10
"""

import argparse
import asyncio
import email as email_lib
import json
import os
import re
import signal
import ssl
import sys
import time
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional

import aioimaplib
import asyncpg
import structlog
from anthropic import AsyncAnthropic

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents" / "src"))

from agents.src.tools.anonymize import anonymize_text
from agents.src.agents.email.sender_filter import check_sender_filter
from agents.src.agents.email.prompts import build_classification_prompt
from agents.src.models.email_classification import EmailClassification

logger = structlog.get_logger("migrate_emails")

# ============================================================================
# Configuration
# ============================================================================

DATABASE_URL = os.getenv("DATABASE_URL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = "claude-haiku-4-5-20251001"

# Rate limiting
MAX_CONCURRENT = int(os.getenv("MIGRATE_CONCURRENCY", "5"))
CHECKPOINT_INTERVAL = 50
LOG_INTERVAL = 10

# IMAP months for SEARCH command
IMAP_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Graceful shutdown
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True
    logger.info("shutdown_requested", signal=signum)


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ============================================================================
# Checkpoint
# ============================================================================


class Checkpoint:
    """Sauvegarde progression pour reprise apres interruption."""

    def __init__(self, tag: str):
        self.filepath = Path(f"/tmp/migrate_{tag}.json")
        self.processed_uids: dict[str, list[str]] = {}  # account_id -> [uid, ...]
        self.stats = {"migrated": 0, "skipped": 0, "blacklisted": 0, "failed": 0}

    def load(self) -> bool:
        if self.filepath.exists():
            with open(self.filepath) as f:
                data = json.load(f)
            self.processed_uids = data.get("processed_uids", {})
            self.stats = data.get("stats", self.stats)
            logger.info(
                "checkpoint_loaded", migrated=self.stats["migrated"], skipped=self.stats["skipped"]
            )
            return True
        return False

    def save(self):
        with open(self.filepath, "w") as f:
            json.dump(
                {
                    "processed_uids": self.processed_uids,
                    "stats": self.stats,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                f,
            )

    def is_done(self, account_id: str, uid: str) -> bool:
        return uid in self.processed_uids.get(account_id, [])

    def mark_done(self, account_id: str, uid: str):
        self.processed_uids.setdefault(account_id, []).append(uid)


# ============================================================================
# IMAP helpers
# ============================================================================


def load_accounts() -> list[dict[str, Any]]:
    """Charge config IMAP depuis env vars (meme format que imap_fetcher)."""
    accounts = []
    seen = set()
    for key, value in sorted(os.environ.items()):
        if key.startswith("IMAP_ACCOUNT_") and key.endswith("_EMAIL"):
            raw_id = key.replace("IMAP_ACCOUNT_", "").replace("_EMAIL", "")
            account_id = f"account_{raw_id.lower()}"
            if account_id in seen:
                continue
            seen.add(account_id)
            prefix = f"IMAP_ACCOUNT_{raw_id}"
            accounts.append(
                {
                    "account_id": account_id,
                    "email": value,
                    "imap_host": os.getenv(f"{prefix}_IMAP_HOST", ""),
                    "imap_port": int(os.getenv(f"{prefix}_IMAP_PORT", "993")),
                    "imap_user": os.getenv(f"{prefix}_IMAP_USER", value),
                    "imap_password": os.getenv(f"{prefix}_IMAP_PASSWORD", ""),
                }
            )
    return accounts


def make_ssl_context(account_id: str) -> ssl.SSLContext:
    """Cree SSL context (gere ProtonMail Bridge cert custom)."""
    ctx = ssl.create_default_context()
    if "protonmail" in account_id:
        cert_path = os.getenv("PROTONMAIL_CERT_PATH", "/app/certs/protonmail-bridge.pem")
        if os.path.exists(cert_path):
            ctx.load_verify_locations(cert_path)
        else:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def imap_connect(account: dict) -> aioimaplib.IMAP4_SSL:
    """Connexion IMAP SSL."""
    ssl_ctx = make_ssl_context(account["account_id"])
    imap = aioimaplib.IMAP4_SSL(
        host=account["imap_host"],
        port=account["imap_port"],
        ssl_context=ssl_ctx,
    )
    await imap.wait_hello_from_server()
    await imap.login(account["imap_user"], account["imap_password"])
    # SELECT (pas EXAMINE) pour pouvoir marquer lu si besoin
    await imap.select("INBOX")
    return imap


def format_imap_date(date_str: str) -> str:
    """Convertit YYYY-MM-DD en DD-Mon-YYYY (format IMAP SEARCH)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{dt.day:02d}-{IMAP_MONTHS[dt.month - 1]}-{dt.year}"


async def imap_search_date_range(
    imap: aioimaplib.IMAP4_SSL,
    since: Optional[str],
    until: Optional[str],
) -> list[str]:
    """SEARCH par plage de dates, retourne liste de sequence numbers."""
    criteria_parts = []
    if since:
        criteria_parts.append(f"SINCE {format_imap_date(since)}")
    if until:
        criteria_parts.append(f"BEFORE {format_imap_date(until)}")

    criteria = " ".join(criteria_parts) if criteria_parts else "ALL"

    result = await imap.search(criteria)
    status = result.result if hasattr(result, "result") else result[0]
    lines = result.lines if hasattr(result, "lines") else result[1]

    if status != "OK":
        return []

    seq_nums = []
    for line in lines:
        if isinstance(line, (bytes, bytearray)):
            line = line.decode("utf-8", errors="replace")
        if isinstance(line, str):
            for part in line.split():
                if part.isdigit():
                    seq_nums.append(part)

    return seq_nums


async def imap_fetch_email(imap: aioimaplib.IMAP4_SSL, seq_num: str) -> Optional[dict]:
    """Fetch un email complet par sequence number. Retourne dict (incl. uid) ou None."""
    result = await imap.fetch(seq_num, "(UID BODY.PEEK[] INTERNALDATE)")
    status = result.result if hasattr(result, "result") else result[0]
    data = result.lines if hasattr(result, "lines") else result[1]

    if status != "OK" or not data:
        return None

    # aioimaplib retourne une liste plate :
    #   lines[0] = bytes header: b'83481 FETCH (UID 100142 INTERNALDATE "..." BODY[] {31635})'
    #   lines[1] = bytearray: raw email bytes
    #   lines[2] = b')'
    #   lines[3] = b'Success'

    # Extraire UID + INTERNALDATE depuis le header (lines[0])
    uid = None
    internal_date_str = None
    raw_email = None

    if len(data) >= 2:
        # Header line
        hdr_bytes = data[0]
        if isinstance(hdr_bytes, (bytes, bytearray)):
            hdr = bytes(hdr_bytes).decode("utf-8", errors="replace")
            uid_match = re.search(r"UID (\d+)", hdr)
            if uid_match:
                uid = uid_match.group(1)
            date_match = re.search(r'INTERNALDATE "([^"]+)"', hdr)
            if date_match:
                internal_date_str = date_match.group(1)

        # Raw email body (lines[1])
        body_bytes = data[1]
        if isinstance(body_bytes, (bytes, bytearray)) and len(body_bytes) > 100:
            raw_email = bytes(body_bytes)

    if not raw_email or not uid:
        return None

    # Parser email
    msg = email_lib.message_from_bytes(raw_email)

    from_header = msg.get("From", "unknown")
    to_header = msg.get("To", "")
    subject = msg.get("Subject", "(no subject)")
    date_header = msg.get("Date", "")

    # Decoder subject/from (MIME encoded)
    subject = _decode_header(subject)
    from_header = _decode_header(from_header)

    # Extraire body text
    body_text = _extract_body_text(msg)

    # Detecter PJ
    has_attachments = _has_attachments(msg)

    # Parser date
    received_at = None
    if internal_date_str:
        try:
            received_at = parsedate_to_datetime(internal_date_str)
        except Exception:
            pass
    if not received_at and date_header:
        try:
            received_at = parsedate_to_datetime(date_header)
        except Exception:
            pass
    if not received_at:
        received_at = datetime.now(timezone.utc)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    # Extraire email sender pour filtrage
    from_email = ""
    addr_match = re.search(r"<([^>]+)>", from_header)
    if addr_match:
        from_email = addr_match.group(1)
    elif "@" in from_header:
        from_email = from_header.strip()

    return {
        "uid": uid,  # Extrait du FETCH response header
        "from_raw": from_header,
        "from_email": from_email,
        "to_raw": to_header,
        "subject": subject,
        "body": body_text[:5000],
        "has_attachments": has_attachments,
        "received_at": received_at,
    }


def _decode_header(value: str) -> str:
    """Decode MIME encoded header."""
    try:
        parts = decode_header(value)
        return "".join(
            part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else part
            for part, enc in parts
        )
    except Exception:
        return value


def _extract_body_text(msg) -> str:
    """Extrait le texte brut d'un email."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
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


def _has_attachments(msg) -> bool:
    """Detecte si l'email a des pieces jointes."""
    if not msg.is_multipart():
        return False
    for part in msg.walk():
        if "attachment" in str(part.get("Content-Disposition", "")):
            return True
    return False


# ============================================================================
# Pipeline (anonymize + classify + store)
# ============================================================================


async def anonymize_email(email_data: dict) -> dict:
    """Anonymise from, subject, body via Presidio."""
    try:
        from_result = await anonymize_text(email_data["from_raw"])
        from_anon = from_result.anonymized_text

        subject_result = await anonymize_text(email_data["subject"])
        subject_anon = subject_result.anonymized_text

        body_result = await anonymize_text(email_data["body"]) if email_data["body"] else None
        body_anon = body_result.anonymized_text if body_result else ""
    except Exception as e:
        logger.warning("anonymization_failed", uid=email_data["uid"], error=str(e))
        from_anon = "[REDACTED]"
        subject_anon = "[REDACTED]"
        body_anon = "[REDACTED]"

    return {
        "from_anon": from_anon,
        "subject_anon": subject_anon,
        "body_anon": body_anon,
    }


async def classify_email_haiku(
    client: AsyncAnthropic,
    email_text: str,
) -> tuple[str, float]:
    """Classification via Haiku 3.5. Retourne (category, confidence)."""
    system_prompt, user_prompt = build_classification_prompt(email_text=email_text)

    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=300,
            temperature=0.1,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        text = response.content[0].text.strip()
        # Strip markdown fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        classification = EmailClassification.model_validate_json(text)
        return classification.category, classification.confidence

    except Exception as e:
        logger.warning(
            "classification_failed", error=str(e), response=text[:200] if "text" in dir() else "N/A"
        )
        return "inconnu", 0.0


async def store_email(
    db_pool: asyncpg.Pool,
    account_id: str,
    uid: str,
    email_data: dict,
    anon_data: dict,
    category: str,
    confidence: float,
) -> Optional[str]:
    """Stocke un email dans ingestion.emails. Retourne UUID ou None si doublon."""
    try:
        email_id = await db_pool.fetchval(
            """
            INSERT INTO ingestion.emails
            (account_id, message_id, from_anon, to_anon, subject_anon, body_anon,
             category, confidence, has_attachments, received_at, processed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
            ON CONFLICT (account_id, message_id) DO NOTHING
            RETURNING id
            """,
            account_id,
            uid,
            anon_data["from_anon"],
            email_data.get("to_raw", ""),
            anon_data["subject_anon"],
            anon_data["body_anon"],
            category,
            confidence,
            email_data["has_attachments"],
            email_data["received_at"],
        )
        return str(email_id) if email_id else None
    except Exception as e:
        logger.error("store_failed", uid=uid, error=str(e))
        return None


# ============================================================================
# Main migration logic
# ============================================================================


async def process_one_email(
    imap: aioimaplib.IMAP4_SSL,
    anthropic_client: AsyncAnthropic,
    db_pool: asyncpg.Pool,
    account_id: str,
    seq_num: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, Optional[str]]:
    """
    Traite un email : fetch → anonymize → filter → classify → store.
    Retourne: (status, uid) ou status = 'migrated'|'blacklisted'|'skipped'|'failed'.
    """
    async with semaphore:
        try:
            # 1. Fetch from IMAP (includes UID extraction)
            email_data = await imap_fetch_email(imap, seq_num)
            if not email_data:
                return "failed", None

            uid = email_data["uid"]

            # 2. Check dedup DB
            exists = await db_pool.fetchval(
                "SELECT id FROM ingestion.emails WHERE account_id = $1 AND message_id = $2 LIMIT 1",
                account_id,
                uid,
            )
            if exists:
                return "skipped", uid

            # 3. Check sender filter (blacklist)
            from_email = email_data.get("from_email", "")
            domain = from_email.split("@")[1].lower() if "@" in from_email else None

            filter_result = None
            if from_email or domain:
                filter_result = await check_sender_filter(
                    email_id=uid,
                    sender_email=from_email or None,
                    sender_domain=domain,
                    db_pool=db_pool,
                )

            if filter_result and filter_result.get("filter_type") == "blacklist":
                # Store as blacklisted (same as consumer)
                anon_data = await anonymize_email(email_data)
                await store_email(
                    db_pool,
                    account_id,
                    uid,
                    email_data,
                    anon_data,
                    category="blacklisted",
                    confidence=1.0,
                )
                return "blacklisted", uid

            # 4. Anonymize
            anon_data = await anonymize_email(email_data)

            # 5. Classify with Haiku
            email_text = (
                f"De: {anon_data['from_anon']}\n"
                f"Sujet: {anon_data['subject_anon']}\n\n"
                f"{anon_data['body_anon']}"
            )
            category, confidence = await classify_email_haiku(anthropic_client, email_text)

            # 6. Store in DB
            email_id = await store_email(
                db_pool,
                account_id,
                uid,
                email_data,
                anon_data,
                category=category,
                confidence=confidence,
            )

            if email_id:
                return "migrated", uid
            else:
                return "skipped", uid  # ON CONFLICT = doublon

        except Exception as e:
            logger.error(
                "process_email_failed",
                account_id=account_id,
                seq_num=seq_num,
                error=str(e),
                error_type=type(e).__name__,
            )
            return "failed", None


async def migrate_account(
    account: dict,
    anthropic_client: AsyncAnthropic,
    db_pool: asyncpg.Pool,
    checkpoint: Checkpoint,
    since: Optional[str],
    until: Optional[str],
    limit: Optional[int],
) -> dict:
    """Migre les emails d'un compte IMAP. Retourne stats."""
    account_id = account["account_id"]
    stats = {"migrated": 0, "skipped": 0, "blacklisted": 0, "failed": 0}

    try:
        imap = await imap_connect(account)
        logger.info("imap_connected", account_id=account_id, host=account["imap_host"])
    except Exception as e:
        logger.error("imap_connect_failed", account_id=account_id, error=str(e))
        return stats

    try:
        # Search by date range (returns sequence numbers)
        seq_nums = await imap_search_date_range(imap, since, until)
        logger.info("search_results", account_id=account_id, seq_nums_found=len(seq_nums))

        if not seq_nums:
            return stats

        # Apply limit
        if limit:
            remaining = limit - checkpoint.stats["migrated"] - checkpoint.stats["blacklisted"]
            if remaining <= 0:
                return stats
            seq_nums = seq_nums[: remaining + checkpoint.stats["skipped"] + 50]  # Marge pour skips

        logger.info("processing_start", account_id=account_id, seq_nums=len(seq_nums))

        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        start_time = time.time()
        migrated_this_run = 0

        for i, seq_num in enumerate(seq_nums):
            if _shutdown:
                logger.info("shutdown_saving", account_id=account_id)
                checkpoint.save()
                break

            # Limite atteinte ?
            if limit and (migrated_this_run + stats["blacklisted"]) >= limit:
                break

            result, uid = await process_one_email(
                imap,
                anthropic_client,
                db_pool,
                account_id,
                seq_num,
                semaphore,
            )

            stats[result] += 1
            checkpoint.stats[result] += 1
            if uid:
                checkpoint.mark_done(account_id, uid)
            if result == "migrated":
                migrated_this_run += 1

            # Log progress
            processed = i + 1
            if processed % LOG_INTERVAL == 0:
                elapsed = time.time() - start_time
                rate = processed / (elapsed / 60) if elapsed > 0 else 0
                logger.info(
                    "progress",
                    account_id=account_id,
                    processed=processed,
                    total=len(seq_nums),
                    migrated=stats["migrated"],
                    blacklisted=stats["blacklisted"],
                    skipped=stats["skipped"],
                    failed=stats["failed"],
                    rate_per_min=round(rate, 1),
                )

            # Checkpoint periodique
            if processed % CHECKPOINT_INTERVAL == 0:
                checkpoint.save()

    except Exception as e:
        logger.error("migration_error", account_id=account_id, error=str(e))
    finally:
        try:
            await imap.logout()
        except Exception:
            pass

    return stats


async def main_migrate(args: argparse.Namespace):
    """Boucle principale de migration."""
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set")
        sys.exit(1)
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not set")
        sys.exit(1)

    # Checkpoint
    tag = f"{args.since or 'start'}_{args.until or 'now'}"
    checkpoint = Checkpoint(tag)
    if args.resume:
        checkpoint.load()

    # Load accounts
    accounts = load_accounts()
    if args.account:
        accounts = [a for a in accounts if a["account_id"] == args.account]

    if not accounts:
        logger.error("no_accounts_found")
        sys.exit(1)

    logger.info(
        "migration_starting",
        accounts=len(accounts),
        since=args.since,
        until=args.until,
        limit=args.limit,
        model=MODEL,
        concurrency=MAX_CONCURRENT,
    )

    # Connexions
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    start_time = time.time()
    total_stats = {"migrated": 0, "skipped": 0, "blacklisted": 0, "failed": 0}

    # Traiter chaque compte sequentiellement
    for account in accounts:
        if _shutdown:
            break

        stats = await migrate_account(
            account,
            anthropic_client,
            db_pool,
            checkpoint,
            since=args.since,
            until=args.until,
            limit=args.limit,
        )

        for k in total_stats:
            total_stats[k] += stats[k]

    # Sauvegarder checkpoint final
    checkpoint.save()
    elapsed = time.time() - start_time

    await db_pool.close()

    # Rapport final
    print(f"\n{'=' * 50}")
    print(f"Migration terminee")
    print(f"{'=' * 50}")
    print(f"Migres      : {total_stats['migrated']}")
    print(f"Blacklistes : {total_stats['blacklisted']}")
    print(f"Ignores     : {total_stats['skipped']}")
    print(f"Echecs      : {total_stats['failed']}")
    print(f"Duree       : {elapsed / 60:.1f} min")
    if total_stats["migrated"] > 0 and elapsed > 0:
        print(f"Rate        : {total_stats['migrated'] / (elapsed / 60):.1f} emails/min")
    print(f"Modele      : {MODEL}")
    print(f"Checkpoint  : {checkpoint.filepath}")


def main():
    parser = argparse.ArgumentParser(description="Migration emails via IMAP direct")
    parser.add_argument("--since", type=str, help="Date debut YYYY-MM-DD (inclus)")
    parser.add_argument("--until", type=str, help="Date fin YYYY-MM-DD (exclus)")
    parser.add_argument("--limit", type=int, help="Limite nombre emails migres")
    parser.add_argument("--account", type=str, help="Filtrer par account_id")
    parser.add_argument("--resume", action="store_true", help="Reprendre depuis checkpoint")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=MAX_CONCURRENT,
        help=f"Concurrence max appels API (defaut: {MAX_CONCURRENT})",
    )

    args = parser.parse_args()

    if not args.since and not args.until:
        print("ERREUR: --since et/ou --until requis")
        sys.exit(1)

    asyncio.run(main_migrate(args))


if __name__ == "__main__":
    main()
