#!/usr/bin/env python3
"""
scripts/anonymize_names.py
Remove personal name references from codebase for public release
"""

import re
from pathlib import Path

# Replacements map (pattern → replacement)
REPLACEMENTS = {
    # README.md specific
    ("README.md", r"owner \(extension famille"): r"Utilisateur principal (extension famille",
    ("README.md", r"owner"): "Mainteneur",

    # LICENSE
    ("LICENSE", r"Copyright \(c\) 2026 owner"): "Copyright (c) 2026 Friday 2.0 Project",

    # SECURITY.md
    ("SECURITY.md", r"owner Lopez"): "Friday 2.0 Maintainer",
    ("SECURITY.md", r"mainteneur@exemple\.com"): "security@friday-project.example.com",
    ("SECURITY.md", r"\[mainteneur@exemple\.com\]\(mailto:mainteneur@exemple\.com\)"): "[security contact](mailto:security@friday-project.example.com)",
    ("SECURITY.md", r"owner"): "Mainteneur",

    # .sops.yaml
    (".sops.yaml", r"# Clé publique owner"): "# Clé publique mainteneur",

    # .env.example
    (".env.example", r"OWNER_USER_ID"): "OWNER_USER_ID",
    (".env.example", r"# ID utilisateur owner"): "# ID utilisateur principal",

    # CLAUDE.md
    ("CLAUDE.md", r"owner est francophone"): "Utilisateur francophone",
    ("CLAUDE.md", r"owner"): "Mainteneur",

    # Config YAML
    ("config/telegram.yaml", r"user_name: owner"): "user_name: Mainteneur",
    ("config/telegram.yaml", r"owner"): "Mainteneur",

    # Docs
    ("*.md", r"\*\*owner\*\*"): "**Mainteneur**",
    ("*.md", r"owner \("): "Mainteneur (",
    ("*.md", r", owner"): ", Mainteneur",
}

def anonymize_file(file_path: Path, patterns: list[tuple[str, str]]):
    """Apply anonymization patterns to a file"""
    try:
        content = file_path.read_text(encoding='utf-8')
        original = content

        for pattern, replacement in patterns:
            content = re.sub(pattern, replacement, content)

        if content != original:
            file_path.write_text(content, encoding='utf-8')
            print(f"[OK] {file_path.relative_to(Path.cwd())}")
            return True
    except Exception as e:
        print(f"[ERR] {file_path}: {e}")
    return False

def main():
    root = Path(__file__).parent.parent
    changed = 0

    print("Anonymizing personal references in codebase...\n")

    # Group replacements by file pattern
    file_patterns = {}
    for (file_pattern, regex), replacement in REPLACEMENTS.items():
        if file_pattern not in file_patterns:
            file_patterns[file_pattern] = []
        file_patterns[file_pattern].append((regex, replacement))

    # Process specific files
    for file_pattern, patterns in file_patterns.items():
        if "*" not in file_pattern:
            # Exact file
            file_path = root / file_pattern
            if file_path.exists():
                if anonymize_file(file_path, patterns):
                    changed += 1
        else:
            # Glob pattern
            for file_path in root.rglob(file_pattern):
                if ".git" not in str(file_path) and "_bmad" not in str(file_path):
                    if anonymize_file(file_path, patterns):
                        changed += 1

    # Additional generic replacements for Python, SQL, etc.
    print("\nProcessing code files...")

    # Python files (except test fixtures)
    for py_file in root.rglob("*.py"):
        if ".git" not in str(py_file) and "_bmad" not in str(py_file) and "fixtures" not in str(py_file):
            patterns = [(r"owner", "owner")]
            if anonymize_file(py_file, patterns):
                changed += 1

    # SQL migrations
    for sql_file in (root / "database" / "migrations").glob("*.sql"):
        patterns = [(r"owner", "owner"), (r"'owner'", "'owner'")]
        if anonymize_file(sql_file, patterns):
            changed += 1

    print(f"\nAnonymization complete: {changed} files updated")
    print("Review changes with: git diff")

if __name__ == "__main__":
    main()
