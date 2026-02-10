#!/bin/bash
# monitor-ram.sh - Monitoring RAM Friday 2.0
#
# Vérifie l'utilisation RAM et alerte via Telegram si dépasse seuil 85%
# Usage: ./scripts/monitor-ram.sh [--telegram] [--json] [--help]
#
# Story 1.13 - AC2: Monitoring RAM avec alertes si > 85%

set -euo pipefail

# Configuration
RAM_ALERT_THRESHOLD_PCT="${RAM_ALERT_THRESHOLD_PCT:-85}"
CPU_ALERT_THRESHOLD_PCT="${CPU_ALERT_THRESHOLD_PCT:-80}"
DISK_ALERT_THRESHOLD_PCT="${DISK_ALERT_THRESHOLD_PCT:-80}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
TOPIC_SYSTEM_ID="${TOPIC_SYSTEM_ID:-}"  # Topic System pour alertes (Story 1.9)
DATABASE_URL="${DATABASE_URL:-}"

# Couleurs
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Flags
JSON_OUTPUT=false
TELEGRAM_ALERT=false

# Fonction : Afficher aide
show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Monitoring système Friday 2.0 - Vérifie RAM, CPU, et disque

Options:
  --json        Afficher output au format JSON structuré (pour logging)
  --telegram    Envoyer alerte Telegram si seuil dépassé (nécessite TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)
  --help        Afficher cette aide

Exemples:
  # Monitoring standard (output humain)
  ./monitor-ram.sh

  # Output JSON pour logging
  ./monitor-ram.sh --json

  # Monitoring + alerte Telegram si anomalie
  ./monitor-ram.sh --telegram

  # Combiné
  ./monitor-ram.sh --json --telegram

Seuils (modifiables via envvars):
  RAM_ALERT_THRESHOLD_PCT=${RAM_ALERT_THRESHOLD_PCT}% (40.8 Go sur VPS-4 48 Go - D22)
  CPU_ALERT_THRESHOLD_PCT=${CPU_ALERT_THRESHOLD_PCT}%
  DISK_ALERT_THRESHOLD_PCT=${DISK_ALERT_THRESHOLD_PCT}%

Variables d'environnement:
  TELEGRAM_BOT_TOKEN    - Token bot Telegram (requis pour --telegram)
  TELEGRAM_CHAT_ID      - Chat ID Telegram (requis pour --telegram)
  TOPIC_SYSTEM_ID       - Thread ID topic System (optionnel, Story 1.9)
  DATABASE_URL          - URL PostgreSQL (optionnel, pour logging core.system_metrics)
  RAM_ALERT_THRESHOLD_PCT  - Seuil alerte RAM (défaut: 85%)
  CPU_ALERT_THRESHOLD_PCT  - Seuil alerte CPU (défaut: 80%)
  DISK_ALERT_THRESHOLD_PCT - Seuil alerte disque (défaut: 80%)

Exit codes:
  0 - Tous les seuils OK
  1 - Au moins un seuil dépassé

Story 1.13 - AC2 : Monitoring RAM avec alertes si > 85%
EOF
    exit 0
}

# Fonction : Obtenir RAM totale et utilisée
get_ram_usage() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        total_kb=$(sysctl -n hw.memsize)
        total_gb=$((total_kb / 1024 / 1024 / 1024))

        # Utilisation approximative (pas précis sur macOS - Bug LOW #6 documenté)
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
        if [[ "$JSON_OUTPUT" == false ]]; then
            echo -e "${YELLOW}⚠️  Variables Telegram non configurées. Alerte non envoyée.${NC}"
        fi
        return
    fi

    # Construire URL avec topic si disponible (Story 1.9)
    local api_url="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"
    local post_data="chat_id=${TELEGRAM_CHAT_ID}&text=${message}&parse_mode=Markdown"

    # Ajouter message_thread_id si TOPIC_SYSTEM_ID défini
    if [[ -n "$TOPIC_SYSTEM_ID" ]]; then
        post_data="${post_data}&message_thread_id=${TOPIC_SYSTEM_ID}"
    fi

    # AC5 (Story 1.13): Timeout 30s max pour envoi notification
    curl -s --max-time 30 -X POST "$api_url" -d "$post_data" > /dev/null || {
        if [[ "$JSON_OUTPUT" == false ]]; then
            echo -e "${YELLOW}⚠️  Telegram notification failed (timeout or error)${NC}"
        fi
        return 1
    }

    if [[ "$JSON_OUTPUT" == false ]]; then
        echo -e "${GREEN}✅ Alerte Telegram envoyée${NC}"
    fi
}

# Fonction : Logger dans database (Subtask 1.3.2)
# TODO: Activer quand migration 020_recovery_events.sql sera créée (Task 2.2)
log_to_database() {
    local ram_pct=$1
    local cpu_pct=$2
    local disk_pct=$3

    # Skip si DATABASE_URL non défini
    if [[ -z "$DATABASE_URL" ]]; then
        return
    fi

    # TODO Task 2.2: Décommenter quand table core.system_metrics existe
    # psql "$DATABASE_URL" -c "
    #     INSERT INTO core.system_metrics (metric_type, value, threshold, timestamp)
    #     VALUES
    #         ('ram_usage_pct', ${ram_pct}, ${RAM_ALERT_THRESHOLD_PCT}, NOW()),
    #         ('cpu_usage_pct', ${cpu_pct}, ${CPU_ALERT_THRESHOLD_PCT}, NOW()),
    #         ('disk_usage_pct', ${disk_pct}, ${DISK_ALERT_THRESHOLD_PCT}, NOW())
    # " 2>/dev/null || true
}

