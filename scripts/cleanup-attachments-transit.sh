#!/bin/bash
# Cleanup attachments zone transit
# Story 2.4 - Task 7.1
#
# Supprime fichiers zone transit >24h ET status='archived' en DB.
#
# Workflow :
#   1. Query PostgreSQL : fichiers status='archived' AND processed_at < NOW() - 24h
#   2. Pour chaque filepath : rm -f (si existe)
#   3. Calcul espace libéré (du -sh avant/après)
#   4. Notification Telegram System si >100 Mo libérés
#
# Cron : 03:05 quotidien (appelé par scripts/cleanup-disk)

set -euo pipefail

# ============================================
# Configuration
# ============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source .env si existe
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.env"
fi

# Variables env (avec defaults pour dev)
DATABASE_URL="${DATABASE_URL:-postgresql://friday:friday@localhost:5432/friday}"
TRANSIT_BASE_DIR="${TRANSIT_BASE_DIR:-/var/friday/transit/attachments}"
DRY_RUN="${DRY_RUN:-false}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_SUPERGROUP_ID="${TELEGRAM_SUPERGROUP_ID:-}"
TOPIC_SYSTEM_ID="${TOPIC_SYSTEM_ID:-}"

LOG_PREFIX="[cleanup-attachments-transit]"

# ============================================
# Fonctions
# ============================================

log_info() {
    echo "$LOG_PREFIX INFO: $*" >&2
}

log_error() {
    echo "$LOG_PREFIX ERROR: $*" >&2
}

send_telegram_notification() {
    local message="$1"

    if [[ -z "$TELEGRAM_BOT_TOKEN" ]] || [[ -z "$TELEGRAM_SUPERGROUP_ID" ]] || [[ -z "$TOPIC_SYSTEM_ID" ]]; then
        log_info "Telegram not configured, skip notification"
        return 0
    fi

    curl -s -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{
            \"chat_id\": \"${TELEGRAM_SUPERGROUP_ID}\",
            \"message_thread_id\": ${TOPIC_SYSTEM_ID},
            \"text\": \"${message}\",
            \"parse_mode\": \"HTML\"
        }" >/dev/null 2>&1 || log_error "Telegram notification failed"
}

get_disk_usage_mb() {
    local dir="$1"

    if [[ ! -d "$dir" ]]; then
        echo "0"
        return
    fi

    # du -sb retourne bytes (portable Linux/macOS)
    # Convertir en Mo
    local bytes
    bytes=$(du -sb "$dir" 2>/dev/null | awk '{print $1}' || echo "0")
    echo "scale=2; $bytes / 1048576" | bc
}

# ============================================
# Main Logic
# ============================================

main() {
    log_info "Starting cleanup attachments zone transit"
    log_info "Transit dir: $TRANSIT_BASE_DIR"
    log_info "Dry run: $DRY_RUN"

    # Vérifier PostgreSQL accessible
    if ! psql "$DATABASE_URL" -c "SELECT 1" >/dev/null 2>&1; then
        log_error "PostgreSQL connection failed"
        exit 1
    fi

    # Mesure espace AVANT cleanup
    disk_usage_before_mb=$(get_disk_usage_mb "$TRANSIT_BASE_DIR")
    log_info "Disk usage before: ${disk_usage_before_mb} Mo"

    # Query PostgreSQL : fichiers archived >24h
    # NOTE : filepath stocke chemin complet Unix (ex: /var/friday/transit/attachments/2026-02-11/123_0_file.pdf)
    local query="
    SELECT filepath
    FROM ingestion.attachments
    WHERE status='archived'
      AND processed_at < NOW() - INTERVAL '24 hours'
    ORDER BY processed_at ASC;
    "

    log_info "Querying archived attachments >24h..."

    local filepaths
    filepaths=$(psql "$DATABASE_URL" -t -c "$query" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -v '^$' || true)

    if [[ -z "$filepaths" ]]; then
        log_info "No archived attachments >24h found. Nothing to cleanup."
        exit 0
    fi

    local total_files=0
    local deleted_files=0
    local failed_files=0

    while IFS= read -r filepath; do
        ((total_files++))

        if [[ ! -f "$filepath" ]]; then
            log_info "File already deleted (skip): $filepath"
            continue
        fi

        if [[ "$DRY_RUN" == "true" ]]; then
            log_info "[DRY RUN] Would delete: $filepath"
            ((deleted_files++))
        else
            if rm -f "$filepath" 2>/dev/null; then
                log_info "Deleted: $filepath"
                ((deleted_files++))
            else
                log_error "Failed to delete: $filepath"
                ((failed_files++))
            fi
        fi
    done <<< "$filepaths"

    # Mesure espace APRÈS cleanup
    disk_usage_after_mb=$(get_disk_usage_mb "$TRANSIT_BASE_DIR")
    freed_mb=$(echo "$disk_usage_before_mb - $disk_usage_after_mb" | bc)

    log_info "Disk usage after: ${disk_usage_after_mb} Mo"
    log_info "Space freed: ${freed_mb} Mo"
    log_info "Files processed: $total_files (deleted: $deleted_files, failed: $failed_files)"

    # Notification Telegram si >100 Mo libérés
    if (( $(echo "$freed_mb >= 100" | bc -l) )); then
        local message="Cleanup attachments transit\n\nEspace libere : ${freed_mb} Mo\nFichiers supprimes : ${deleted_files}"
        send_telegram_notification "$message"
        log_info "Telegram notification sent (freed >100 Mo)"
    fi

    # Cleanup répertoires vides (dates anciennes)
    if [[ "$DRY_RUN" == "false" ]]; then
        find "$TRANSIT_BASE_DIR" -type d -empty -delete 2>/dev/null || true
        log_info "Empty directories cleaned"
    fi

    log_info "Cleanup completed successfully"
}

# ============================================
# Entry Point
# ============================================

main "$@"
