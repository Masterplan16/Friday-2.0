#!/usr/bin/env python3
"""
Compare count EmailEngine API REST vs PostgreSQL pour periode donnee.
Detecte emails manquants (timeout reseau, crash, etc.)
Note : EmailEngine n'a PAS de SDK Python — on utilise httpx sur l'API REST.

Story 2.9 - Validation integrite migration.

Usage:
    python scripts/validate_migration.py --since 2026-01-01
    python scripts/validate_migration.py --since 2025-01-01 --until 2025-12-31
"""

import argparse
import asyncio
import os
import sys

import asyncpg
import httpx

EMAILENGINE_URL = os.getenv("EMAILENGINE_URL", "http://localhost:3000")
EMAILENGINE_TOKEN = os.getenv("EMAILENGINE_ACCESS_TOKEN")


async def count_emailengine_messages(
    client: httpx.AsyncClient, since: str, until: str | None = None
) -> int:
    """Count messages via EmailEngine REST API (GET /v1/accounts/{id}/messages)."""
    total = 0
    accounts_resp = await client.get(
        f"{EMAILENGINE_URL}/v1/accounts",
        headers={"Authorization": f"Bearer {EMAILENGINE_TOKEN}"},
    )
    accounts_resp.raise_for_status()

    for account in accounts_resp.json().get("accounts", []):
        account_id = account["account"]
        params: dict = {"path": "INBOX", "pageSize": 0}
        if since:
            params["since"] = since
        if until:
            params["until"] = until

        resp = await client.get(
            f"{EMAILENGINE_URL}/v1/account/{account_id}/messages",
            headers={"Authorization": f"Bearer {EMAILENGINE_TOKEN}"},
            params=params,
        )
        resp.raise_for_status()
        total += resp.json().get("total", 0)

    return total


async def validate_migration(since: str, until: str | None = None) -> bool:
    """Compare counts EmailEngine vs PostgreSQL."""
    if not EMAILENGINE_TOKEN:
        print("ERROR: EMAILENGINE_ACCESS_TOKEN not set")
        return False

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        return False

    # Count EmailEngine API
    async with httpx.AsyncClient(timeout=30) as client:
        ee_count = await count_emailengine_messages(client, since, until)

    # Count PostgreSQL
    db = await asyncpg.connect(database_url)
    query = "SELECT COUNT(*) FROM ingestion.emails WHERE received_at >= $1::date"
    params: list = [since]

    if until:
        query += " AND received_at <= $2::date"
        params.append(until)

    pg_count = await db.fetchval(query, *params)
    await db.close()

    # Compare
    diff = ee_count - pg_count
    diff_pct = (diff / ee_count * 100) if ee_count > 0 else 0

    print(f"\n{'=' * 40}")
    print(f"Validation migration")
    print(f"{'=' * 40}")
    print(f"Periode     : {since} -> {until or 'now'}")
    print(f"EmailEngine : {ee_count} emails")
    print(f"PostgreSQL  : {pg_count} emails")
    print(f"Difference  : {diff} emails ({diff_pct:.1f}%)")

    if abs(diff_pct) > 5:
        print(f"\nWARNING: >5% difference - investigate!")
        return False
    else:
        print(f"\nIntegrity check PASSED")
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate migration integrity")
    parser.add_argument("--since", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--until", default=None, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()
    success = asyncio.run(validate_migration(args.since, args.until))
    sys.exit(0 if success else 1)
