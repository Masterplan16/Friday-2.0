#!/usr/bin/env python3
"""Count emails per account for a date range."""

import asyncio, os, ssl, aioimaplib


async def main():
    accounts = []
    seen = set()
    for key, value in sorted(os.environ.items()):
        if key.startswith("IMAP_ACCOUNT_") and key.endswith("_EMAIL"):
            raw_id = key.replace("IMAP_ACCOUNT_", "").replace("_EMAIL", "")
            account_id = "account_" + raw_id.lower()
            if account_id in seen:
                continue
            seen.add(account_id)
            prefix = "IMAP_ACCOUNT_" + raw_id
            accounts.append(
                {
                    "account_id": account_id,
                    "imap_host": os.getenv(prefix + "_IMAP_HOST", ""),
                    "imap_port": int(os.getenv(prefix + "_IMAP_PORT", "993")),
                    "imap_user": os.getenv(prefix + "_IMAP_USER", value),
                    "imap_password": os.getenv(prefix + "_IMAP_PASSWORD", ""),
                }
            )

    total = 0
    for acc in accounts:
        ctx = ssl.create_default_context()
        if "proton" in acc["account_id"]:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        try:
            imap = aioimaplib.IMAP4_SSL(
                host=acc["imap_host"], port=acc["imap_port"], ssl_context=ctx
            )
            await imap.wait_hello_from_server()
            await imap.login(acc["imap_user"], acc["imap_password"])
            await imap.select("INBOX")
            result = await imap.search("SINCE 01-Jan-2026")
            nums = []
            for line in result.lines:
                if isinstance(line, bytes):
                    line = line.decode()
                for p in line.split():
                    if p.isdigit():
                        nums.append(p)
            count = len(nums)
            print(f"{acc['account_id']}: {count} emails")
            total += count
            await imap.logout()
        except Exception as e:
            print(f"{acc['account_id']}: ERROR {e}")
    print(f"TOTAL: {total}")


asyncio.run(main())
