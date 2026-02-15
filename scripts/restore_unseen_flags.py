#!/usr/bin/env python3
"""
EMERGENCY FIX: Restaurer flags UNSEEN sur emails marqués SEEN par erreur.

Bug: agents/src/adapters/email.py utilisait RFC822 (= BODY[]) au lieu de
BODY.PEEK[] dans le consumer re-fetch. Chaque email traité par le consumer
a été marqué \Seen côté IMAP serveur.

Ce script:
1. Lit ingestion.emails pour récupérer les UIDs traités par account
2. Se connecte à chaque compte IMAP
3. Exécute uid STORE <uid> -FLAGS (\Seen) pour restaurer UNSEEN

Usage:
    python scripts/restore_unseen_flags.py              # Dry-run (affiche sans modifier)
    python scripts/restore_unseen_flags.py --apply      # Applique les changements
    python scripts/restore_unseen_flags.py --apply --all  # Restaure TOUS les SEEN récents (pas juste DB)

Date: 2026-02-15
"""

import asyncio
import os
import ssl
import sys
from collections import defaultdict
from pathlib import Path

# Ajouter repo root au path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


async def load_accounts_config():
    """Charge config IMAP depuis env vars (même logique que imap_fetcher.py)."""
    accounts = {}
    for key, value in sorted(os.environ.items()):
        if key.startswith("IMAP_ACCOUNT_") and key.endswith("_EMAIL"):
            raw_id = key.replace("IMAP_ACCOUNT_", "").replace("_EMAIL", "")
            account_id = f"account_{raw_id.lower()}"
            prefix = f"IMAP_ACCOUNT_{raw_id}"

            accounts[account_id] = {
                "email": value,
                "imap_host": os.getenv(f"{prefix}_IMAP_HOST", ""),
                "imap_port": int(os.getenv(f"{prefix}_IMAP_PORT", "993")),
                "imap_user": os.getenv(f"{prefix}_IMAP_USER", value),
                "imap_password": os.getenv(f"{prefix}_IMAP_PASSWORD", ""),
            }

    return accounts


async def get_processed_uids_from_db():
    """Récupère les UIDs traités par le consumer depuis PostgreSQL."""
    import asyncpg

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    conn = await asyncpg.connect(db_url)

    rows = await conn.fetch(
        """
        SELECT account_id, message_id
        FROM ingestion.emails
        ORDER BY account_id, message_id::integer
        """
    )

    await conn.close()

    uids_by_account = defaultdict(list)
    for row in rows:
        uids_by_account[row["account_id"]].append(row["message_id"])

    return uids_by_account


async def restore_unseen_for_account(account_id, account_config, uids, dry_run=True):
    """Restaure flag UNSEEN pour une liste d'UIDs sur un compte IMAP."""
    import aioimaplib

    host = account_config["imap_host"]
    port = account_config["imap_port"]

    print(f"\n{'='*60}")
    print(f"Compte: {account_id} ({account_config['email']})")
    print(f"Host: {host}:{port}")
    print(f"UIDs à restaurer: {len(uids)}")

    if not uids:
        print("  Aucun UID à restaurer.")
        return 0

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

        response = await imap.login(
            account_config["imap_user"],
            account_config["imap_password"],
        )
        if response.result != "OK":
            print(f"  ERREUR: Login failed: {response.result}")
            return 0

        await imap.select("INBOX")
        print(f"  Connecté à INBOX")

        restored_count = 0
        failed_count = 0

        for uid in uids:
            try:
                if dry_run:
                    print(f"  [DRY-RUN] Restaurerait UID {uid} → UNSEEN")
                    restored_count += 1
                else:
                    # -FLAGS = retirer le flag. \Seen = flag de lecture
                    result = await imap.uid("store", uid, "-FLAGS", "(\\Seen)")

                    if isinstance(result, tuple):
                        status = result[0]
                    else:
                        status = result.result

                    if status == "OK":
                        restored_count += 1
                        if restored_count % 20 == 0:
                            print(f"  Progression: {restored_count}/{len(uids)} restaurés...")
                    else:
                        print(f"  WARN: UID {uid} store failed: {status}")
                        failed_count += 1

            except Exception as e:
                print(f"  ERREUR UID {uid}: {e}")
                failed_count += 1

        await imap.logout()

        action = "restaurés (dry-run)" if dry_run else "restaurés UNSEEN"
        print(f"  Résultat: {restored_count} {action}, {failed_count} erreurs")
        return restored_count

    except Exception as e:
        print(f"  ERREUR connexion: {e}")
        return 0


