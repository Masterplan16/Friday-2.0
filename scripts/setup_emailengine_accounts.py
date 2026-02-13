#!/usr/bin/env python3
"""
[DEPRECATED D25 - 2026-02-13] EmailEngine retiré. Ce script n'est plus utilisé.
Remplacé par: agents/src/adapters/email.py (IMAP direct)

Script setup EmailEngine accounts - Story 2.1 Task 1.3
Configure 4 comptes IMAP dans EmailEngine via API REST

Prérequis:
- EmailEngine container running (docker compose up emailengine)
- Credentials IMAP dans .env (chiffré SOPS)
- PostgreSQL table ingestion.email_accounts (migration 024)

Usage:
    python scripts/setup_emailengine_accounts.py [--dry-run]

Sortie:
    - Crée 4 comptes dans EmailEngine API
    - Stocke account_id dans PostgreSQL ingestion.email_accounts
    - Alerte Telegram si échec

"""

import asyncio
import asyncpg
import httpx
import os
import sys
from pathlib import Path
from typing import Dict, Optional
import logging
import json

# Ajouter repo root au PYTHONPATH pour imports
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


# ============================================
# Configuration Logging
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================
# Configuration EmailEngine
# ============================================

EMAILENGINE_BASE_URL = os.getenv('EMAILENGINE_BASE_URL', 'http://localhost:3000')
EMAILENGINE_SECRET = os.getenv('EMAILENGINE_SECRET')

if not EMAILENGINE_SECRET:
    logger.error("❌ EMAILENGINE_SECRET not set in environment")
    sys.exit(1)


# ============================================
# Configuration 4 Comptes IMAP
# ============================================

# Comptes IMAP à configurer (credentials depuis .env)
IMAP_ACCOUNTS = [
    {
        'account_id': 'account-medical',
        'name': 'Cabinet SELARL (médical)',
        'email': os.getenv('IMAP_MEDICAL_USER'),
        'imap_host': os.getenv('IMAP_MEDICAL_HOST'),
        'imap_port': int(os.getenv('IMAP_MEDICAL_PORT', '993')),
        'imap_user': os.getenv('IMAP_MEDICAL_USER'),
        'imap_password': os.getenv('IMAP_MEDICAL_PASSWORD'),
        'uses_oauth': False,
    },
    {
        'account_id': 'account-faculty',
        'name': 'Faculté (enseignement)',
        'email': os.getenv('IMAP_FACULTY_USER'),
        'imap_host': os.getenv('IMAP_FACULTY_HOST'),
        'imap_port': int(os.getenv('IMAP_FACULTY_PORT', '993')),
        'imap_user': os.getenv('IMAP_FACULTY_USER'),
        'imap_password': os.getenv('IMAP_FACULTY_PASSWORD'),
        'uses_oauth': False,
    },
    {
        'account_id': 'account-research',
        'name': 'Recherche (thèses)',
        'email': os.getenv('IMAP_RESEARCH_USER'),
        'imap_host': os.getenv('IMAP_RESEARCH_HOST'),
        'imap_port': int(os.getenv('IMAP_RESEARCH_PORT', '993')),
        'imap_user': os.getenv('IMAP_RESEARCH_USER'),
        'imap_password': os.getenv('IMAP_RESEARCH_PASSWORD'),
        'uses_oauth': False,
    },
    {
        'account_id': 'account-personal',
        'name': 'Personnel',
        'email': os.getenv('IMAP_PERSONAL_USER'),
        'imap_host': os.getenv('IMAP_PERSONAL_HOST'),
        'imap_port': int(os.getenv('IMAP_PERSONAL_PORT', '993')),
        'imap_user': os.getenv('IMAP_PERSONAL_USER'),
        'imap_password': os.getenv('IMAP_PERSONAL_PASSWORD'),
        'uses_oauth': False,
    },
]


# ============================================
# Functions - EmailEngine API
# ============================================