# Fonction : Output JSON structuré (Subtask 1.3.1)
output_json() {
    local ram_used=$1
    local ram_total=$2
    local ram_pct=$3
    local cpu_pct=$4
    local disk_pct=$5
    local alert_status=$6
    local exit_code=$7

    cat <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "ram_used_gb": ${ram_used},
  "ram_total_gb": ${ram_total},
  "ram_usage_pct": ${ram_pct},
  "ram_threshold_pct": ${RAM_ALERT_THRESHOLD_PCT},
  "cpu_usage_pct": ${cpu_pct},
  "cpu_threshold_pct": ${CPU_ALERT_THRESHOLD_PCT},
  "disk_usage_pct": ${disk_pct},
  "disk_threshold_pct": ${DISK_ALERT_THRESHOLD_PCT},
  "alert_status": "${alert_status}",
  "exit_code": ${exit_code}
}
EOF
}

# Main
main() {
    # Parser arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --json)
                JSON_OUTPUT=true
                shift
                ;;
            --telegram)
                TELEGRAM_ALERT=true
                shift
                ;;
            --help)
                show_help
                ;;
            *)
                echo "Erreur: Option inconnue: $1"
                echo "Utilisez --help pour voir l'aide"
                exit 1
                ;;
        esac
    done

    # Obtenir métriques
    read -r used_gb total_gb <<< "$(get_ram_usage)"
    ram_usage_pct=$((used_gb * 100 / total_gb))

    cpu_usage=$(get_cpu_usage)
    cpu_usage_int=${cpu_usage%.*}  # Arrondir à l'entier

    disk_usage=$(get_disk_usage)

    # Déterminer status alertes
    alerts=""
    exit_code=0
    alert_status="ok"

    if [[ $ram_usage_pct -ge $RAM_ALERT_THRESHOLD_PCT ]]; then
        alerts="${alerts}🚨 *RAM* : ${ram_usage_pct}% (${used_gb}/${total_gb} Go)
"
        exit_code=1
        alert_status="alert"
    fi

    if [[ $cpu_usage_int -ge $CPU_ALERT_THRESHOLD_PCT ]]; then
        alerts="${alerts}🚨 *CPU* : ${cpu_usage}%
"
        exit_code=1
        alert_status="alert"
    fi

    if [[ $disk_usage -ge $DISK_ALERT_THRESHOLD_PCT ]]; then
        alerts="${alerts}🚨 *Disque* : ${disk_usage}%
"
        exit_code=1
        alert_status="alert"
    fi

    # Output selon format demandé
    if [[ "$JSON_OUTPUT" == true ]]; then
        # Format JSON structuré (Subtask 1.3.1)
        output_json "$used_gb" "$total_gb" "$ram_usage_pct" "$cpu_usage" "$disk_usage" "$alert_status" "$exit_code"
    else
        # Format humain (comportement par défaut)
        echo "🔍 Friday 2.0 - Monitoring Système"
        echo "==================================="

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

        # Afficher status par métrique
        if [[ $ram_usage_pct -ge $RAM_ALERT_THRESHOLD_PCT ]]; then
            echo -e "${RED}🚨 ALERTE RAM : ${ram_usage_pct}% >= ${RAM_ALERT_THRESHOLD_PCT}%${NC}"
        else
            echo -e "${GREEN}✅ RAM OK (${ram_usage_pct}% < ${RAM_ALERT_THRESHOLD_PCT}%)${NC}"
        fi

        if [[ $cpu_usage_int -ge $CPU_ALERT_THRESHOLD_PCT ]]; then
            echo -e "${RED}🚨 ALERTE CPU : ${cpu_usage}% >= ${CPU_ALERT_THRESHOLD_PCT}%${NC}"
        else
            echo -e "${GREEN}✅ CPU OK (${cpu_usage}% < ${CPU_ALERT_THRESHOLD_PCT}%)${NC}"
        fi

        if [[ $disk_usage -ge $DISK_ALERT_THRESHOLD_PCT ]]; then
            echo -e "${RED}🚨 ALERTE DISQUE : ${disk_usage}% >= ${DISK_ALERT_THRESHOLD_PCT}%${NC}"
        else
            echo -e "${GREEN}✅ Disque OK (${disk_usage}% < ${DISK_ALERT_THRESHOLD_PCT}%)${NC}"
        fi

        # Optionnel : Afficher détails Docker
        if command -v docker &> /dev/null; then
            echo ""
            echo "📊 Top 5 conteneurs Docker (RAM) :"
            echo "-----------------------------------"
            docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" | head -n 6
        fi
    fi

    # Envoyer alerte Telegram si anomalie détectée + flag --telegram
    if [[ -n "$alerts" ]] && [[ "$TELEGRAM_ALERT" == true ]]; then
        send_telegram_alert "🟡 *Friday RAM Alert*

${alerts}
Seuil: ${RAM_ALERT_THRESHOLD_PCT}% (${RAM_ALERT_THRESHOLD_PCT}*48/100 = 40.8 GB sur VPS-4)

Actions:
\`docker stats --no-stream\`
\`/recovery\`"
    fi

    # Logger dans database (Subtask 1.3.2 - TODO Task 2.2)
    log_to_database "$ram_usage_pct" "$cpu_usage_int" "$disk_usage"

    exit $exit_code
}

main "$@"
