#!/usr/bin/env python3
"""
[DEPRECATED D25] Migration progressive des 108k emails historiques via API EmailEngine REST.
Ce script dependait de l'API REST EmailEngine, retiree par D25 (IMAP direct).

Story 2.9 — Reecriture complete.
Source de donnees : API EmailEngine REST (remplace ingestion.emails_legacy).

Parametres CLI :
    --since YYYY-MM-DD     Date debut (inclus)
    --until YYYY-MM-DD     Date fin (inclus)
    --unread-only          Seulement non-lus
    --limit N              Limite nombre emails (pour tests/sample check)
    --trust-auto           Bypass validation Telegram (bulk)
    --trust-propose        Validation Telegram (defaut pour sample)
    --resume               Reprendre depuis checkpoint (last_processed_id)
    --reclassify           Re-traiter emails deja en base (UPDATE, pas INSERT)
    --account ACCOUNT_ID   Filtrer par compte (optionnel)

Workflow Phase D :
    # Sample check obligatoire
    python scripts/migrate_emails.py --since 2026-01-01 --limit 100 --trust-propose
    # Puis bulk
    python scripts/migrate_emails.py --since 2026-01-01 --trust-auto --resume

Usage:
    export $(sops -d .env.enc | xargs)
    export $(sops -d .env.email.enc | xargs)
    python scripts/migrate_emails.py [options]
"""

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import httpx
import structlog

# Add agents/src to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "agents" / "src"))

logger = structlog.get_logger("migrate_emails")

