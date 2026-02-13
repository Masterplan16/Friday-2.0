#!/usr/bin/env python3
"""
[DEPRECATED D25] Extraction top domains depuis API EmailEngine (headers seulement, 0 token Claude).
Ce script dependait de l'API REST EmailEngine, retiree par D25 (IMAP direct).

Story 2.9 - Reecriture complete.
Source de donnees : API EmailEngine REST (remplace ingestion.emails qui est vide avant migration).

Format CSV strict :
    domain,email_count,suggestion,action
    example.com,1234,whitelist,
    spam.com,567,blacklist,blacklist

Workflow :
1. Script genere CSV → envoie via bot.send_document()
2. Mainteneur telecharge, ouvre dans Excel, remplit colonne 'action'
3. Mainteneur renvoie CSV modifie dans topic System
4. Bot detecte document, valide CSV, applique filtres
5. Confirmation Telegram : "143 filtres appliques : 18 VIP, 58 whitelist, 67 blacklist"

Usage:
    python scripts/extract_email_domains.py                    # Generer CSV
    python scripts/extract_email_domains.py --apply domain_filters.csv  # Appliquer CSV rempli
    python scripts/extract_email_domains.py --top 100          # Top 100 domains (defaut: 50)
"""

import argparse
import asyncio
import csv
import os
import re
import sys
from collections import Counter

import asyncpg
import httpx
import structlog

logger = structlog.get_logger(__name__)

