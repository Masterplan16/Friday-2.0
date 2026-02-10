#!/usr/bin/env bash
# scripts/anonymize-names.sh
# Remove personal name references from codebase

set -euo pipefail

echo "Anonymizing personal references in codebase..."

# Files to process (excluding _bmad internal docs)
FILES=(
    "README.md"
    "SECURITY.md"
    ".sops.yaml"
    ".env.example"
    "CLAUDE.md"
    "docs/*.md"
    "config/*.yaml"
    "bot/**/*.py"
    "agents/**/*.py"
    "services/**/*.py"
    "scripts/**/*.py"
    "database/migrations/*.sql"
)

# Replacements
# Antonio → Mainteneur (in French contexts)
# Antonio → Maintainer (in English contexts)
# ANTONIO_USER_ID → OWNER_USER_ID
# antonio@exemple.com → contact@ address ou removal

# Process README.md
sed -i.bak 's/Antonio (extension famille/Utilisateur principal (extension famille/g' README.md
sed -i.bak 's/Antonio/Mainteneur/g' README.md

# Process SECURITY.md
sed -i.bak 's/Antonio Lopez/Friday 2.0 Maintainer/g' SECURITY.md
sed -i.bak 's/antonio@exemple\.com/security@friday-project.example.com/g' SECURITY.md
sed -i.bak 's/Antonio/Mainteneur/g' SECURITY.md

# Process .sops.yaml
sed -i.bak 's/# Clé publique Antonio/# Clé publique mainteneur/g' .sops.yaml

# Process .env.example
sed -i.bak 's/ANTONIO_USER_ID/OWNER_USER_ID/g' .env.example
sed -i.bak 's/# ID utilisateur Antonio/# ID utilisateur principal/g' .env.example

# Process CLAUDE.md
sed -i.bak 's/Antonio/Mainteneur/g' CLAUDE.md

# Process config files
find config -name "*.yaml" -type f -exec sed -i.bak 's/user_name: Antonio/user_name: Mainteneur/g' {} \;
find config -name "*.yaml" -type f -exec sed -i.bak 's/Antonio/Mainteneur/g' {} \;

# Process Python files
find bot agents services scripts -name "*.py" -type f -exec sed -i.bak 's/Antonio/Owner/g' {} \;

# Process docs
find docs -name "*.md" -type f -exec sed -i.bak 's/Antonio/Mainteneur/g' {} \;

# Process SQL migrations
find database/migrations -name "*.sql" -type f -exec sed -i.bak 's/Antonio/owner/g' {} \;

# Clean up backup files
find . -name "*.bak" -type f -delete

echo "✅ Anonymization complete"
echo "Files processed. Review changes with: git diff"
