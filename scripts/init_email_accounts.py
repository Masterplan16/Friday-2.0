#!/usr/bin/env python3
"""
Script d'initialisation des comptes email dans ingestion.email_accounts.

Lit les variables d'environnement IMAP_ACCOUNT_* et insère les comptes dans PostgreSQL.
Le trigger encrypt_imap_password() va automatiquement chiffrer les passwords avec pgcrypto.

Usage:
    # Sur VPS (après avoir déchiffré .env.enc)
    python scripts/init_email_accounts.py

Prérequis:
    - PostgreSQL accessible (DATABASE_URL dans .env)
    - Variables IMAP_ACCOUNT_* définies dans .env
    - Migration 027 (email_accounts table) appliquée

Date: 2026-02-14
"""

import asyncio
import os
import sys

import asyncpg
from dotenv import load_dotenv


async def main():
    """Initialize email accounts in database."""

    # Load environment variables
    load_dotenv()

    # Database connection
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ ERROR: DATABASE_URL not set in environment")
        sys.exit(1)

    print(f"📡 Connecting to database...")
    try:
        conn = await asyncpg.connect(database_url)
        print("✅ Connected to database")
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        sys.exit(1)

    # Email accounts configuration from environment
    # Format: IMAP_ACCOUNT_{LABEL}_{FIELD}
    accounts = {
        "gmail1": {
            "account_id": "account_gmail1",
            "label": "Gmail 1",
        },
        "gmail2": {
            "account_id": "account_gmail2",
            "label": "Gmail 2",
        },
        "proton": {
            "account_id": "account_protonmail",
            "label": "ProtonMail",
        },
        "universite": {
            "account_id": "account_universite",
            "label": "Université",
        },
    }

    inserted_count = 0
    skipped_count = 0
    error_count = 0

    for key, config in accounts.items():
        account_id = config["account_id"]
        label = config["label"]

        # Read environment variables for this account
        env_prefix = f"IMAP_ACCOUNT_{key.upper()}"

        email = os.getenv(f"{env_prefix}_EMAIL")
        imap_host = os.getenv(f"{env_prefix}_IMAP_HOST", "imap.gmail.com")
        imap_port = int(os.getenv(f"{env_prefix}_IMAP_PORT", "993"))
        imap_user = os.getenv(f"{env_prefix}_IMAP_USER", email)  # Default to email
        imap_password = os.getenv(f"{env_prefix}_IMAP_PASSWORD")
        smtp_host = os.getenv(f"{env_prefix}_SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv(f"{env_prefix}_SMTP_PORT", "587"))

        # Validation
        if not email:
            print(f"⚠️  SKIP {label}: {env_prefix}_EMAIL not set")
            skipped_count += 1
            continue

        if not imap_password:
            print(f"⚠️  SKIP {label}: {env_prefix}_IMAP_PASSWORD not set")
            skipped_count += 1
            continue

        # Check if account already exists
        existing = await conn.fetchrow(
            "SELECT account_id FROM ingestion.email_accounts WHERE account_id = $1", account_id
        )

        if existing:
            print(f"⏭️  SKIP {label} ({email}): already exists")
            skipped_count += 1
            continue

        # Insert account
        try:
            # Determine auth_method and use_idle based on provider
            use_idle = True
            auth_method = "app_password"

            if "proton" in key.lower():
                # ProtonMail Bridge doesn't support IDLE
                use_idle = False

            await conn.execute(
                """
                INSERT INTO ingestion.email_accounts (
                    account_id, email, imap_host, imap_port, imap_user,
                    imap_password_encrypted, smtp_host, smtp_port,
                    use_idle, auth_method, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                account_id,
                email,
                imap_host,
                imap_port,
                imap_user,
                imap_password.encode("utf-8"),  # Trigger will encrypt with pgcrypto
                smtp_host,
                smtp_port,
                use_idle,
                auth_method,
                "disconnected",  # Initial status
            )

            print(f"✅ INSERTED {label} ({email})")
            print(f"   - IMAP: {imap_host}:{imap_port}")
            print(f"   - SMTP: {smtp_host}:{smtp_port}")
            print(f"   - IDLE: {use_idle}")
            print(f"   - Auth: {auth_method}")
            inserted_count += 1

        except Exception as e:
            print(f"❌ ERROR {label} ({email}): {e}")
            error_count += 1

    # Close connection
    await conn.close()

    # Summary
    print("\n" + "=" * 60)
    print(f"📊 Summary:")
    print(f"   ✅ Inserted: {inserted_count}")
    print(f"   ⏭️  Skipped:  {skipped_count}")
    print(f"   ❌ Errors:   {error_count}")
    print("=" * 60)

    if error_count > 0:
        sys.exit(1)

    print("\n✅ Email accounts initialization complete!")


if __name__ == "__main__":
    asyncio.run(main())
