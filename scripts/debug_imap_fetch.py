#!/usr/bin/env python3
"""Debug: inspecte le format de reponse aioimaplib.fetch() pour comprendre la structure."""

import asyncio
import os
import ssl
import sys
import aioimaplib


async def main():
    host = os.getenv("IMAP_ACCOUNT_GMAIL1_IMAP_HOST", "imap.gmail.com")
    port = int(os.getenv("IMAP_ACCOUNT_GMAIL1_IMAP_PORT", "993"))
    user = os.getenv("IMAP_ACCOUNT_GMAIL1_IMAP_USER", os.getenv("IMAP_ACCOUNT_GMAIL1_EMAIL", ""))
    pwd = os.getenv("IMAP_ACCOUNT_GMAIL1_IMAP_PASSWORD", "")

    if not user or not pwd:
        print("ERROR: IMAP credentials not set")
        sys.exit(1)

    ctx = ssl.create_default_context()
    imap = aioimaplib.IMAP4_SSL(host=host, port=port, ssl_context=ctx)
    await imap.wait_hello_from_server()
    await imap.login(user, pwd)
    await imap.select("INBOX")

    # Search recent emails
    result = await imap.search("SINCE 14-Feb-2026")
    print(f"=== SEARCH result ===")
    print(f"  type(result) = {type(result)}")
    print(f"  result = {result}")
    if hasattr(result, 'result'):
        print(f"  result.result = {result.result}")
    if hasattr(result, 'lines'):
        print(f"  result.lines = {result.lines}")
        for i, line in enumerate(result.lines):
            print(f"    line[{i}] type={type(line)} repr={repr(line)[:200]}")

    # Get first seq_num
    status = result.result if hasattr(result, 'result') else result[0]
    lines = result.lines if hasattr(result, 'lines') else result[1]
    seq_nums = []
    if status == "OK":
        for line in lines:
            if isinstance(line, (bytes, bytearray)):
                line = line.decode("utf-8", errors="replace")
            if isinstance(line, str):
                for part in line.split():
                    if part.isdigit():
                        seq_nums.append(part)

    if not seq_nums:
        print("No emails found")
        await imap.logout()
        return

    print(f"\nFound {len(seq_nums)} seq_nums: {seq_nums[:5]}...")

    # Fetch first email
    seq = seq_nums[0]
    print(f"\n=== FETCH seq_num={seq} ===")
    fetch_result = await imap.fetch(seq, "(UID BODY.PEEK[] INTERNALDATE)")
    print(f"  type(fetch_result) = {type(fetch_result)}")
    print(f"  fetch_result.result = {fetch_result.result}")
    print(f"  len(fetch_result.lines) = {len(fetch_result.lines)}")

    for i, item in enumerate(fetch_result.lines):
        t = type(item).__name__
        if isinstance(item, bytes):
            preview = repr(item[:300])
            print(f"  lines[{i}] type=bytes len={len(item)} preview={preview}")
        elif isinstance(item, bytearray):
            preview = repr(bytes(item)[:300])
            print(f"  lines[{i}] type=bytearray len={len(item)} preview={preview}")
        elif isinstance(item, str):
            print(f"  lines[{i}] type=str repr={repr(item)[:300]}")
        elif isinstance(item, tuple):
            print(f"  lines[{i}] type=tuple len={len(item)}")
            for j, sub in enumerate(item):
                st = type(sub).__name__
                if isinstance(sub, (bytes, bytearray)):
                    preview = repr(bytes(sub)[:300])
                    print(f"    [{j}] type={st} len={len(sub)} preview={preview}")
                else:
                    print(f"    [{j}] type={st} repr={repr(sub)[:300]}")
        else:
            print(f"  lines[{i}] type={t} repr={repr(item)[:300]}")

    await imap.logout()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
