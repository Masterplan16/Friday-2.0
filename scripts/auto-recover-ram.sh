#!/usr/bin/env bash
# auto-recover-ram.sh - Auto-recovery RAM Friday 2.0
#
# Tue automatiquement les services par priorité si RAM > 91%
# Usage: ./scripts/auto-recover-ram.sh
#
# Story 1.13 - AC3: Auto-recover-ram si > 91% (kill services par priorité)
# NFR13: Recovery < 2 min

set -euo pipefail

# Configuration
RAM_RECOVERY_THRESHOLD_PCT="${RAM_RECOVERY_THRESHOLD_PCT:-91}"  # Seuil déclenchement auto-recovery
RAM_TARGET_PCT="${RAM_TARGET_PCT:-85}"  # Cible après recovery
MAX_SERVICES_TO_KILL="${MAX_SERVICES_TO_KILL:-3}"  # Safety guard
WAIT_AFTER_KILL_SECONDS="${WAIT_AFTER_KILL_SECONDS:-10}"  # Attendre libération RAM
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-120}"  # NFR13: < 2 min

# Telegram
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
TOPIC_SYSTEM_ID="${TOPIC_SYSTEM_ID:-}"  # Topic System (Story 1.9)

# Database
DATABASE_URL="${DATABASE_URL:-}"

# Couleurs
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Priority order for service termination (based on business criticality)
# Priority 1: Least critical (kill first)
# Priority 2: Medium criticality
# Priority 3: Important but deferrable
PRIORITY_1_SERVICE="kokoro-tts"
PRIORITY_1_RAM_FREED=2  # Go

PRIORITY_2_SERVICE="faster-whisper"
PRIORITY_2_RAM_FREED=4  # Go

PRIORITY_3_SERVICE="surya-ocr"
PRIORITY_3_RAM_FREED=2  # Go

# Protected services (NEVER kill)
PROTECTED_SERVICES=(
    "postgres"
    "redis"
    "friday-gateway"
    "friday-bot"
    "n8n"
    "imap-fetcher"
    "presidio"
)

# Fonction : Obtenir RAM usage percentage
get_ram_usage_pct() {
    # Si variable d'environnement définie (pour tests), utiliser celle-ci
    if [[ -n "${RAM_PCT:-}" ]]; then
        echo "$RAM_PCT"
        return 0
    fi

    # Sinon, calculer réellement (Linux uniquement)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS : approximatif
        total_kb=$(sysctl -n hw.memsize)
        total_gb=$((total_kb / 1024 / 1024 / 1024))
        used_gb=$(( (total_kb - $(vm_stat | awk '/Pages free/ {print $3}' | sed 's/\.//')*4096) / 1024 / 1024 / 1024 ))
    else
        # Linux
        total_gb=$(free -g | awk '/^Mem:/ {print $2}')
        used_gb=$(free -g | awk '/^Mem:/ {print $3}')
    fi

    local ram_pct=$((used_gb * 100 / total_gb))
    echo "$ram_pct"
}

# Fonction : Envoyer notification Telegram
send_telegram_notification() {
    local message="$1"

    if [[ -z "$TELEGRAM_BOT_TOKEN" ]] || [[ -z "$TELEGRAM_CHAT_ID" ]]; then
        return 0  # Skip si pas configuré
    fi

    local api_url="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"
    local post_data="chat_id=${TELEGRAM_CHAT_ID}&text=${message}&parse_mode=Markdown"

    # Ajouter message_thread_id si TOPIC_SYSTEM_ID défini (Story 1.9)
    if [[ -n "$TOPIC_SYSTEM_ID" ]]; then
        post_data="${post_data}&message_thread_id=${TOPIC_SYSTEM_ID}"
    fi

    # AC5: Timeout 30s max pour envoi notification
    curl -s --max-time 30 -X POST "$api_url" -d "$post_data" > /dev/null || {
        echo "⚠️  Telegram notification failed (timeout or error)" >&2
        return 1
    }
}