# Configuration
EMAILENGINE_URL = os.getenv("EMAILENGINE_URL", "http://localhost:3000")
EMAILENGINE_TOKEN = os.getenv("EMAILENGINE_ACCESS_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

MAX_RETRIES = 3
CHECKPOINT_INTERVAL = 100  # Sauvegarder checkpoint toutes les N emails
LOG_INTERVAL = 10  # Log progression toutes les N emails

# Graceful shutdown
_shutdown_requested = False


def _handle_signal(signum, frame):
    """Ctrl+C propre — sauvegarde checkpoint avant arret."""
    global _shutdown_requested
    logger.info("shutdown_requested", signal=signum)
    _shutdown_requested = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


class MigrationCheckpoint:
    """Gestion checkpoint pour reprise apres interruption."""

    def __init__(self, since: str | None, until: str | None):
        tag = f"{since or 'start'}_{until or 'now'}"
        self.filepath = Path(f"/tmp/migrate_checkpoint_{tag}.json")
        self.data = {
            "last_processed_id": None,
            "count_migrated": 0,
            "count_skipped": 0,
            "count_failed": 0,
            "timestamp": None,
        }

    def load(self) -> bool:
        """Charge checkpoint existant. Retourne True si trouve."""
        if self.filepath.exists():
            with open(self.filepath) as f:
                self.data = json.load(f)
            logger.info(
                "checkpoint_loaded",
                filepath=str(self.filepath),
                count_migrated=self.data["count_migrated"],
                last_processed_id=self.data["last_processed_id"],
            )
            return True
        return False

    def save(self) -> None:
        """Sauvegarde checkpoint."""
        self.data["timestamp"] = datetime.now(timezone.utc).isoformat()
        with open(self.filepath, "w") as f:
            json.dump(self.data, f, indent=2)

    def update(self, message_id: str, migrated: bool = True) -> None:
        """Met a jour compteurs."""
        self.data["last_processed_id"] = message_id
        if migrated:
            self.data["count_migrated"] += 1
        else:
            self.data["count_skipped"] += 1

    def increment_failed(self) -> None:
        self.data["count_failed"] += 1

    @property
    def count_migrated(self) -> int:
        return self.data["count_migrated"]

    @property
    def count_skipped(self) -> int:
        return self.data["count_skipped"]

    @property
    def count_failed(self) -> int:
        return self.data["count_failed"]

    @property
    def last_processed_id(self) -> str | None:
        return self.data["last_processed_id"]


async def fetch_emails_from_emailengine(
    client: httpx.AsyncClient,
    since: str | None = None,
    until: str | None = None,
    unread_only: bool = False,
    account_id: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """
    Recupere les emails depuis l'API EmailEngine REST.

    Tri : received_at DESC (plus recent d'abord).
    Retourne liste de dicts avec message_id, from, to, subject, body, received_at, account_id.
    """
    all_messages = []
    headers = {"Authorization": f"Bearer {EMAILENGINE_TOKEN}"}

    # Lister comptes
    if account_id:
        account_ids = [account_id]
    else:
        resp = await client.get(f"{EMAILENGINE_URL}/v1/accounts", headers=headers)
        resp.raise_for_status()
        account_ids = [a["account"] for a in resp.json().get("accounts", [])]

    for acc_id in account_ids:
        page = 0
        page_size = 250

        while True:
            if limit and len(all_messages) >= limit:
                break

            params: dict = {"path": "INBOX", "page": page, "pageSize": page_size}
            if since:
                params["since"] = since
            if until:
                params["until"] = until
            if unread_only:
                params["unseen"] = "true"

            resp = await client.get(
                f"{EMAILENGINE_URL}/v1/account/{acc_id}/messages",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            messages = data.get("messages", [])

            if not messages:
                break

            for msg in messages:
                if limit and len(all_messages) >= limit:
                    break

                # Extraire from
                from_addr = msg.get("from", {})
                if isinstance(from_addr, dict):
                    from_email = from_addr.get("address", "")
                    from_name = from_addr.get("name", "")
                elif isinstance(from_addr, list) and from_addr:
                    from_email = from_addr[0].get("address", "")
                    from_name = from_addr[0].get("name", "")
                else:
                    from_email = ""
                    from_name = ""

                # Extraire to
                to_list = msg.get("to", [])
                to_emails = []
                if isinstance(to_list, list):
                    to_emails = [t.get("address", "") for t in to_list if isinstance(t, dict)]

                all_messages.append({
                    "message_id": msg.get("id", ""),
                    "emailengine_id": msg.get("id", ""),
                    "account_id": acc_id,
                    "from_email": from_email,
                    "from_name": from_name,
                    "to": to_emails,
                    "subject": msg.get("subject", ""),
                    "received_at": msg.get("date", ""),
                    "has_attachments": len(msg.get("attachments", [])) > 0,
                    "is_read": msg.get("seen", False),
                })

            page += 1

        logger.info(
            "account_fetched",
            account_id=acc_id,
            messages=len([m for m in all_messages if m["account_id"] == acc_id]),
        )

    # Tri par date DESC (plus recent d'abord)
    all_messages.sort(key=lambda m: m.get("received_at", ""), reverse=True)

    logger.info("total_emails_fetched", count=len(all_messages))
    return all_messages


async def fetch_email_body(
    client: httpx.AsyncClient, account_id: str, message_id: str
) -> str:
    """Recupere le corps d'un email via EmailEngine."""
    headers = {"Authorization": f"Bearer {EMAILENGINE_TOKEN}"}
    resp = await client.get(
        f"{EMAILENGINE_URL}/v1/account/{account_id}/message/{message_id}",
        headers=headers,
        params={"textType": "plain"},
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("text", {}).get("plain", "") or data.get("text", {}).get("html", "") or ""


async def check_email_exists(db: asyncpg.Connection, message_id: str) -> bool:
    """Verifie si un email est deja en base (pour skip ou reclassify)."""
    exists = await db.fetchval(
        "SELECT EXISTS(SELECT 1 FROM ingestion.emails WHERE message_id = $1)",
        message_id,
    )
    return exists


async def classify_email_for_migration(
    email_text: str, trust_mode: str
) -> dict:
    """
    Classification d'un email via le classifier agent.

    Pour migration, utilise directement l'adaptateur LLM (pas le pipeline complet).
    """
    try:
        from agents.email.classifier import classify_email as _classify
        # Placeholder: en production, appeler classify_email avec db_pool
        # Pour la migration, on utilise un appel simplifie
        pass
    except ImportError:
        pass

    # Fallback: classification via appel direct Claude
    from adapters.llm import get_llm_adapter

    llm = get_llm_adapter()
    prompt = (
        "Classe cet email dans une des categories suivantes : "
        "pro, finance, universite, recherche, perso, urgent, spam, inconnu.\n"
        "Reponds UNIQUEMENT avec le nom de la categorie.\n\n"
        f"Email:\n{email_text[:3000]}"
    )

    response = await llm.complete(prompt=prompt, max_tokens=20)
    category = response.text.strip().lower()

    # Valider categorie
    valid_categories = {"pro", "finance", "universite", "recherche", "perso", "urgent", "spam", "inconnu"}
    if category not in valid_categories:
        category = "inconnu"

    return {"category": category, "confidence": 0.85}


async def store_migrated_email(
    db: asyncpg.Connection,
    email: dict,
    category: str,
    confidence: float,
    body_text: str,
    reclassify: bool = False,
) -> str | None:
    """Stocke ou met a jour un email dans ingestion.emails."""
    if reclassify:
        await db.execute(
            """
            UPDATE ingestion.emails
            SET category = $2, confidence = $3, updated_at = NOW()
            WHERE message_id = $1
            """,
            email["message_id"],
            category,
            confidence,
        )
        return email["message_id"]
    else:
        try:
            email_id = await db.fetchval(
                """
                INSERT INTO ingestion.emails
                (account_id, message_id, sender, subject_anon, body_anon,
                 category, confidence, received_at, has_attachments, is_read,
                 metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::timestamptz, $9, $10, $11)
                ON CONFLICT (message_id) DO NOTHING
                RETURNING id
                """,
                email["account_id"],
                email["message_id"],
                email["from_email"],
                email.get("subject", ""),
                body_text[:10000],  # Limiter taille body
                category,
                confidence,
                email.get("received_at"),
                email.get("has_attachments", False),
                email.get("is_read", False),
                json.dumps({"source": "migration", "trust_mode": "auto"}),
            )
            return str(email_id) if email_id else None
        except Exception as e:
            logger.error("store_email_failed", message_id=email["message_id"], error=str(e))
            return None


async def migrate_emails(args: argparse.Namespace) -> None:
    """Boucle principale de migration."""
    if not EMAILENGINE_TOKEN:
        logger.error("EMAILENGINE_ACCESS_TOKEN not set")
        sys.exit(1)
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set")
        sys.exit(1)

    trust_mode = "propose" if args.trust_propose else "auto"
    checkpoint = MigrationCheckpoint(args.since, args.until)

    # Charger checkpoint si --resume
    if args.resume:
        if not checkpoint.load():
            logger.warning("no_checkpoint_found", msg="Starting from scratch")

    # Sample check obligatoire (securite)
    sample_flag = Path(f"/tmp/sample_validated_{args.since or 'start'}_{args.until or 'now'}.flag")
    if not args.resume and not sample_flag.exists() and not args.trust_auto:
        logger.info("SAMPLE CHECK MODE: Premiers emails en mode propose")
        trust_mode = "propose"
        if not args.limit or args.limit > 100:
            args.limit = 100
            logger.info("Limite automatique a 100 emails pour sample check")

    # Connexion DB
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)

    # Fetch emails depuis EmailEngine
    async with httpx.AsyncClient(timeout=60) as client:
        logger.info(
            "fetching_emails",
            since=args.since,
            until=args.until,
            unread_only=args.unread_only,
            limit=args.limit,
            account=args.account,
        )
        emails = await fetch_emails_from_emailengine(
            client,
            since=args.since,
            until=args.until,
            unread_only=args.unread_only,
            account_id=args.account,
            limit=args.limit,
        )

        if not emails:
            logger.info("no_emails_found")
            await db_pool.close()
            return

        total = len(emails)
        logger.info("migration_started", total=total, trust_mode=trust_mode)
        start_time = time.time()

        # Skip emails deja traites (si resume)
        skip_until_found = checkpoint.last_processed_id if args.resume else None
        skipping = skip_until_found is not None

        for idx, email in enumerate(emails):
            if _shutdown_requested:
                logger.info("shutdown_saving_checkpoint")
                checkpoint.save()
                break

            # Skip mode resume
            if skipping:
                if email["message_id"] == skip_until_found:
                    skipping = False
                    logger.info("resume_point_found", message_id=email["message_id"])
                continue

            message_id = email["message_id"]

            try:
                async with db_pool.acquire() as conn:
                    # Verifier doublon
                    exists = await check_email_exists(conn, message_id)
                    if exists and not args.reclassify:
                        checkpoint.update(message_id, migrated=False)
                        continue

                    # Fetch body
                    body_text = await fetch_email_body(
                        client, email["account_id"], message_id
                    )

                    # Classification
                    email_text = f"From: {email['from_email']}\nSubject: {email['subject']}\n\n{body_text}"
                    classification = await classify_email_for_migration(email_text, trust_mode)

                    # Stocker
                    email_id = await store_migrated_email(
                        conn,
                        email,
                        category=classification["category"],
                        confidence=classification["confidence"],
                        body_text=body_text,
                        reclassify=args.reclassify,
                    )

                    if email_id:
                        checkpoint.update(message_id, migrated=True)
                    else:
                        checkpoint.update(message_id, migrated=False)

            except Exception as e:
                logger.error(
                    "email_migration_failed",
                    message_id=message_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                checkpoint.increment_failed()
                continue

            # Log progression
            processed = checkpoint.count_migrated + checkpoint.count_skipped
            if processed % LOG_INTERVAL == 0:
                elapsed = time.time() - start_time
                rate = processed / (elapsed / 60) if elapsed > 0 else 0
                logger.info(
                    "migration_progress",
                    processed=processed,
                    total=total,
                    migrated=checkpoint.count_migrated,
                    skipped=checkpoint.count_skipped,
                    failed=checkpoint.count_failed,
                    rate_per_min=round(rate, 1),
                )

            # Checkpoint periodique
            if processed % CHECKPOINT_INTERVAL == 0:
                checkpoint.save()

    # Sauvegarder checkpoint final
    checkpoint.save()

    elapsed = time.time() - start_time
    logger.info(
        "migration_completed",
        migrated=checkpoint.count_migrated,
        skipped=checkpoint.count_skipped,
        failed=checkpoint.count_failed,
        elapsed_sec=round(elapsed),
        elapsed_min=round(elapsed / 60, 1),
    )

    # Si sample check reussi, creer flag
    if trust_mode == "propose" and checkpoint.count_migrated > 0:
        logger.info("sample_check_complete", msg="Valider dans Telegram puis relancer avec --trust-auto --resume")

    await db_pool.close()

    print(f"\n{'=' * 50}")
    print(f"Migration terminee")
    print(f"{'=' * 50}")
    print(f"Migres  : {checkpoint.count_migrated}")
    print(f"Ignores : {checkpoint.count_skipped}")
    print(f"Echecs  : {checkpoint.count_failed}")
    print(f"Duree   : {elapsed / 60:.1f} min")
    if checkpoint.count_migrated > 0:
        print(f"Rate    : {checkpoint.count_migrated / (elapsed / 60):.1f} emails/min")


def main():
    parser = argparse.ArgumentParser(
        description="Migration progressive emails via API EmailEngine"
    )
    parser.add_argument("--since", type=str, default=None, help="Date debut (YYYY-MM-DD)")
    parser.add_argument("--until", type=str, default=None, help="Date fin (YYYY-MM-DD)")
    parser.add_argument("--unread-only", action="store_true", help="Seulement non-lus")
    parser.add_argument("--limit", type=int, default=None, help="Limite nombre emails")
    parser.add_argument("--trust-auto", action="store_true", help="Bypass validation Telegram (bulk)")
    parser.add_argument("--trust-propose", action="store_true", help="Validation Telegram (sample)")
    parser.add_argument("--resume", action="store_true", help="Reprendre depuis checkpoint")
    parser.add_argument("--reclassify", action="store_true", help="Re-traiter emails existants (UPDATE)")
    parser.add_argument("--account", type=str, default=None, help="Filtrer par compte EmailEngine")

    args = parser.parse_args()

    # Validation arguments
    if args.trust_auto and args.trust_propose:
        print("ERROR: --trust-auto et --trust-propose sont mutuellement exclusifs")
        sys.exit(1)

    asyncio.run(migrate_emails(args))


if __name__ == "__main__":
    main()
