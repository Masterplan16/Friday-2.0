#!/bin/bash
# monitor-ram.sh - Monitoring RAM Friday 2.0
#
# Vérifie l'utilisation RAM et alerte via Telegram si dépasse seuil 85%
# Usage: ./scripts/monitor-ram.sh [--telegram]

set -euo pipefail

# Configuration
RAM_ALERT_THRESHOLD_PCT=85
CPU_ALERT_THRESHOLD_PCT=80
DISK_ALERT_THRESHOLD_PCT=80
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

# Fonction : Obtenir utilisation CPU
get_cpu_usage() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS : Utiliser top
        cpu_usage=$(top -l 1 | awk '/CPU usage/ {print $3}' | sed 's/%//')
    else
        # Linux : Utiliser top
        cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
    fi

    echo "$cpu_usage"
}

# Fonction : Obtenir utilisation disque
get_disk_usage() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS : Racine du système
        disk_usage=$(df -h / | tail -1 | awk '{print $5}' | tr -d '%')
    else
        # Linux : Racine du système
        disk_usage=$(df -h / | tail -1 | awk '{print $5}' | tr -d '%')
    fi

    echo "$disk_usage"
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
    echo "🔍 Friday 2.0 - Monitoring Système"
    echo "==================================="

    # Obtenir métriques
    read -r used_gb total_gb <<< "$(get_ram_usage)"
    ram_usage_pct=$((used_gb * 100 / total_gb))

    cpu_usage=$(get_cpu_usage)
    cpu_usage_int=${cpu_usage%.*}  # Arrondir à l'entier

    disk_usage=$(get_disk_usage)

    # Afficher métriques
    echo ""
    echo "📊 RAM"
    echo "  Totale      : ${total_gb} Go"
    echo "  Utilisée    : ${used_gb} Go"
    echo "  Utilisation : ${ram_usage_pct}%"
    echo "  Seuil       : ${RAM_ALERT_THRESHOLD_PCT}%"

    echo ""
    echo "💻 CPU"
    echo "  Utilisation : ${cpu_usage}%"
    echo "  Seuil       : ${CPU_ALERT_THRESHOLD_PCT}%"

    echo ""
    echo "💾 Disque (racine /)"
    echo "  Utilisation : ${disk_usage}%"
    echo "  Seuil       : ${DISK_ALERT_THRESHOLD_PCT}%"
    echo ""

    # Vérifier seuils
    alerts=""
    exit_code=0

    if [[ $ram_usage_pct -ge $RAM_ALERT_THRESHOLD_PCT ]]; then
        echo -e "${RED}🚨 ALERTE RAM : ${ram_usage_pct}% >= ${RAM_ALERT_THRESHOLD_PCT}%${NC}"
        alerts="${alerts}🚨 *RAM* : ${ram_usage_pct}% (${used_gb}/${total_gb} Go)
"
        exit_code=1
    else
        echo -e "${GREEN}✅ RAM OK (${ram_usage_pct}% < ${RAM_ALERT_THRESHOLD_PCT}%)${NC}"
    fi

    if [[ $cpu_usage_int -ge $CPU_ALERT_THRESHOLD_PCT ]]; then
        echo -e "${RED}🚨 ALERTE CPU : ${cpu_usage}% >= ${CPU_ALERT_THRESHOLD_PCT}%${NC}"
        alerts="${alerts}🚨 *CPU* : ${cpu_usage}%
"
        exit_code=1
    else
        echo -e "${GREEN}✅ CPU OK (${cpu_usage}% < ${CPU_ALERT_THRESHOLD_PCT}%)${NC}"
    fi

    if [[ $disk_usage -ge $DISK_ALERT_THRESHOLD_PCT ]]; then
        echo -e "${RED}🚨 ALERTE DISQUE : ${disk_usage}% >= ${DISK_ALERT_THRESHOLD_PCT}%${NC}"
        alerts="${alerts}🚨 *Disque* : ${disk_usage}%
"
        exit_code=1
    else
        echo -e "${GREEN}✅ Disque OK (${disk_usage}% < ${DISK_ALERT_THRESHOLD_PCT}%)${NC}"
    fi

    # Envoyer alerte Telegram si anomalie détectée
    if [[ -n "$alerts" ]] && [[ "${1:-}" == "--telegram" ]]; then
        send_telegram_alert "🚨 *Friday 2.0 - Alerte Système*

${alerts}
Vérifier les services lourds :
\`docker stats --no-stream\`"
    fi

    # Optionnel : Afficher détails Docker
    if command -v docker &> /dev/null; then
        echo ""
        echo "📊 Top 5 conteneurs Docker (RAM) :"
        echo "-----------------------------------"
        docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" | head -n 6
    fi

    exit $exit_code
}

main "$@"
