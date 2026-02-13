#!/bin/bash
# verify_env.sh - Vérifier que toutes les variables d'environnement requises sont définies
#
# Usage: ./scripts/verify_env.sh [--env-file .env]

set -euo pipefail

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Variables d'environnement requises
REQUIRED_VARS=(
  "TELEGRAM_BOT_TOKEN"
  "TELEGRAM_CHAT_ID"
  "ANTHROPIC_API_KEY"
  "POSTGRES_PASSWORD"
  "REDIS_PASSWORD"
  "DATABASE_URL"
)

# Variables optionnelles (warning si manquant)
OPTIONAL_VARS=(
  "BENCHMARK_BUDGET_USD"
  "TAILSCALE_PC_HOSTNAME"
  "VPS_TIER"
)

# Charger fichier .env si fourni
if [[ "${1:-}" == "--env-file" ]] && [[ -n "${2:-}" ]]; then
    ENV_FILE="$2"
    if [[ -f "$ENV_FILE" ]]; then
        echo "📄 Chargement de $ENV_FILE..."
        set -a
        source "$ENV_FILE"
        set +a
    else
        echo -e "${RED}❌ Fichier $ENV_FILE introuvable${NC}"
        exit 1
    fi
fi

# Fonction : Vérifier une variable
check_var() {
    local var_name="$1"
    local var_value="${!var_name:-}"

    if [[ -z "$var_value" ]]; then
        return 1
    else
        return 0
    fi
}

# Main
main() {
    echo "🔐 Friday 2.0 - Vérification variables d'environnement"
    echo "======================================================"
    echo ""

    local missing_count=0
    local warning_count=0

    # Vérifier variables requises
    echo "📋 Variables REQUISES :"
    echo "-----------------------"
    for var in "${REQUIRED_VARS[@]}"; do
        if check_var "$var"; then
            echo -e "${GREEN}✓${NC} $var (définie)"
        else
            echo -e "${RED}✗${NC} $var (MANQUANTE)"
            ((missing_count++))
        fi
    done

    echo ""
    echo "📋 Variables OPTIONNELLES :"
    echo "---------------------------"
    for var in "${OPTIONAL_VARS[@]}"; do
        if check_var "$var"; then
            echo -e "${GREEN}✓${NC} $var (définie)"
        else
            echo -e "${YELLOW}⚠${NC} $var (manquante - optionnelle)"
            ((warning_count++))
        fi
    done

    echo ""
    echo "======================================================"

    if [[ $missing_count -eq 0 ]]; then
        echo -e "${GREEN}✅ Toutes les variables requises sont définies !${NC}"

        if [[ $warning_count -gt 0 ]]; then
            echo -e "${YELLOW}⚠️  $warning_count variable(s) optionnelle(s) manquante(s)${NC}"
        fi

        exit 0
    else
        echo -e "${RED}❌ $missing_count variable(s) manquante(s)${NC}"
        echo ""
        echo "💡 Comment les obtenir :"
        echo "   - TELEGRAM_BOT_TOKEN    : @BotFather sur Telegram"
        echo "   - TELEGRAM_CHAT_ID      : @userinfobot sur Telegram"
        echo "   - ANTHROPIC_API_KEY     : https://console.anthropic.com/"
        echo "   - POSTGRES_PASSWORD     : Générer : openssl rand -base64 32"
        echo "   - REDIS_PASSWORD        : Générer : openssl rand -base64 32"
        echo "   - DATABASE_URL          : postgresql://user:password@host:5432/dbname"
        echo ""
        echo "📚 Guide complet : docs/secrets-management.md"
        exit 1
    fi
}

main "$@"