# Fonction : Logger dans database (Task 2.2)
log_recovery_event() {
    local event_type="$1"
    local services_affected="$2"
    local ram_before="$3"
    local ram_after="$4"
    local success="$5"

    if [[ -z "$DATABASE_URL" ]]; then
        return 0  # Skip si pas configuré
    fi

    # Migration 020 créée - logging activé
    psql "$DATABASE_URL" -c "
        INSERT INTO core.recovery_events
            (event_type, services_affected, ram_before, ram_after, success, created_at)
        VALUES
            ('${event_type}', '${services_affected}', ${ram_before}, ${ram_after}, ${success}, NOW())
    " 2>/dev/null || true
}

# Fonction : Vérifier si service est protégé
is_protected_service() {
    local service="$1"

    for protected in "${PROTECTED_SERVICES[@]}"; do
        if [[ "$service" == "$protected" ]]; then
            return 0  # Protected
        fi
    done

    return 1  # Not protected
}

# Fonction : Tuer service et attendre libération RAM
kill_service() {
    local service="$1"
    local ram_freed_expected="$2"

    echo -e "${RED}🔴 Killing $service to free ~${ram_freed_expected}GB RAM...${NC}"

    # Vérifier que le service n'est pas protégé (safety check)
    if is_protected_service "$service"; then
        echo -e "${RED}❌ ERROR: Attempted to kill protected service: $service${NC}"
        return 1
    fi

    # Docker stop
    if command -v docker &> /dev/null; then
        docker stop "$service" 2>/dev/null || {
            echo -e "${YELLOW}⚠️  Service $service not found or already stopped${NC}"
            return 1
        }
    else
        echo -e "${YELLOW}⚠️  Docker not available (test mode)${NC}"
        return 0  # OK dans tests
    fi

    # Attendre libération RAM
    echo "⏳ Waiting ${WAIT_AFTER_KILL_SECONDS}s for RAM to be freed..."
    sleep "$WAIT_AFTER_KILL_SECONDS"

    # Vérifier nouvelle RAM usage
    local current_ram_pct
    current_ram_pct=$(get_ram_usage_pct)

    if [ "$current_ram_pct" -lt "$RAM_TARGET_PCT" ]; then
        echo -e "${GREEN}✅ RAM recovery successful: ${current_ram_pct}%${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠️  RAM still high: ${current_ram_pct}% (target: ${RAM_TARGET_PCT}%)${NC}"
        return 1  # Continue killing
    fi
}

