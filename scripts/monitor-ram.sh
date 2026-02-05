#!/bin/bash
# monitor-ram.sh - Monitoring RAM Friday 2.0
#
# Vérifie l'utilisation RAM et alerte via Telegram si dépasse seuil 85%
# Usage: ./scripts/monitor-ram.sh [--telegram]

set -euo pipefail

# Configuration
RAM_ALERT_THRESHOLD_PCT=85
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

# Couleurs
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Fonction : Obtenir RAM totale et utilisée
get_ram_usage() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        total_kb=$(sysctl -n hw.memsize)
        total_gb=$((total_kb / 1024 / 1024 / 1024))

        # Utilisation approximative (pas précis sur macOS)
        used_gb=$(( (total_kb - $(vm_stat | awk '/Pages free/ {print $3}' | sed 's/\.//')*4096) / 1024 / 1024 / 1024 ))
    else
        # Linux
        total_gb=$(free -g | awk '/^Mem:/ {print $2}')
        used_gb=$(free -g | awk '/^Mem:/ {print $3}')
    fi

    echo "$used_gb $total_gb"
}

# Fonction : Envoyer alerte Telegram
send_telegram_alert() {
    local message="$1"

    if [[ -z "$TELEGRAM_BOT_TOKEN" ]] || [[ -z "$TELEGRAM_CHAT_ID" ]]; then
        echo -e "${YELLOW}⚠️  Variables Telegram non configurées. Alerte non envoyée.${NC}"
        return
    fi

    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "text=${message}" \
        -d "parse_mode=Markdown" > /dev/null

    echo -e "${GREEN}✅ Alerte Telegram envoyée${NC}"
}

# Main
main() {
    echo "🔍 Friday 2.0 - Monitoring RAM"
    echo "=============================="

    # Obtenir usage RAM
    read -r used_gb total_gb <<< "$(get_ram_usage)"

    # Calculer pourcentage
    usage_pct=$((used_gb * 100 / total_gb))

    echo ""
    echo "RAM totale    : ${total_gb} Go"
    echo "RAM utilisée  : ${used_gb} Go"
    echo "Utilisation   : ${usage_pct}%"
    echo "Seuil alerte  : ${RAM_ALERT_THRESHOLD_PCT}%"
    echo ""

    # Vérifier seuil
    if [[ $usage_pct -ge $RAM_ALERT_THRESHOLD_PCT ]]; then
        echo -e "${RED}🚨 ALERTE RAM : Utilisation ${usage_pct}% >= ${RAM_ALERT_THRESHOLD_PCT}%${NC}"

        # Envoyer alerte Telegram si demandé
        if [[ "${1:-}" == "--telegram" ]]; then
            send_telegram_alert "🚨 *Friday 2.0 - Alerte RAM*

Utilisation : *${usage_pct}%* (${used_gb}/${total_gb} Go)
Seuil : ${RAM_ALERT_THRESHOLD_PCT}%

Vérifier les services lourds :
\`docker stats --no-stream\`"
        fi

        exit 1
    else
        echo -e "${GREEN}✅ RAM OK (${usage_pct}% < ${RAM_ALERT_THRESHOLD_PCT}%)${NC}"
    fi

    # Optionnel : Afficher détails Docker
    if command -v docker &> /dev/null; then
        echo ""
        echo "📊 Top 5 conteneurs Docker (RAM) :"
        echo "-----------------------------------"
        docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" | head -n 6
    fi
}

main "$@"