EMAILENGINE_URL = os.getenv("EMAILENGINE_URL", "http://localhost:3000")
EMAILENGINE_TOKEN = os.getenv("EMAILENGINE_ACCESS_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Seuils suggestions
VIP_MIN_EMAILS = 50  # >50 emails d'un domaine pro → suggestion VIP
BLACKLIST_KEYWORDS = [
    "newsletter", "noreply", "no-reply", "marketing", "promo",
    "notification", "alert", "mailer-daemon", "unsubscribe",
]

CSV_HEADERS = ["domain", "email_count", "suggestion", "action"]


async def fetch_all_senders(client: httpx.AsyncClient) -> list[str]:
    """Recupere tous les senders via EmailEngine API (headers seulement)."""
    senders = []

    # Lister comptes
    accounts_resp = await client.get(
        f"{EMAILENGINE_URL}/v1/accounts",
        headers={"Authorization": f"Bearer {EMAILENGINE_TOKEN}"},
    )
    accounts_resp.raise_for_status()
    accounts = accounts_resp.json().get("accounts", [])

    for account in accounts:
        account_id = account["account"]
        page = 0
        page_size = 250

        while True:
            resp = await client.get(
                f"{EMAILENGINE_URL}/v1/account/{account_id}/messages",
                headers={"Authorization": f"Bearer {EMAILENGINE_TOKEN}"},
                params={"path": "INBOX", "page": page, "pageSize": page_size},
            )
            resp.raise_for_status()
            data = resp.json()
            messages = data.get("messages", [])

            if not messages:
                break

            for msg in messages:
                from_addr = msg.get("from", {})
                if isinstance(from_addr, dict):
                    email = from_addr.get("address", "")
                elif isinstance(from_addr, list) and from_addr:
                    email = from_addr[0].get("address", "")
                else:
                    continue

                if email and "@" in email:
                    senders.append(email.lower())

            page += 1

            # Safety: log progression
            if page % 10 == 0:
                logger.info(
                    "fetch_progress",
                    account_id=account_id,
                    page=page,
                    senders_so_far=len(senders),
                )

    return senders


def analyze_domains(senders: list[str], top_n: int = 50) -> list[dict]:
    """Analyse les domaines et genere suggestions."""
    domain_counter: Counter = Counter()
    domain_senders: dict[str, set] = {}

    for sender in senders:
        _, domain = sender.rsplit("@", 1)
        domain_counter[domain] += 1
        if domain not in domain_senders:
            domain_senders[domain] = set()
        domain_senders[domain].add(sender)

    results = []
    for domain, count in domain_counter.most_common(top_n):
        suggestion = _suggest_filter(domain, count, domain_senders.get(domain, set()))
        results.append({
            "domain": domain,
            "email_count": count,
            "suggestion": suggestion,
            "action": "",  # A remplir par Mainteneur
        })

    return results


def _suggest_filter(domain: str, count: int, senders: set[str]) -> str:
    """Genere suggestion automatique pour un domaine."""
    # Check blacklist keywords dans senders
    for sender in senders:
        local_part = sender.split("@")[0]
        if any(kw in local_part for kw in BLACKLIST_KEYWORDS):
            return "blacklist"

    # Domaines marketing connus
    marketing_tlds = [".info", ".club", ".xyz", ".top", ".buzz"]
    if any(domain.endswith(tld) for tld in marketing_tlds):
        return "blacklist"

    # VIP : domaines pro avec beaucoup d'emails
    pro_indicators = [".gouv.fr", ".edu", ".ac.fr", ".univ-", "chu-", ".sante.fr"]
    if count >= VIP_MIN_EMAILS and any(ind in domain for ind in pro_indicators):
        return "vip"

    # Default : whitelist
    return "whitelist"


def save_csv(domains: list[dict], output_path: str) -> None:
    """Sauvegarde resultats en CSV."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(domains)


def validate_csv(csv_path: str) -> bool:
    """Valide un CSV rempli par le Mainteneur avant application."""
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)

        # Verifier headers
        if list(reader.fieldnames) != CSV_HEADERS:
            print(f"ERROR: Invalid headers: {reader.fieldnames}")
            print(f"Expected: {CSV_HEADERS}")
            return False

        for i, row in enumerate(reader, start=2):
            # Verifier action valide
            action = row.get("action", "").strip()
            if action and action not in ("vip", "whitelist", "blacklist"):
                print(f"ERROR line {i}: Invalid action '{action}' (must be vip/whitelist/blacklist or empty)")
                return False

            # Verifier domain format
            domain = row.get("domain", "").strip()
            if not re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", domain):
                print(f"ERROR line {i}: Invalid domain '{domain}'")
                return False

    return True


async def apply_filters_from_csv(csv_path: str) -> dict[str, int]:
    """Applique les filtres depuis un CSV valide dans core.sender_filters."""
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    db = await asyncpg.connect(DATABASE_URL)
    stats: dict[str, int] = {"vip": 0, "whitelist": 0, "blacklist": 0, "skipped": 0}

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            action = row.get("action", "").strip()
            if not action:
                stats["skipped"] += 1
                continue

            domain = row["domain"].strip()

            await db.execute(
                """
                INSERT INTO core.sender_filters (filter_type, sender_domain, created_by)
                VALUES ($1, $2, 'system')
                ON CONFLICT (sender_domain) WHERE sender_email IS NULL
                DO UPDATE SET filter_type = EXCLUDED.filter_type, updated_at = NOW()
                """,
                action,
                domain,
            )
            stats[action] += 1

    await db.close()
    return stats


async def main() -> None:
    parser = argparse.ArgumentParser(description="Extract top email domains from EmailEngine")
    parser.add_argument("--top", type=int, default=50, help="Top N domains (default: 50)")
    parser.add_argument("--output", type=str, default="domain_filters.csv", help="Output CSV file")
    parser.add_argument("--apply", type=str, default=None, help="Apply filters from CSV file")
    args = parser.parse_args()

    # Mode application
    if args.apply:
        print(f"Validating CSV: {args.apply}")
        if not validate_csv(args.apply):
            print("CSV validation FAILED")
            sys.exit(1)

        print("CSV valid. Applying filters...")
        stats = await apply_filters_from_csv(args.apply)
        total = stats["vip"] + stats["whitelist"] + stats["blacklist"]
        print(f"\n{total} filtres appliques : "
              f"{stats['vip']} VIP, {stats['whitelist']} whitelist, {stats['blacklist']} blacklist "
              f"({stats['skipped']} ignores)")
        return

    # Mode extraction
    if not EMAILENGINE_TOKEN:
        print("ERROR: EMAILENGINE_ACCESS_TOKEN not set")
        sys.exit(1)

    print(f"Fetching senders from EmailEngine API...")
    async with httpx.AsyncClient(timeout=60) as client:
        senders = await fetch_all_senders(client)

    print(f"Total senders fetched: {len(senders)}")

    domains = analyze_domains(senders, top_n=args.top)
    save_csv(domains, args.output)

    print(f"\nCSV saved: {args.output}")
    print(f"\nTop 10 domains:")
    for i, d in enumerate(domains[:10], 1):
        print(f"  {i}. {d['domain']} ({d['email_count']} emails) -> suggestion: {d['suggestion']}")

    print(f"\nWorkflow:")
    print(f"  1. Ouvrir {args.output} dans Excel")
    print(f"  2. Remplir colonne 'action' (vip/whitelist/blacklist ou vide)")
    print(f"  3. python scripts/extract_email_domains.py --apply {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
