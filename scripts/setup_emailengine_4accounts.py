#!/usr/bin/env python3
"""
[DEPRECATED D25 - 2026-02-13] EmailEngine retiré. Ce script n'est plus utilisé.
Remplacé par: agents/src/adapters/email.py (IMAP direct)

Setup EmailEngine avec les 4 comptes IMAP de Masterplan.

Usage:
    python scripts/setup_emailengine_4accounts.py [--dry-run]

Prérequis:
    - EmailEngine running (docker compose up -d emailengine)
    - .env.email chargé dans l'environnement
    - ProtonMail Bridge running sur PC (Tailscale 100.100.4.31)
"""

import asyncio
import os
import sys
from typing import Dict, Any
import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv(".env.email")

# EmailEngine API configuration
EMAILENGINE_URL = os.getenv("EMAILENGINE_URL", "http://localhost:3000")
EMAILENGINE_ACCESS_TOKEN = os.getenv("EMAILENGINE_ACCESS_TOKEN")

if not EMAILENGINE_ACCESS_TOKEN:
    print("❌ EMAILENGINE_ACCESS_TOKEN not found in environment")
    sys.exit(1)

# Account configurations
ACCOUNTS = [
    {
        "account_id": "account_professional",
        "name": "Gmail Pro",
        "email": os.getenv("GMAIL_PRO_EMAIL"),
        "imap": {
            "host": os.getenv("GMAIL_PRO_IMAP_HOST"),
            "port": int(os.getenv("GMAIL_PRO_IMAP_PORT", 993)),
            "secure": True,
            "auth": {
                "user": os.getenv("GMAIL_PRO_IMAP_USER"),
                "pass": os.getenv("GMAIL_PRO_APP_PASSWORD"),
            }
        },
        "smtp": {
            "host": os.getenv("GMAIL_PRO_SMTP_HOST"),
            "port": int(os.getenv("GMAIL_PRO_SMTP_PORT", 587)),
            "secure": True,
            "auth": {
                "user": os.getenv("GMAIL_PRO_IMAP_USER"),
                "pass": os.getenv("GMAIL_PRO_APP_PASSWORD"),
            }
        }
    },
    {
        "account_id": "account_personal",
        "name": "Gmail Perso",
        "email": os.getenv("GMAIL_PERSO_EMAIL"),
        "imap": {
            "host": os.getenv("GMAIL_PERSO_IMAP_HOST"),
            "port": int(os.getenv("GMAIL_PERSO_IMAP_PORT", 993)),
            "secure": True,
            "auth": {
                "user": os.getenv("GMAIL_PERSO_IMAP_USER"),
                "pass": os.getenv("GMAIL_PERSO_APP_PASSWORD"),
            }
        },
        "smtp": {
            "host": os.getenv("GMAIL_PERSO_SMTP_HOST"),
            "port": int(os.getenv("GMAIL_PERSO_SMTP_PORT", 587)),
            "secure": True,
            "auth": {
                "user": os.getenv("GMAIL_PERSO_IMAP_USER"),
                "pass": os.getenv("GMAIL_PERSO_APP_PASSWORD"),
            }
        }
    },
    {
        "account_id": "account_faculty",
        "name": "Zimbra Université",
        "email": os.getenv("ZIMBRA_EMAIL"),
        "imap": {
            "host": os.getenv("ZIMBRA_IMAP_HOST"),
            "port": int(os.getenv("ZIMBRA_IMAP_PORT", 993)),
            "secure": True,
            "auth": {
                "user": os.getenv("ZIMBRA_IMAP_USER"),  # p00000004769@umontpellier.fr
                "pass": os.getenv("ZIMBRA_PASSWORD"),
            }
        },
        "smtp": {
            "host": os.getenv("ZIMBRA_SMTP_HOST"),
            "port": int(os.getenv("ZIMBRA_SMTP_PORT", 587)),
            "secure": True,
            "auth": {
                "user": os.getenv("ZIMBRA_IMAP_USER"),
                "pass": os.getenv("ZIMBRA_PASSWORD"),
            }
        }
    },
    {
        "account_id": "account_protonmail",
        "name": "ProtonMail (Bridge)",
        "email": os.getenv("PROTONMAIL_EMAIL"),
        "imap": {
            "host": os.getenv("PROTONMAIL_IMAP_HOST"),  # Tailscale IP du PC
            "port": int(os.getenv("PROTONMAIL_IMAP_PORT", 1143)),
            "secure": False,  # STARTTLS, pas TLS direct
            "tls": {"rejectUnauthorized": False},  # Cert auto-signe Bridge
            "auth": {
                "user": os.getenv("PROTONMAIL_IMAP_USER"),
                "pass": os.getenv("PROTONMAIL_BRIDGE_PASSWORD"),
            }
        },
        "smtp": {
            "host": os.getenv("PROTONMAIL_SMTP_HOST"),  # Tailscale IP du PC
            "port": int(os.getenv("PROTONMAIL_SMTP_PORT", 1025)),
            "secure": False,  # STARTTLS
            "tls": {"rejectUnauthorized": False},
            "auth": {
                "user": os.getenv("PROTONMAIL_IMAP_USER"),
                "pass": os.getenv("PROTONMAIL_BRIDGE_PASSWORD"),
            }
        }
    }
]


