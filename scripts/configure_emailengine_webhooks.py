#!/usr/bin/env python3
"""
[DEPRECATED D25 - 2026-02-13] EmailEngine retiré. Ce script n'est plus utilisé.
Remplacé par: agents/src/adapters/email.py (IMAP direct)

Configure EmailEngine Webhooks - Story 2.1 Task 2.4
Configure webhooks pour les 4 comptes IMAP → Gateway endpoint

Usage:
    python scripts/configure_emailengine_webhooks.py [--dry-run]

Prérequis:
    - EmailEngine running avec 4 comptes configurés (setup_emailengine_accounts.py)
    - Gateway running sur http://localhost:8000 (ou GATEWAY_URL env var)
    - WEBHOOK_SECRET dans .env
"""

import asyncio
import httpx
import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# Configuration
# ============================================

EMAILENGINE_URL = os.getenv('EMAILENGINE_BASE_URL', 'http://localhost:3000')
EMAILENGINE_SECRET = os.getenv('EMAILENGINE_SECRET')
GATEWAY_URL = os.getenv('GATEWAY_URL', 'http://gateway:8000')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')

ACCOUNTS = ['account-medical', 'account-faculty', 'account-research', 'account-personal']

if not EMAILENGINE_SECRET:
    logger.error("❌ EMAILENGINE_SECRET not set")
    sys.exit(1)

if not WEBHOOK_SECRET:
    logger.error("❌ WEBHOOK_SECRET not set")
    sys.exit(1)


# ============================================
# Functions
# ============================================

async def configure_webhook(
    client: httpx.AsyncClient,
    account_id: str,
    dry_run: bool = False
) -> bool:
    """
    Configure webhook pour un compte EmailEngine

    Args:
        client: HTTP client
        account_id: ID du compte (account-medical, etc.)
        dry_run: Mode test (pas d'appel API)

    Returns:
        True si succès, False si échec
    """
    webhook_url = f"{GATEWAY_URL}/api/v1/webhooks/emailengine/{account_id}"

    logger.info(f"📧 Configuring webhook for {account_id}")
    logger.info(f"   URL: {webhook_url}")

    if dry_run:
        logger.info(f"🔵 [DRY-RUN] Would configure webhook for {account_id}")
        return True

    # Payload webhook EmailEngine API
    payload = {
        'url': webhook_url,
        'events': ['messageNew'],  # Événement: nouvel email
        'enabled': True
    }

    try:
        response = await client.post(
            f'{EMAILENGINE_URL}/v1/account/{account_id}/webhooks',
            json=payload,
            headers={'Authorization': f'Bearer {EMAILENGINE_SECRET}'},
            timeout=10.0
        )

        if response.status_code in [200, 201]:
            logger.info(f"✅ Webhook configured for {account_id}")
            return True
        else:
            logger.error(
                f"❌ Failed to configure webhook for {account_id}: "
                f"HTTP {response.status_code} - {response.text}"
            )
            return False

    except Exception as e:
        logger.error(f"❌ Error configuring webhook for {account_id}: {e}")
        return False


async def verify_webhook(
    client: httpx.AsyncClient,
    account_id: str,
    dry_run: bool = False
) -> bool:
    """Vérifie qu'un webhook est configuré"""
    if dry_run:
        logger.info(f"🔵 [DRY-RUN] Would verify webhook for {account_id}")
        return True

    try:
        response = await client.get(
            f'{EMAILENGINE_URL}/v1/account/{account_id}/webhooks',
            headers={'Authorization': f'Bearer {EMAILENGINE_SECRET}'},
            timeout=10.0
        )

        if response.status_code == 200:
            webhooks = response.json()
            if len(webhooks) > 0:
                logger.info(f"✅ {len(webhooks)} webhook(s) configured for {account_id}")
                return True
            else:
                logger.warning(f"⚠️  No webhooks found for {account_id}")
                return False
        else:
            logger.error(f"❌ Failed to verify webhook for {account_id}")
            return False

    except Exception as e:
        logger.error(f"❌ Error verifying webhook for {account_id}: {e}")
        return False


async def main(dry_run: bool = False):
    """Main entry point"""
    logger.info("🚀 Starting EmailEngine webhook configuration...")

    if dry_run:
        logger.info("🔵 DRY-RUN mode enabled")

    async with httpx.AsyncClient() as client:
        success_count = 0
        failed_accounts = []

        for account_id in ACCOUNTS:
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {account_id}")
            logger.info(f"{'='*60}")

            # Configure webhook
            configured = await configure_webhook(client, account_id, dry_run)

            if not configured:
                failed_accounts.append(account_id)
                continue

            # Verify webhook
            verified = await verify_webhook(client, account_id, dry_run)

            if verified:
                success_count += 1

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"Configuration complete!")
    logger.info(f"{'='*60}")
    logger.info(f"✅ Successfully configured: {success_count}/{len(ACCOUNTS)} accounts")

    if failed_accounts:
        logger.error(f"❌ Failed accounts: {', '.join(failed_accounts)}")
        sys.exit(1)
    else:
        logger.info("🎉 All webhooks configured successfully!")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Configure EmailEngine webhooks')
    parser.add_argument('--dry-run', action='store_true', help='Test mode')
    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run))
