#!/usr/bin/env python3
"""
Extraction top domains depuis IMAP direct (D25 : remplace EmailEngine).

Story 2.9 Phase D.0 - Scan domaines avant migration historique.
Source de donnees : IMAP INBOX de chaque compte configure (headers From seulement).

Format CSV strict :
    domain,email_count,suggestion,action
    example.com,1234,whitelist,
    spam.com,567,blacklist,blacklist

Workflow :
1. Script scanne IMAP INBOX → genere CSV
2. Mainteneur telecharge, ouvre dans Excel, remplit colonne 'action'
3. python scripts/extract_email_domains.py --apply domain_filters.csv
4. Filtres appliques dans core.sender_filters

Usage:
    python scripts/extract_email_domains.py                    # Generer CSV (top 200)
    python scripts/extract_email_domains.py --top 500          # Top 500 domains
    python scripts/extract_email_domains.py --apply domain_filters.csv  # Appliquer CSV rempli

Date: 2026-02-15 (D25 rewrite)
"""

import argparse
import asyncio
import csv
import email as email_lib
import os
import re
import ssl
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

# Ajouter repo root au path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

DATABASE_URL = os.getenv("DATABASE_URL")

# Seuils suggestions
VIP_MIN_EMAILS = 50
BLACKLIST_KEYWORDS = [
    "newsletter",
    "noreply",
    "no-reply",
    "marketing",
    "promo",
    "notification",
    "alert",
    "mailer-daemon",
    "unsubscribe",
    "bounce",
    "daemon",
    "automated",
    "do-not-reply",
]

CSV_HEADERS = ["domain", "email_count", "suggestion", "action"]


# ============================================================================
# IMAP Account Config (meme logique que imap_fetcher.py)
# ============================================================================


def load_accounts_config() -> List[Dict]:
    """Charge config comptes IMAP depuis variables d'environnement."""
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


# ============================================================================
# IMAP Fetch Senders
# ============================================================================


async def fetch_senders_from_account(account: Dict) -> List[str]:
    """
    Scan INBOX d'un compte IMAP et extrait toutes les adresses From.
    Utilise BODY.PEEK[HEADER.FIELDS (FROM)] pour ne recuperer que le header From
    sans marquer les messages comme lus.
    """
    import aioimaplib

    account_id = account["account_id"]
    host = account["imap_host"]
    port = account["imap_port"]

    print(f"  [{account_id}] Connexion {host}:{port}...")

    # SSL context pour ProtonMail Bridge
    ssl_context = None
    if "protonmail" in account_id.lower():
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        cert_path = Path("/app/config/certs/protonmail_bridge.pem")
        if cert_path.exists():
            ssl_context.load_verify_locations(cafile=str(cert_path))
        else:
            ssl_context.verify_mode = ssl.CERT_NONE

    try:
        imap = aioimaplib.IMAP4_SSL(
            host=host,
            port=port,
            ssl_context=ssl_context,
        )
        await imap.wait_hello_from_server()

        response = await imap.login(account["imap_user"], account["imap_password"])
        if response.result != "OK":
            print(f"  [{account_id}] ERREUR login: {response.result}")
            return []

        # SELECT INBOX (BODY.PEEK garantit zero modification des flags)
        await imap.select("INBOX")

        # Compter messages
        status, data = await imap.search("ALL")
        if status != "OK":
            print(f"  [{account_id}] ERREUR search: {status}")
            await imap.logout()
            return []

        seq_str = data[0] if data else b""
        if isinstance(seq_str, (bytes, bytearray)):
            seq_str = seq_str.decode("utf-8", errors="replace")

        if not seq_str or not seq_str.strip():
            print(f"  [{account_id}] INBOX vide")
            await imap.logout()
            return []

        seq_nums = seq_str.strip().split()
        total = len(seq_nums)
        print(f"  [{account_id}] {total} messages dans INBOX")

        # Fetch From headers par batch (BODY.PEEK = pas de flag Seen)
        senders = []
        batch_size = 100
        processed = 0

        for i in range(0, total, batch_size):
            batch = seq_nums[i : i + batch_size]
            seq_range = ",".join(batch)

            try:
                status, fetch_data = await imap.fetch(
                    seq_range, "(BODY.PEEK[HEADER.FIELDS (FROM)])"
                )

                if status != "OK":
                    print(f"  [{account_id}] WARN: fetch batch {i}-{i+len(batch)} failed: {status}")
                    continue

                # Parser les reponses
                for item in fetch_data:
                    if isinstance(item, (bytes, bytearray)):
                        item_str = bytes(item).decode("utf-8", errors="replace")
                    elif isinstance(item, str):
                        item_str = item
                    else:
                        continue

                    # Ignorer lignes de status IMAP
                    if "FETCH" in item_str and "BODY" in item_str:
                        continue
                    if item_str.strip() == ")" or "completed" in item_str.lower():
                        continue

                    # Extraire adresse email du header From
                    from_match = re.search(r"From:\s*(.+)", item_str, re.IGNORECASE)
                    if from_match:
                        from_value = from_match.group(1).strip()
                        addr = _extract_email_address(from_value)
                        if addr and "@" in addr:
                            senders.append(addr.lower())

                processed += len(batch)
                if processed % 500 == 0 or processed == total:
                    print(
                        f"  [{account_id}] Progression: {processed}/{total} ({len(senders)} senders)"
                    )

            except Exception as e:
                print(f"  [{account_id}] WARN: batch {i} error: {e}")
                continue

        await imap.logout()
        print(f"  [{account_id}] Termine: {len(senders)} senders extraits")
        return senders

    except Exception as e:
        print(f"  [{account_id}] ERREUR: {e}")
        return []