# Main
main() {
    local start_time
    start_time=$(date +%s)

    echo "🔍 Friday 2.0 - Auto-Recovery RAM"
    echo "===================================="
    echo ""

    # Obtenir RAM usage actuelle
    local current_ram_pct
    current_ram_pct=$(get_ram_usage_pct)
    local initial_ram_pct=$current_ram_pct

    echo "📊 Current RAM: ${current_ram_pct}%"
    echo "🎯 Recovery threshold: ${RAM_RECOVERY_THRESHOLD_PCT}%"
    echo "🎯 Target after recovery: ${RAM_TARGET_PCT}%"
    echo ""

    # Vérifier si recovery nécessaire
    if [ "$current_ram_pct" -lt "$RAM_RECOVERY_THRESHOLD_PCT" ]; then
        echo -e "${GREEN}✅ RAM OK (${current_ram_pct}% < ${RAM_RECOVERY_THRESHOLD_PCT}%)${NC}"
        echo "No recovery needed."
        exit 0
    fi

    echo -e "${RED}🚨 RAM CRITICAL: ${current_ram_pct}% >= ${RAM_RECOVERY_THRESHOLD_PCT}%${NC}"
    echo -e "${YELLOW}Starting auto-recovery...${NC}"
    echo ""

    # Tuer services par priorité
    local services_killed=()
    local killed_count=0

    # Priority 1: TTS (least critical)
    if [ "$current_ram_pct" -ge "$RAM_TARGET_PCT" ] && [ "$killed_count" -lt "$MAX_SERVICES_TO_KILL" ]; then
        if kill_service "$PRIORITY_1_SERVICE" "$PRIORITY_1_RAM_FREED"; then
            services_killed+=("$PRIORITY_1_SERVICE")
            ((killed_count++))
            current_ram_pct=$(get_ram_usage_pct)
        fi
    fi

    # Priority 2: STT (medium criticality)
    if [ "$current_ram_pct" -ge "$RAM_TARGET_PCT" ] && [ "$killed_count" -lt "$MAX_SERVICES_TO_KILL" ]; then
        if kill_service "$PRIORITY_2_SERVICE" "$PRIORITY_2_RAM_FREED"; then
            services_killed+=("$PRIORITY_2_SERVICE")
            ((killed_count++))
            current_ram_pct=$(get_ram_usage_pct)
        else
            # Si kill échoue (service pas trouvé), continuer
            true
        fi
    fi

    # Priority 3: OCR (important but deferrable)
    if [ "$current_ram_pct" -ge "$RAM_TARGET_PCT" ] && [ "$killed_count" -lt "$MAX_SERVICES_TO_KILL" ]; then
        if kill_service "$PRIORITY_3_SERVICE" "$PRIORITY_3_RAM_FREED"; then
            services_killed+=("$PRIORITY_3_SERVICE")
            ((killed_count++))
            current_ram_pct=$(get_ram_usage_pct)
        else
            true
        fi
    fi

    # Safety guard : max 3 services tués
    if [ "$killed_count" -ge "$MAX_SERVICES_TO_KILL" ]; then
        echo -e "${YELLOW}⚠️  Safety guard triggered: Max ${MAX_SERVICES_TO_KILL} services killed${NC}"
    fi

    # Calculer durée recovery
    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # Vérifier timeout (NFR13: < 2 min)
    if [ "$duration" -gt "$TIMEOUT_SECONDS" ]; then
        echo -e "${RED}❌ Recovery timeout: ${duration}s > ${TIMEOUT_SECONDS}s (NFR13 violation)${NC}"
    fi

    # Résumé final
    echo ""
    echo "═══════════════════════════════════════════════════"
    echo "📊 Recovery Summary"
    echo "═══════════════════════════════════════════════════"
    echo "RAM before: ${initial_ram_pct}%"
    echo "RAM after:  ${current_ram_pct}%"
    echo "Services killed: ${killed_count} (${services_killed[*]:-none})"
    echo "Duration: ${duration}s (target: <${TIMEOUT_SECONDS}s)"
    echo ""

    # Déterminer succès
    local success=false
    local exit_code=1

    if [ "$current_ram_pct" -lt "$RAM_TARGET_PCT" ]; then
        echo -e "${GREEN}✅ Auto-recovery SUCCESSFUL${NC}"
        echo "Services will restart automatically via Docker restart policy."
        success=true
        exit_code=0
    else
        echo -e "${RED}❌ Auto-recovery FAILED${NC}"
        echo "RAM still above target: ${current_ram_pct}% >= ${RAM_TARGET_PCT}%"
        echo "Manual intervention required."
        success=false
        exit_code=1
    fi

    # Envoyer notification Telegram (seulement si succès)
    local services_killed_str="${services_killed[*]:-none}"
    if [ "$success" = true ]; then
        send_telegram_notification "✅ *Auto-Recovery RAM Successful*

Type: RAM overload (${initial_ram_pct}% → ${current_ram_pct}%)
Services killed: ${services_killed_str}
RAM freed: ~$(( (initial_ram_pct - current_ram_pct) * 48 / 100 )) GB
Duration: ${duration}s
Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)

Services will restart automatically when RAM allows."
    else
        send_telegram_notification "❌ *Auto-Recovery RAM FAILED*

Type: RAM overload (${initial_ram_pct}% → ${current_ram_pct}%)
Services killed: ${services_killed_str}
Duration: ${duration}s
Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)

⚠️ Manual intervention required!"
    fi

    # Logger dans database
    log_recovery_event "auto_recovery_ram" "$services_killed_str" "$initial_ram_pct" "$current_ram_pct" "$success"

    exit "$exit_code"
}

main "$@"
