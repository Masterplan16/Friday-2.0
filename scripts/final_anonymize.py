#!/usr/bin/env python3
"""Final complete anonymization"""

import re
from pathlib import Path


def anonymize(file_path):
    try:
        content = file_path.read_text(encoding="utf-8")
        original = content

        # Replace all variations
        content = re.sub(r"\bAntonio\b", "Mainteneur", content)
        content = re.sub(r"\bantonio\b", "mainteneur", content)
        content = re.sub(r"\bANTONIO_USER_ID\b", "OWNER_USER_ID", content)

        if content != original:
            file_path.write_text(content, encoding="utf-8")
            print(f"[OK] {file_path.relative_to(Path.cwd())}")
            return True
    except Exception as e:
        pass
    return False


root = Path(__file__).parent.parent
changed = 0

# Process all files except _bmad and .venv
for pattern in [
    "**/*.md",
    "**/*.py",
    "**/*.sql",
    "**/*.yaml",
    "**/*.yml",
    "**/*.sh",
    "**/*.example",
    "**/docker-compose.yml",
]:
    for f in root.glob(pattern):
        if ".git" not in str(f) and "_bmad" not in str(f) and ".venv" not in str(f):
            if anonymize(f):
                changed += 1

print(f"\nTotal: {changed} files updated")
