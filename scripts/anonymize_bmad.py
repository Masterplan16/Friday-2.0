#!/usr/bin/env python3
"""
Anonymize personal references in _bmad files for public release
"""

import re
from pathlib import Path


def anonymize_file(file_path: Path) -> bool:
    """Apply anonymization to a file"""
    try:
        content = file_path.read_text(encoding='utf-8')
        original = content

        # Replace Antonio with Mainteneur (preserve case)
        content = re.sub(r'\bAntonio\b', 'Mainteneur', content)
        content = re.sub(r'\bantonio\b', 'mainteneur', content)

        # Replace ANTONIO_USER_ID with OWNER_USER_ID
        content = re.sub(r'\bANTONIO_USER_ID\b', 'OWNER_USER_ID', content)

        # Replace user_name: Antonio in YAML
        content = re.sub(r'user_name:\s*Antonio', 'user_name: Mainteneur', content)

        # Replace "Antonio est francophone" pattern
        content = re.sub(r'Antonio est francophone', 'Mainteneur est francophone', content)

        if content != original:
            file_path.write_text(content, encoding='utf-8')
            rel_path = file_path.relative_to(Path.cwd())
            print(f"[OK] {rel_path}")
            return True

        return False

    except Exception as e:
        print(f"[ERR] {file_path}: {e}")
        return False


def main():
    root = Path(__file__).parent.parent
    changed = 0

    print("Anonymizing _bmad files...\n")

    # Process all .md and .yaml files in _bmad directories
    for pattern in ['_bmad/**/*.md', '_bmad/**/*.yaml', '_bmad-output/**/*.md', '_bmad-output/**/*.yaml']:
        for file_path in root.glob(pattern):
            if anonymize_file(file_path):
                changed += 1

    print(f"\n[OK] Anonymization complete: {changed} files updated")
    print("Review changes with: git diff")


if __name__ == "__main__":
    main()
