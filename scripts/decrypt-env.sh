#!/bin/bash
# decrypt-env.sh - Dechiffrer .env.enc en .env
#
# IMPORTANT: Ne JAMAIS utiliser "sops -d .env.enc" directement.
# L'extension .enc fait que SOPS croit que c'est du JSON -> crash sur les commentaires #.
# Ce script utilise les bons flags --input-type dotenv.
#
# Usage:
#   ./scripts/decrypt-env.sh              # Dechiffre .env.enc -> .env
#   ./scripts/decrypt-env.sh --check      # Verifie que .env.enc est dechiffrable (sans ecrire)
#   ./scripts/decrypt-env.sh --to-vps     # Dechiffre et envoie sur VPS via SCP

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENC_FILE="$PROJECT_ROOT/.env.enc"
OUT_FILE="$PROJECT_ROOT/.env"

if [ ! -f "$ENC_FILE" ]; then
    echo "ERREUR: $ENC_FILE introuvable"
    exit 1
fi

case "${1:-}" in
    --check)
        echo "Verification de $ENC_FILE..."
        sops --input-type dotenv --output-type dotenv -d "$ENC_FILE" > /dev/null 2>&1
        if [ $? -eq 0 ]; then
            echo "OK: .env.enc est dechiffrable"
            # Verifier que la cle API n'est pas un placeholder
            API_KEY=$(sops --input-type dotenv --output-type dotenv -d "$ENC_FILE" | grep ANTHROPIC_API_KEY | cut -d= -f2)
            if echo "$API_KEY" | grep -qi "placeholder"; then
                echo "ATTENTION: ANTHROPIC_API_KEY contient 'placeholder' !"
                exit 1
            fi
            echo "OK: ANTHROPIC_API_KEY presente (finit par ...${API_KEY: -8})"
        else
            echo "ERREUR: .env.enc ne peut pas etre dechiffre"
            exit 1
        fi
        ;;
    --to-vps)
        echo "Dechiffrement et envoi sur VPS..."
        sops --input-type dotenv --output-type dotenv -d "$ENC_FILE" > "$OUT_FILE"
        echo "Dechiffre: $OUT_FILE"
        scp "$OUT_FILE" friday-vps:/opt/friday/.env
        echo "Envoye sur VPS: /opt/friday/.env"
        rm -f "$OUT_FILE"
        echo "Fichier local .env supprime (securite)"
        echo ""
        echo "IMPORTANT: Redemarrer les services sur VPS:"
        echo "  ssh friday-vps 'cd /opt/friday && docker compose --project-name friday-20 up -d'"
        ;;
    *)
        echo "Dechiffrement de .env.enc -> .env"
        sops --input-type dotenv --output-type dotenv -d "$ENC_FILE" > "$OUT_FILE"
        echo "OK: $OUT_FILE cree"
        echo ""
        echo "ATTENTION: .env contient des secrets en clair."
        echo "Ne PAS committer ce fichier. Supprimer apres usage."
        ;;
esac