async def restore_all_seen_for_account(account_id, account_config, dry_run=True):
    """
    Mode --all: cherche TOUS les emails SEEN dans INBOX et les remet en UNSEEN.
    Utile si on veut restaurer y compris des emails pas dans la DB.
    """
    import aioimaplib
    import re

    host = account_config["imap_host"]
    port = account_config["imap_port"]

    print(f"\n{'='*60}")
    print(f"Compte: {account_id} ({account_config['email']})")
    print(f"Host: {host}:{port}")
    print(f"Mode: TOUS les SEEN → UNSEEN")

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

        response = await imap.login(
            account_config["imap_user"],
            account_config["imap_password"],
        )
        if response.result != "OK":
            print(f"  ERREUR: Login failed: {response.result}")
            return 0

        await imap.select("INBOX")

        # Chercher tous les emails SEEN
        status, data = await imap.search("SEEN")
        if status != "OK":
            print(f"  ERREUR: SEARCH SEEN failed: {status}")
            await imap.logout()
            return 0

        seq_str = data[0] if data else b""
        if isinstance(seq_str, (bytes, bytearray)):
            seq_str = seq_str.decode("utf-8", errors="replace")

        if not seq_str or not seq_str.strip():
            print(f"  Aucun email SEEN trouvé.")
            await imap.logout()
            return 0

        seq_nums = seq_str.strip().split()
        print(f"  Emails SEEN trouvés: {len(seq_nums)}")

        # Récupérer les UIDs pour chaque séquence
        uids = []
        for seq in seq_nums:
            try:
                result = await imap.fetch(seq, "(UID)")
                if isinstance(result, tuple):
                    fetch_data = result[1]
                else:
                    fetch_data = result.lines

                for item in fetch_data:
                    item_str = item.decode("utf-8", errors="replace") if isinstance(item, (bytes, bytearray)) else str(item)
                    match = re.search(r"UID\s+(\d+)", item_str)
                    if match:
                        uids.append(match.group(1))
                        break
            except Exception as e:
                print(f"  WARN: fetch UID for seq {seq} failed: {e}")

        print(f"  UIDs SEEN récupérés: {len(uids)}")

        if not uids:
            await imap.logout()
            return 0

        restored_count = 0
        failed_count = 0

        for uid in uids:
            try:
                if dry_run:
                    restored_count += 1
                else:
                    result = await imap.uid("store", uid, "-FLAGS", "(\\Seen)")
                    if isinstance(result, tuple):
                        st = result[0]
                    else:
                        st = result.result

                    if st == "OK":
                        restored_count += 1
                        if restored_count % 20 == 0:
                            print(f"  Progression: {restored_count}/{len(uids)}...")
                    else:
                        failed_count += 1
            except Exception as e:
                print(f"  ERREUR UID {uid}: {e}")
                failed_count += 1

        await imap.logout()

        action = "à restaurer (dry-run)" if dry_run else "restaurés UNSEEN"
        print(f"  Résultat: {restored_count} {action}, {failed_count} erreurs")
        return restored_count

    except Exception as e:
        print(f"  ERREUR connexion: {e}")
        return 0


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Restaurer flags UNSEEN sur emails marqués SEEN par erreur")
    parser.add_argument("--apply", action="store_true", help="Appliquer les changements (sans = dry-run)")
    parser.add_argument("--all", action="store_true", help="Restaurer TOUS les SEEN (pas juste ceux en DB)")
    args = parser.parse_args()

    dry_run = not args.apply

    if dry_run:
        print("MODE DRY-RUN (ajouter --apply pour exécuter)")
    else:
        print("MODE APPLY — Les flags IMAP vont être modifiés")

    print()

    # Charger config comptes
    accounts = await load_accounts_config()
    if not accounts:
        print("ERREUR: Aucun compte IMAP configuré (IMAP_ACCOUNT_* env vars)")
        sys.exit(1)

    print(f"Comptes trouvés: {len(accounts)}")
    for aid, cfg in accounts.items():
        print(f"  - {aid}: {cfg['email']} ({cfg['imap_host']}:{cfg['imap_port']})")

    total_restored = 0

    if args.all:
        # Mode --all: restaurer TOUS les SEEN
        for account_id, config in accounts.items():
            count = await restore_all_seen_for_account(account_id, config, dry_run)
            total_restored += count
    else:
        # Mode normal: restaurer seulement les UIDs de la DB
        print("\nRécupération UIDs depuis PostgreSQL ingestion.emails...")
        uids_by_account = await get_processed_uids_from_db()

        for account_id, uids in uids_by_account.items():
            print(f"  {account_id}: {len(uids)} UIDs")

        for account_id, config in accounts.items():
            uids = uids_by_account.get(account_id, [])
            count = await restore_unseen_for_account(account_id, config, uids, dry_run)
            total_restored += count

    print(f"\n{'='*60}")
    if dry_run:
        print(f"DRY-RUN TERMINÉ: {total_restored} emails seraient restaurés en UNSEEN")
        print(f"Relancer avec --apply pour exécuter")
    else:
        print(f"TERMINÉ: {total_restored} emails restaurés en UNSEEN")


if __name__ == "__main__":
    asyncio.run(main())