def _extract_email_address(from_header: str) -> str:
    """Extrait l'adresse email d'un header From (avec ou sans nom)."""
    # Format: "Name <email@domain.com>" ou "email@domain.com"
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1).strip()

    # Pas de chevrons, chercher directement un email
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", from_header)
    if match:
        return match.group(0).strip()

    return ""


async def fetch_all_senders_imap() -> List[str]:
    """Scan tous les comptes IMAP et retourne toutes les adresses sender."""
    accounts = load_accounts_config()

    if not accounts:
        print("ERREUR: Aucun compte IMAP configure (IMAP_ACCOUNT_* env vars)")
        sys.exit(1)

    print(f"Comptes IMAP: {len(accounts)}")
    for acc in accounts:
        print(f"  - {acc['account_id']}: {acc['email']}")

    all_senders = []
    for account in accounts:
        senders = await fetch_senders_from_account(account)
        all_senders.extend(senders)

    return all_senders


# ============================================================================
# Analysis & Suggestions
# ============================================================================


def analyze_domains(senders: list[str], top_n: int = 200) -> list[dict]:
    """Analyse les domaines et genere suggestions."""
    domain_counter: Counter = Counter()
    domain_senders: dict[str, set] = {}

    for sender in senders:
        if "@" not in sender:
            continue
        _, domain = sender.rsplit("@", 1)
        domain_counter[domain] += 1
        if domain not in domain_senders:
            domain_senders[domain] = set()
        domain_senders[domain].add(sender)

    results = []
    for domain, count in domain_counter.most_common(top_n):
        suggestion = _suggest_filter(domain, count, domain_senders.get(domain, set()))
        results.append(
            {
                "domain": domain,
                "email_count": count,
                "suggestion": suggestion,
                "action": "",  # A remplir par Mainteneur
            }
        )

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


# ============================================================================
# CSV I/O
# ============================================================================


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

        if list(reader.fieldnames) != CSV_HEADERS:
            print(f"ERROR: Invalid headers: {reader.fieldnames}")
            print(f"Expected: {CSV_HEADERS}")
            return False

        for i, row in enumerate(reader, start=2):
            action = row.get("action", "").strip()
            if action and action not in ("vip", "whitelist", "blacklist"):
                print(
                    f"ERROR line {i}: Invalid action '{action}' (must be vip/whitelist/blacklist or empty)"
                )
                return False

            domain = row.get("domain", "").strip()
            if not re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", domain):
                print(f"ERROR line {i}: Invalid domain '{domain}'")
                return False

    return True


async def apply_filters_from_csv(csv_path: str) -> dict[str, int]:
    """Applique les filtres depuis un CSV valide dans core.sender_filters."""
    import asyncpg

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    db = await asyncpg.connect(DATABASE_URL)
    stats: dict[str, int] = {"vip": 0, "whitelist": 0, "blacklist": 0, "skipped": 0}

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # action override suggestion si rempli, sinon fallback sur suggestion
            action = row.get("action", "").strip()
            if not action:
                action = row.get("suggestion", "").strip()
            if not action:
                stats["skipped"] += 1
                continue

            domain = row["domain"].strip()

            await db.execute(
                """
                INSERT INTO core.sender_filters (filter_type, sender_domain, created_by)
                VALUES ($1, $2, 'system')
                ON CONFLICT (sender_domain) WHERE sender_email IS NULL AND sender_domain IS NOT NULL
                DO UPDATE SET filter_type = EXCLUDED.filter_type, updated_at = NOW()
                """,
                action,
                domain,
            )
            stats[action] += 1

    await db.close()
    return stats


# ============================================================================
# Main
# ============================================================================


async def main() -> None:
    parser = argparse.ArgumentParser(description="Extract top email domains via IMAP direct (D25)")
    parser.add_argument("--top", type=int, default=200, help="Top N domains (default: 200)")
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
        print(
            f"\n{total} filtres appliques : "
            f"{stats['vip']} VIP, {stats['whitelist']} whitelist, {stats['blacklist']} blacklist "
            f"({stats['skipped']} ignores)"
        )
        return

    # Mode extraction IMAP
    print("Scan IMAP INBOX de tous les comptes...")
    print()
    senders = await fetch_all_senders_imap()
    print(f"\nTotal senders: {len(senders)}")

    domains = analyze_domains(senders, top_n=args.top)
    save_csv(domains, args.output)

    print(f"\nCSV genere: {args.output}")
    print(f"Domaines uniques: {len(domains)}")
    print(f"\nTop 15 domaines:")
    for i, d in enumerate(domains[:15], 1):
        print(f"  {i:3d}. {d['domain']:40s} {d['email_count']:5d} emails  -> {d['suggestion']}")

    print(f"\nWorkflow:")
    print(f"  1. Ouvrir {args.output} dans Excel/Google Sheets")
    print(f"  2. Remplir colonne 'action' (vip/whitelist/blacklist ou vide)")
    print(f"  3. python scripts/extract_email_domains.py --apply {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
