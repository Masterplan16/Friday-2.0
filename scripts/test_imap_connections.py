"""
Teste TOUS les comptes IMAP AVANT Phase B.
Verifie : connexion, count messages, latence reseau.

Story 2.8 / A.9 - Validation credentials IMAP pre-deploiement.

Usage:
    # Charger credentials depuis .env.email.enc
    export $(sops -d .env.email.enc | xargs)
    python scripts/test_imap_connections.py
"""

import imaplib
import os
import sys
from datetime import datetime

ACCOUNTS = [
    {
        "name": "Gmail Pro",
        "host": "imap.gmail.com",
        "port": 993,
        "user": os.getenv("GMAIL_PRO_USER"),
        "password": os.getenv("GMAIL_PRO_PASSWORD"),
        "expected_count": 27000,
    },
    {
        "name": "Gmail Perso",
        "host": "imap.gmail.com",
        "port": 993,
        "user": os.getenv("GMAIL_PERSO_USER"),
        "password": os.getenv("GMAIL_PERSO_PASSWORD"),
        "expected_count": 19000,
    },
    {
        "name": "Zimbra Universite",
        "host": "zimbra.umontpellier.fr",
        "port": 993,
        "user": os.getenv("ZIMBRA_USER"),
        "password": os.getenv("ZIMBRA_PASSWORD"),
        "expected_count": 45000,
    },
    {
        "name": "ProtonMail Bridge",
        "host": os.getenv("PROTON_BRIDGE_HOST", "pc-mainteneur"),
        "port": 1143,
        "user": os.getenv("PROTON_USER"),
        "password": os.getenv("PROTON_BRIDGE_PASSWORD"),
        "expected_count": 17000,
        "tls": False,
    },
]

# Note : Utiliser les noms DNS Tailscale (ex: pc-mainteneur, vps-friday)
# plutot que les IPs hardcodees (100.100.x.x) qui peuvent changer
# si le device est re-enregistre dans Tailscale.


def test_account(account: dict) -> bool:
    """Teste la connexion IMAP d'un compte."""
    name = account["name"]
    print(f"\nTesting {name}...")

    if not account.get("user") or not account.get("password"):
        print(f"  SKIP: credentials manquants (env vars non definies)")
        return False

    start = datetime.now()

    try:
        # Connexion IMAP
        if account.get("tls", True):
            imap = imaplib.IMAP4_SSL(account["host"], account["port"])
        else:
            imap = imaplib.IMAP4(account["host"], account["port"])

        imap.login(account["user"], account["password"])

        # Count messages
        imap.select("INBOX")
        _, data = imap.search(None, "ALL")
        count = len(data[0].split())

        imap.logout()

        latency = (datetime.now() - start).total_seconds()

        # Validation count
        expected = account["expected_count"]
        diff_pct = abs(count - expected) / expected * 100 if expected > 0 else 0

        if diff_pct > 20:
            print(
                f"  WARNING: Count mismatch: {count} vs {expected} expected ({diff_pct:.1f}% diff)"
            )
        else:
            print(f"  OK: {count} messages")

        # Validation latence
        if latency > 5:
            print(f"  WARNING: High latency: {latency:.2f}s")
        else:
            print(f"  OK: Latency: {latency:.2f}s")

        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("Friday 2.0 - IMAP Connection Validator")
    print("=" * 50)

    results = [test_account(acc) for acc in ACCOUNTS]

    print("\n" + "=" * 50)
    if all(results):
        print("ALL ACCOUNTS VALID - Ready for Phase B")
        sys.exit(0)
    else:
        failed = [
            ACCOUNTS[i]["name"] for i, ok in enumerate(results) if not ok
        ]
        print(f"FAILED: {', '.join(failed)} - Fix before continuing")
        sys.exit(1)