async def create_emailengine_account(
    client: httpx.AsyncClient,
    account_config: Dict,
    dry_run: bool = False
) -> Optional[str]:
    """
    Crée un compte IMAP dans EmailEngine via API

    Args:
        client: HTTP client asyncio
        account_config: Config compte (account_id, email, imap_host, etc.)
        dry_run: Si True, n'appelle pas l'API (test)

    Returns:
        account_id si succès, None si échec
    """
    account_id = account_config['account_id']
    logger.info(f"📧 Creating EmailEngine account: {account_id} ({account_config['name']})")

    # Validation
    if not account_config['email']:
        logger.error(f"❌ Missing email for {account_id}")
        return None

    if not account_config['imap_password']:
        logger.error(f"❌ Missing IMAP password for {account_id}")
        return None

    if dry_run:
        logger.info(f"🔵 [DRY-RUN] Would create account {account_id}")
        return account_id

    # Payload API EmailEngine
    payload = {
        'account': account_id,
        'name': account_config['name'],
        'email': account_config['email'],
        'imap': {
            'host': account_config['imap_host'],
            'port': account_config['imap_port'],
            'secure': True,  # TLS/SSL
            'auth': {
                'user': account_config['imap_user'],
                'pass': account_config['imap_password'],
            },
        },
        'smtp': False,  # Day 1: IMAP only, SMTP Story 2.6
    }

    # Retry 3x si échec
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            response = await client.post(
                f'{EMAILENGINE_BASE_URL}/v1/account',
                json=payload,
                headers={'Authorization': f'Bearer {EMAILENGINE_SECRET}'},
                timeout=30.0,
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Account {account_id} created: {result.get('state', 'unknown')}")
                return account_id

            elif response.status_code == 409:
                # Account already exists
                logger.warning(f"⚠️  Account {account_id} already exists (409)")
                return account_id

            else:
                logger.error(
                    f"❌ Failed to create {account_id} (attempt {attempt}/{max_retries}): "
                    f"HTTP {response.status_code} - {response.text}"
                )

        except httpx.RequestError as e:
            logger.error(f"❌ Request error for {account_id} (attempt {attempt}/{max_retries}): {e}")

        # Retry backoff: 2s, 4s, 8s
        if attempt < max_retries:
            delay = 2 ** attempt
            logger.info(f"🔄 Retrying in {delay}s...")
            await asyncio.sleep(delay)

    # Max retries exceeded
    logger.error(f"❌ Failed to create {account_id} after {max_retries} attempts")
    return None


async def verify_account_connected(
    client: httpx.AsyncClient,
    account_id: str,
    dry_run: bool = False
) -> bool:
    """
    Vérifie qu'un compte EmailEngine est connected

    Returns:
        True si state=connected, False sinon
    """
    if dry_run:
        logger.info(f"🔵 [DRY-RUN] Would verify {account_id}")
        return True

    try:
        response = await client.get(
            f'{EMAILENGINE_BASE_URL}/v1/account/{account_id}',
            headers={'Authorization': f'Bearer {EMAILENGINE_SECRET}'},
            timeout=10.0,
        )

        if response.status_code == 200:
            data = response.json()
            account_data = data.get('account', {})
            state = account_data.get('state', 'unknown')

            if state == 'connected':
                logger.info(f"✅ Account {account_id} is connected")
                return True
            else:
                logger.warning(f"⚠️  Account {account_id} state: {state}")
                return False
        else:
            logger.error(f"❌ Failed to verify {account_id}: HTTP {response.status_code}")
            return False

    except httpx.RequestError as e:
        logger.error(f"❌ Request error verifying {account_id}: {e}")
        return False


# ============================================
# Functions - PostgreSQL Storage
# ============================================

async def store_account_in_database(
    db: asyncpg.Connection,
    account_config: Dict,
    dry_run: bool = False
) -> bool:
    """
    Stocke account dans PostgreSQL ingestion.email_accounts

    Returns:
        True si succès, False si échec
    """
    account_id = account_config['account_id']

    if dry_run:
        logger.info(f"🔵 [DRY-RUN] Would store {account_id} in database")
        return True

    try:
        # Chiffrer password avec pgcrypto AVANT insert
        # NOTE: Le trigger dans migration 024 devrait gérer ça,
        # mais on fait manuellement ici pour être explicite

        await db.execute(
            """
            INSERT INTO ingestion.email_accounts (
                account_id, email, imap_host, imap_port, imap_user,
                imap_password_encrypted, status, uses_oauth
            ) VALUES (
                $1, $2, $3, $4, $5,
                pgp_sym_encrypt($6::TEXT, current_setting('app.encryption_key')),
                'disconnected', $7
            )
            ON CONFLICT (account_id) DO UPDATE SET
                email = EXCLUDED.email,
                imap_host = EXCLUDED.imap_host,
                imap_port = EXCLUDED.imap_port,
                imap_user = EXCLUDED.imap_user,
                imap_password_encrypted = EXCLUDED.imap_password_encrypted,
                uses_oauth = EXCLUDED.uses_oauth,
                updated_at = CURRENT_TIMESTAMP
            """,
            account_id,
            account_config['email'],
            account_config['imap_host'],
            account_config['imap_port'],
            account_config['imap_user'],
            account_config['imap_password'],
            account_config['uses_oauth'],
        )

        logger.info(f"✅ Account {account_id} stored in database")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to store {account_id} in database: {e}")
        return False


async def update_account_status(
    db: asyncpg.Connection,
    account_id: str,
    status: str,
    dry_run: bool = False
) -> bool:
    """
    Met à jour le status d'un compte dans PostgreSQL

    Args:
        status: connected | disconnected | error | auth_failed
    """
    if dry_run:
        logger.info(f"🔵 [DRY-RUN] Would update {account_id} status to {status}")
        return True

    try:
        await db.execute(
            """
            UPDATE ingestion.email_accounts
            SET status = $1, last_sync = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE account_id = $2
            """,
            status,
            account_id,
        )

        logger.info(f"✅ Account {account_id} status updated: {status}")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to update {account_id} status: {e}")
        return False


# ============================================
# Main Script
# ============================================

async def main(dry_run: bool = False):
    """
    Setup EmailEngine accounts - Main entry point

    Args:
        dry_run: Si True, n'appelle pas les APIs (test)
    """
    logger.info("🚀 Starting EmailEngine accounts setup...")

    if dry_run:
        logger.info("🔵 DRY-RUN mode enabled (no API calls)")

    # Connect to PostgreSQL
    database_url = os.getenv('DATABASE_URL', 'postgresql://friday:friday@localhost:5432/friday')

    try:
        db = await asyncpg.connect(database_url)
        logger.info("✅ Connected to PostgreSQL")
    except Exception as e:
        logger.error(f"❌ Failed to connect to PostgreSQL: {e}")
        sys.exit(1)

    # HTTP client pour EmailEngine API
    async with httpx.AsyncClient() as client:
        success_count = 0
        failed_accounts = []

        for account_config in IMAP_ACCOUNTS:
            account_id = account_config['account_id']
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {account_id}")
            logger.info(f"{'='*60}")

            # Étape 1: Créer compte dans EmailEngine
            created_account_id = await create_emailengine_account(client, account_config, dry_run)

            if not created_account_id:
                logger.error(f"❌ Failed to create {account_id} in EmailEngine")
                failed_accounts.append(account_id)
                continue

            # Étape 2: Vérifier connexion IMAP
            is_connected = await verify_account_connected(client, account_id, dry_run)

            # Étape 3: Stocker dans PostgreSQL
            stored = await store_account_in_database(db, account_config, dry_run)

            if not stored:
                logger.error(f"❌ Failed to store {account_id} in database")
                failed_accounts.append(account_id)
                continue

            # Étape 4: Mettre à jour status
            status = 'connected' if is_connected else 'disconnected'
            await update_account_status(db, account_id, status, dry_run)

            if is_connected:
                success_count += 1
                logger.info(f"✅ {account_id} setup complete")
            else:
                logger.warning(f"⚠️  {account_id} created but not connected")
                failed_accounts.append(account_id)

    # Fermer connexion PostgreSQL
    await db.close()

    # Résumé final
    logger.info(f"\n{'='*60}")
    logger.info(f"Setup complete!")
    logger.info(f"{'='*60}")
    logger.info(f"✅ Successfully configured: {success_count}/{len(IMAP_ACCOUNTS)} accounts")

    if failed_accounts:
        logger.error(f"❌ Failed accounts: {', '.join(failed_accounts)}")
        # TODO Story 2.1: Envoyer alerte Telegram topic System
        sys.exit(1)
    else:
        logger.info("🎉 All accounts configured successfully!")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Setup EmailEngine IMAP accounts')
    parser.add_argument('--dry-run', action='store_true', help='Test mode (no API calls)')
    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run))
