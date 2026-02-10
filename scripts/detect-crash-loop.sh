#!/usr/bin/env bash
# detect-crash-loop.sh - Détection crash loop Docker Friday 2.0
#
# Détecte services qui crashent en boucle (>3 restarts/1h) et les arrête
# Usage: ./scripts/detect-crash-loop.sh
#
# Story 1.13 - AC6: Détection crash loop (>3 restarts en 1h)

set -euo pipefail

# Configuration
THRESHOLD_RESTARTS="${THRESHOLD_RESTARTS:-3}"
TIME_WINDOW_SECONDS="${TIME_WINDOW_SECONDS:-3600}"  # 1 hour
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
TOPIC_SYSTEM_ID="${TOPIC_SYSTEM_ID:-}"
DATABASE_URL="${DATABASE_URL:-}"

# Couleurs
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

# Fonction : Envoyer alerte Telegram
send_crash_loop_alert() {
    local container_name="$1"
    local restart_count="$2"
    local last_logs="$3"

    if [[ -z "$TELEGRAM_BOT_TOKEN" ]] || [[ -z "$TELEGRAM_CHAT_ID" ]]; then
        return 0  # Skip si pas configuré
    fi

    local message="🚨 *CRASH LOOP DETECTED*

Service: \`${container_name}\`
Restarts: ${restart_count} in 1h (threshold: ${THRESHOLD_RESTARTS})
Status: STOPPED (manual restart required)

Last logs:
\`\`\`
${last_logs}
\`\`\`

Actions suggérées:
1. Vérifier logs complets : \`docker logs ${container_name}\`
2. Vérifier healthcheck : \`docker inspect ${container_name} | jq '.[0].State.Health'\`
3. Restart manuel si fixé : \`docker start ${container_name}\`"

    local api_url="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"
    local post_data="chat_id=${TELEGRAM_CHAT_ID}&text=${message}&parse_mode=Markdown"

    if [[ -n "$TOPIC_SYSTEM_ID" ]]; then
        post_data="${post_data}&message_thread_id=${TOPIC_SYSTEM_ID}"
    fi

    curl -s --max-time 30 -X POST "$api_url" -d "$post_data" > /dev/null || {
        echo "⚠️  Telegram alert failed" >&2
    }
}

# Fonction : Logger dans database (Task 2.2)
log_crash_loop_event() {
    local container_name="$1"
    local restart_count="$2"

    if [[ -z "$DATABASE_URL" ]]; then
        return 0
    fi

    # Migration 020 créée - logging activé
    psql "$DATABASE_URL" -c "
        INSERT INTO core.recovery_events
            (event_type, services_affected, success, created_at)
        VALUES
            ('crash_loop_detected', '${container_name}', false, NOW())
    " 2>/dev/null || true
}

# Main
main() {
    echo "🔍 Friday 2.0 - Crash Loop Detector"
    echo "====================================="
    echo ""
    echo "Threshold: > ${THRESHOLD_RESTARTS} restarts in ${TIME_WINDOW_SECONDS}s (1h)"
    echo ""

    # Vérifier Docker disponible
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker not available${NC}"
        exit 1
    fi

    # Get all containers (running + stopped)
    local containers
    containers=$(docker ps -aq 2>/dev/null || echo "")

    if [[ -z "$containers" ]]; then
        echo -e "${GREEN}✅ No containers found${NC}"
        exit 0
    fi

    local crash_loop_detected=false
    local crashed_services=()

    # Analyser chaque container
    for container_id in $containers; do
        # Get container name
        local container_name
        container_name=$(docker inspect --format='{{.Name}}' "$container_id" 2>/dev/null | sed 's/\///' || echo "unknown")

        # Méthode 1: Utiliser RestartCount de docker inspect
        # Plus simple et fiable que docker events
        local restart_count
        restart_count=$(docker inspect --format='{{.RestartCount}}' "$container_id" 2>/dev/null || echo "0")

        # Get last started time
        local started_at
        started_at=$(docker inspect --format='{{.State.StartedAt}}' "$container_id" 2>/dev/null || echo "")

        # Convert started_at to timestamp
        local started_timestamp
        if [[ -n "$started_at" ]]; then
            started_timestamp=$(date -d "$started_at" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%S" "${started_at:0:19}" +%s 2>/dev/null || echo "0")
        else
            started_timestamp=0
        fi

        local current_timestamp
        current_timestamp=$(date +%s)

        local time_since_start=$((current_timestamp - started_timestamp))

        # Si le container a redémarré plus de THRESHOLD fois
        # ET qu'il a démarré récemment (dans la dernière heure)
        if [ "$restart_count" -gt "$THRESHOLD_RESTARTS" ] && [ "$time_since_start" -lt "$TIME_WINDOW_SECONDS" ]; then
            echo -e "${RED}🚨 CRASH LOOP DETECTED: ${container_name} (${restart_count} restarts)${NC}"
            crash_loop_detected=true
            crashed_services+=("$container_name")

            # Get last 5 log lines for diagnostic
            local last_logs
            last_logs=$(docker logs --tail 5 "$container_id" 2>&1 || echo "No logs available")

            # Stop service to prevent infinite loop
            echo "  ⛔ Stopping service to prevent infinite loop..."
            docker stop "$container_id" 2>/dev/null || {
                echo -e "  ${YELLOW}⚠️  Failed to stop service${NC}"
            }

            # Send Telegram alert
            send_crash_loop_alert "$container_name" "$restart_count" "$last_logs"

            # Log to database
            log_crash_loop_event "$container_name" "$restart_count"

        elif [ "$restart_count" -gt 0 ]; then
            # Container a redémarré mais pas assez pour être un crash loop
            echo "  ℹ️  ${container_name}: ${restart_count} restarts (OK, below threshold)"
        fi
    done

    echo ""
    echo "─────────────────────────────────────────────────────────"

    if [ "$crash_loop_detected" = true ]; then
        echo -e "${RED}❌ Crash loop(s) detected and stopped${NC}"
        echo ""
        echo "Affected services:"
        for service in "${crashed_services[@]}"; do
            echo "  • ${service}"
        done
        echo ""
        echo "Manual intervention required:"
        echo "  1. Check logs: docker logs <service>"
        echo "  2. Fix underlying issue"
        echo "  3. Manual restart: docker start <service>"
        echo ""
        exit 1  # Exit 1 signals crash loop detected (for CI/CD)
    else
        echo -e "${GREEN}✅ All services healthy (no crash loops detected)${NC}"
        exit 0
    fi
}

main "$@"
