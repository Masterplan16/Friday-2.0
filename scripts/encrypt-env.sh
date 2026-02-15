#!/bin/bash
# encrypt-env.sh - Chiffrer .env en .env.enc
#
# IMPORTANT: Ne JAMAIS utiliser "sops -e .env > .env.enc" directement.
# Utiliser ce script pour garantir le bon format.
#
# Usage:
#   ./scripts/encrypt-env.sh              # Chiffre .env -> .env.enc
#   ./scripts/encrypt-env.sh --from-vps   # Recupere .env du VPS et chiffre

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"
ENC_FILE="$PROJECT_ROOT/.env.enc"

case "${1:-}" in
    --from-vps)
        echo "Recuperation .env depuis VPS..."
        scp friday-vps:/opt/friday/.env "$ENV_FILE"
        echo "Recupere: $ENV_FILE"
        ;;
esac

if [ ! -f "$ENV_FILE" ]; then
    echo "ERREUR: $ENV_FILE introuvable"
    echo "Creez le fichier .env ou utilisez --from-vps"
    exit 1
fi

# Convertir CRLF -> LF (Windows -> Unix) si necessaire
sed -i 's/\r$//' "$ENV_FILE" 2>/dev/null || true

# Verifier que le fichier n'est pas deja chiffre
if grep -q "ENC\[AES256_GCM" "$ENV_FILE"; then
    echo "ERREUR: $ENV_FILE semble deja chiffre (contient ENC[AES256_GCM)"
    exit 1
fi

# Verifier que ANTHROPIC_API_KEY n'est pas un placeholder
API_KEY=$(grep ANTHROPIC_API_KEY "$ENV_FILE" | cut -d= -f2)
if echo "$API_KEY" | grep -qi "placeholder"; then
    echo "ERREUR: ANTHROPIC_API_KEY contient 'placeholder' !"
    echo "Corrigez la cle avant de chiffrer."
    exit 1
fi

# Backup ancien .env.enc
if [ -f "$ENC_FILE" ]; then
    cp "$ENC_FILE" "${ENC_FILE}.bak"
    echo "Backup: ${ENC_FILE}.bak"
fi

# Chiffrer
sops -e "$ENV_FILE" > "$ENC_FILE"
echo "OK: $ENC_FILE cree"

# Verifier round-trip
echo "Verification round-trip..."
sops --input-type dotenv --output-type dotenv -d "$ENC_FILE" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "OK: Round-trip verifie"
else
    echo "ERREUR: Le fichier chiffre ne peut pas etre dechiffre !"
    echo "Restauration du backup..."
    mv "${ENC_FILE}.bak" "$ENC_FILE"
    exit 1
fi

# Supprimer .env en clair
rm -f "$ENV_FILE"
echo "Fichier .env supprime (securite)"
echo ""
echo "IMPORTANT: Committer .env.enc dans git"