async def create_account(client: httpx.AsyncClient, account: Dict[str, Any], dry_run: bool = False) -> bool:
    """Crée un compte EmailEngine."""
    account_id = account["account_id"]

    if dry_run:
        print(f"[DRY-RUN] Would create account: {account_id} ({account['email']})")
        return True

    print(f"📧 Creating account: {account_id} ({account['email']})...")

    try:
        # Create account
        response = await client.post(
            f"{EMAILENGINE_URL}/v1/account",
            json={
                "account": account_id,
                "name": account["name"],
                "email": account["email"],
                "imap": account["imap"],
                "smtp": account.get("smtp"),
            },
            headers={"Authorization": f"Bearer {EMAILENGINE_ACCESS_TOKEN}"},
            timeout=30.0,
        )

        if response.status_code == 200:
            print(f"   ✅ Account {account_id} created successfully")
            return True
        elif response.status_code == 409:
            print(f"   ⚠️  Account {account_id} already exists, skipping...")
            return True
        else:
            print(f"   ❌ Failed to create account {account_id}: {response.status_code}")
            print(f"      Response: {response.text}")
            return False

    except Exception as e:
        print(f"   ❌ Error creating account {account_id}: {e}")
        return False


async def verify_account(client: httpx.AsyncClient, account_id: str) -> bool:
    """Vérifie le statut d'un compte EmailEngine."""
    print(f"🔍 Verifying account: {account_id}...")

    try:
        response = await client.get(
            f"{EMAILENGINE_URL}/v1/account/{account_id}",
            headers={"Authorization": f"Bearer {EMAILENGINE_ACCESS_TOKEN}"},
            timeout=10.0,
        )

        if response.status_code == 200:
            data = response.json()
            state = data.get("account", {}).get("state")

            if state == "connected":
                print(f"   ✅ Account {account_id} is CONNECTED")
                return True
            else:
                print(f"   ⚠️  Account {account_id} state: {state}")
                return False
        else:
            print(f"   ❌ Failed to verify account {account_id}: {response.status_code}")
            return False

    except Exception as e:
        print(f"   ❌ Error verifying account {account_id}: {e}")
        return False


async def main():
    """Main setup function."""
    dry_run = "--dry-run" in sys.argv

    print("=" * 80)
    print("🚀 Friday 2.0 - EmailEngine 4 Accounts Setup")
    print("=" * 80)
    print()

    if dry_run:
        print("⚠️  DRY-RUN MODE: No actual changes will be made")
        print()

    # Verify environment variables
    print("📋 Checking environment variables...")
    missing = []
    for account in ACCOUNTS:
        if not account["email"]:
            missing.append(f"{account['account_id']}: email")
        if not account["imap"]["auth"]["pass"]:
            missing.append(f"{account['account_id']}: password")

    if missing:
        print(f"❌ Missing environment variables:")
        for m in missing:
            print(f"   - {m}")
        sys.exit(1)

    print("   ✅ All environment variables present")
    print()

    # Test EmailEngine connectivity
    print("🔗 Testing EmailEngine connectivity...")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{EMAILENGINE_URL}/v1/settings",
                headers={"Authorization": f"Bearer {EMAILENGINE_ACCESS_TOKEN}"},
                timeout=5.0,
            )
            if response.status_code in (200, 401):
                print(f"   ✅ EmailEngine is running at {EMAILENGINE_URL}")
            else:
                print(f"   ❌ EmailEngine returned status {response.status_code}")
                sys.exit(1)
        except Exception as e:
            print(f"   ❌ Cannot reach EmailEngine at {EMAILENGINE_URL}: {e}")
            print(f"      Make sure EmailEngine is running: docker compose up -d emailengine")
            sys.exit(1)

    print()

    # Create accounts
    print("📧 Creating EmailEngine accounts...")
    print()

    async with httpx.AsyncClient() as client:
        results = []
        for account in ACCOUNTS:
            success = await create_account(client, account, dry_run)
            results.append((account["account_id"], success))
            print()

        if not dry_run:
            # Wait for connections to establish
            print("⏳ Waiting 10 seconds for accounts to connect...")
            await asyncio.sleep(10)
            print()

            # Verify connections
            print("🔍 Verifying account connections...")
            print()

            for account_id, _ in results:
                await verify_account(client, account_id)
                print()

    # Summary
    print("=" * 80)
    print("📊 SETUP SUMMARY")
    print("=" * 80)

    if dry_run:
        print("⚠️  Dry-run completed. No changes were made.")
    else:
        success_count = sum(1 for _, success in results if success)
        print(f"✅ Successfully created: {success_count}/{len(ACCOUNTS)} accounts")

        if success_count == len(ACCOUNTS):
            print()
            print("🎉 All accounts configured successfully!")
            print()
            print("Next steps:")
            print("  1. Verify webhooks: python scripts/configure_emailengine_webhooks.py")
            print("  2. Test email reception: Send test emails to each account")
            print("  3. Check consumer logs: docker compose logs -f email-consumer")
        else:
            print()
            print("⚠️  Some accounts failed to configure. Check logs above.")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
