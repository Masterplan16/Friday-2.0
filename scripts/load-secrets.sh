#!/usr/bin/env bash
# scripts/load-secrets.sh
# Déchiffre .env.enc et charge les secrets dans l'environnement
# Usage: source ./scripts/load-secrets.sh OU ./scripts/load-secrets.sh && source .env

set -euo pipefail

# Couleurs pour output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SOPS_AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.age/friday-key.txt}"
ENV_ENC_FILE=".env.enc"
ENV_FILE=".env"

# Vérifier que la clé privée age existe
if [ ! -f "$SOPS_AGE_KEY_FILE" ]; then
    echo -e "${RED}❌ Clé privée age introuvable: $SOPS_AGE_KEY_FILE${NC}"
    echo -e "${YELLOW}💡 Génére une clé avec: age-keygen -o ~/.age/friday-key.txt${NC}"
    exit 1
fi

# Vérifier que .env.enc existe
if [ ! -f "$ENV_ENC_FILE" ]; then
    echo -e "${RED}❌ Fichier chiffré introuvable: $ENV_ENC_FILE${NC}"
    echo -e "${YELLOW}💡 Chiffre d'abord .env avec: ./scripts/encrypt-env.sh${NC}"
    exit 1
fi

# Déchiffrer .env.enc → .env
echo -e "${GREEN}🔓 Déchiffrement des secrets...${NC}"
export SOPS_AGE_KEY_FILE
sops --input-type dotenv --output-type dotenv -d "$ENV_ENC_FILE" > "$ENV_FILE"

# Vérifier que le déchiffrement a réussi
if [ ! -s "$ENV_FILE" ]; then
    echo -e "${RED}❌ Erreur: .env vide après déchiffrement${NC}"
    rm -f "$ENV_FILE"
    exit 1
fi

echo -e "${GREEN}✅ Secrets déchiffrés dans .env${NC}"
echo -e "${YELLOW}⚠️  N'oubliez pas de supprimer .env après usage: rm .env${NC}"
echo -e "${YELLOW}💡 Pour charger les variables: source .env${NC}"
