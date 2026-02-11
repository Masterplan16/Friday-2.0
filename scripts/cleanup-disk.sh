#!/bin/bash
#
# cleanup-disk.sh - Cleanup automatisé + purge RGPD
# Story 1.15 - Friday 2.0
#
# Usage:
#   ./cleanup-disk.sh              # Exécution normale
#   ./cleanup-disk.sh --dry-run    # Preview sans suppression réelle
#
# Opérations:
#   1. Purge mappings Presidio >30 jours (RGPD)
#   2. Rotation logs Docker >7 jours
#   3. Rotation logs journald >7 jours
#   4. Rotation backups VPS >30 jours (retention_policy='keep_7_days')
#   5. Cleanup zone transit /data/transit/uploads/ >24h
#   6. Notification Telegram topic System
#
# Cron: 5 3 * * * (03:05 daily, après backup 03:00)

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

# Load environment variables
if [ -f /opt/friday-2.0/.env ]; then
    # shellcheck disable=SC1091
    source /opt/friday-2.0/.env
fi

# Database config
DB_USER="${POSTGRES_USER:-friday}"
DB_NAME="${POSTGRES_DB:-friday}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"

# Telegram config
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_SUPERGROUP_ID="${TELEGRAM_SUPERGROUP_ID:-}"
TOPIC_SYSTEM_ID="${TOPIC_SYSTEM_ID:-}"

# Paths
TRANSIT_DIR="${TRANSIT_DIR:-/data/transit/uploads}"
LOG_FILE="${LOG_FILE:-/var/log/friday/cleanup-disk.log}"

# Dry-run mode
DRY_RUN=false

# ============================================================================
# Logging Functions
# ============================================================================

log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    # H5 FIX: Create log directory if doesn't exist
    mkdir -p "$(dirname "$LOG_FILE")"

    echo "[${timestamp}] [${level}] ${message}" | tee -a "$LOG_FILE"
}

log_error() {
    log "ERROR" "$@"
}

log_warn() {
    log "WARNING" "$@"
}

log_info() {
    log "INFO" "$@"
}

# ============================================================================
# Helper Functions
# ============================================================================

format_bytes() {
    local bytes="$1"

    # M3 FIX: Use base 1024 (binary) instead of 1000 (decimal) for consistency with du/df
    if [ "$bytes" -ge 1073741824 ]; then  # 1024^3
        echo "scale=1; $bytes / 1073741824" | bc | awk '{printf "%.1f GiB", $1}'
    elif [ "$bytes" -ge 1048576 ]; then  # 1024^2
        echo "scale=1; $bytes / 1048576" | bc | awk '{printf "%.1f MiB", $1}'
    elif [ "$bytes" -ge 1024 ]; then
        echo "scale=1; $bytes / 1024" | bc | awk '{printf "%.1f KiB", $1}'
    else
        echo "${bytes} bytes"
    fi
}

calculate_diff() {
    local before="$1"
    local after="$2"
    local diff=$((before - after))

    # M2 FIX: Log warning if negative diff (indicates parsing error)
    if [ $diff -lt 0 ]; then
        log_warn "calculate_diff: negative diff detected (before=$before, after=$after), using 0"
        diff=0
    fi

    echo "$diff"
}

# H1/H2 FIX: Parse Docker/journald size strings to bytes
parse_size_to_bytes() {
    local size_str="$1"

    # Handle empty or invalid input
    if [ -z "$size_str" ]; then
        echo "0"
        return
    fi

    # Extract number and unit (e.g., "1.2GB" → number=1.2, unit=GB)
    local number
    local unit

    # Try to extract floating point number and unit
    number=$(echo "$size_str" | grep -oP '\d+(\.\d+)?' | head -1 || echo "0")
    unit=$(echo "$size_str" | grep -oP '[KMGT]i?B' | head -1 || echo "B")

    # Convert to bytes based on unit
    local bytes
    case "$unit" in
        TB|TiB) bytes=$(echo "scale=0; $number * 1099511627776" | bc) ;;
        GB|GiB) bytes=$(echo "scale=0; $number * 1073741824" | bc) ;;
        MB|MiB) bytes=$(echo "scale=0; $number * 1048576" | bc) ;;
        KB|KiB) bytes=$(echo "scale=0; $number * 1024" | bc) ;;
        *) bytes="$number" ;;
    esac

    # Round to integer
    bytes=$(printf "%.0f" "$bytes" 2>/dev/null || echo "0")

    echo "$bytes"
}

# ============================================================================
# Cleanup Functions
# ============================================================================

cleanup_presidio() {
    log_info "=== Cleanup Presidio Mappings (>30 jours) ==="

    if [ "$DRY_RUN" = true ]; then
        # Dry-run: preview only
        COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -tAc \
            "SELECT COUNT(*) FROM core.action_receipts
             WHERE created_at < NOW() - INTERVAL '30 days'
               AND encrypted_mapping IS NOT NULL
               AND purged_at IS NULL;")

        log_info "DRY-RUN: Purgerait $COUNT mappings Presidio"
        echo "$COUNT"
        return 0
    fi

    # Real execution
    COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -tAc \
        "UPDATE core.action_receipts
         SET encrypted_mapping = NULL, purged_at = NOW()
         WHERE created_at < NOW() - INTERVAL '30 days'
           AND encrypted_mapping IS NOT NULL
           AND purged_at IS NULL
         RETURNING id;" | wc -l)

    log_info "Purgé $COUNT mappings Presidio (RGPD compliance)"
    echo "$COUNT"
}

cleanup_logs_docker() {
    log_info "=== Cleanup Logs Docker (>7 jours) ==="

    # H1 FIX: Parse Docker size properly with units
    BEFORE_STR=$(docker system df -v --format '{{.Size}}' 2>/dev/null | head -1 || echo "0")
    BEFORE=$(parse_size_to_bytes "$BEFORE_STR")

    if [ "$DRY_RUN" = true ]; then
        log_info "DRY-RUN: Exécuterait 'docker system prune -f --filter until=168h'"
        echo "0"
        return 0
    fi

    # Prune: containers stopped + images dangling + networks unused + build cache
    # Filter: until=168h = 7 days * 24h
    docker system prune -f --filter "until=168h" 2>&1 | tee -a "$LOG_FILE"

    # After disk usage
    AFTER_STR=$(docker system df -v --format '{{.Size}}' 2>/dev/null | head -1 || echo "0")
    AFTER=$(parse_size_to_bytes "$AFTER_STR")

    FREED=$(calculate_diff "$BEFORE" "$AFTER")
    log_info "Libéré $(format_bytes $FREED) via Docker prune"
    echo "$FREED"
}

cleanup_logs_journald() {
    log_info "=== Cleanup Logs Journald (>7 jours) ==="

    # Check if journalctl available
    if ! command -v journalctl &> /dev/null; then
        log_warn "journalctl non disponible (systemd pas installé)"
        echo "0"
        return 0
    fi

    # H2 FIX: Parse journalctl size properly with units
    BEFORE_STR=$(journalctl --disk-usage 2>/dev/null | grep -oP '\d+\.\d+[KMGT]i?B' | head -1 || echo "0")
    BEFORE=$(parse_size_to_bytes "$BEFORE_STR")

    if [ "$DRY_RUN" = true ]; then
        log_info "DRY-RUN: Exécuterait 'journalctl --vacuum-time=7d'"
        echo "0"
        return 0
    fi

    # Vacuum logs older than 7 days
    journalctl --vacuum-time=7d 2>&1 | tee -a "$LOG_FILE"

    # After disk usage
    AFTER_STR=$(journalctl --disk-usage 2>/dev/null | grep -oP '\d+\.\d+[KMGT]i?B' | head -1 || echo "0")
    AFTER=$(parse_size_to_bytes "$AFTER_STR")

    FREED=$(calculate_diff "$BEFORE" "$AFTER")
    log_info "Libéré $(format_bytes $FREED) via journald vacuum"
    echo "$FREED"
}

cleanup_backups() {
    log_info "=== Cleanup Backups VPS (>30 jours, retention_policy='keep_7_days') ==="

    # Get list of backups to delete
    BACKUPS=$(psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -tAc \
        "SELECT filename FROM core.backup_metadata
         WHERE retention_policy = 'keep_7_days'
           AND backup_date < NOW() - INTERVAL '30 days'
           AND deleted_at IS NULL;" || echo "")

    if [ -z "$BACKUPS" ]; then
        log_info "Aucun backup VPS à supprimer"
        echo "0"
        return 0
    fi

    COUNT=0
    FREED=0

    for filename in $BACKUPS; do
        filepath="/backups/$filename"

        if [ "$DRY_RUN" = true ]; then
            if [ -f "$filepath" ]; then
                # H3 FIX: Use du -sb (portable) instead of stat -c%s (GNU only)
                SIZE=$(du -sb "$filepath" 2>/dev/null | cut -f1 || echo "0")
                FREED=$((FREED + SIZE))
                COUNT=$((COUNT + 1))
                log_info "DRY-RUN: Supprimerait $filepath ($(format_bytes $SIZE))"
            fi
        else
            if [ -f "$filepath" ]; then
                # H3 FIX: Use du -sb (portable) instead of stat -c%s (GNU only)
                SIZE=$(du -sb "$filepath" 2>/dev/null | cut -f1 || echo "0")
                rm -f "$filepath"
                FREED=$((FREED + SIZE))
                COUNT=$((COUNT + 1))
                log_info "Supprimé $filepath ($(format_bytes $SIZE))"
            else
                log_warn "Fichier introuvable : $filepath (déjà supprimé?)"
            fi
        fi
    done

    # Soft delete in database (mark deleted_at)
    if [ "$DRY_RUN" = false ]; then
        psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -c \
            "UPDATE core.backup_metadata
             SET deleted_at = NOW()
             WHERE retention_policy = 'keep_7_days'
               AND backup_date < NOW() - INTERVAL '30 days'
               AND deleted_at IS NULL;" 2>&1 | tee -a "$LOG_FILE"
    fi

    log_info "Supprimé $COUNT backups VPS, libéré $(format_bytes $FREED)"
    echo "$FREED"
}

cleanup_transit() {
    log_info "=== Cleanup Zone Transit (fichiers >24h) ==="

    # Check if transit dir exists
    if [ ! -d "$TRANSIT_DIR" ]; then
        log_warn "Répertoire transit introuvable : $TRANSIT_DIR"
        echo "0"
        return 0
    fi

    # Before disk usage
    BEFORE=$(du -sb "$TRANSIT_DIR" 2>/dev/null | cut -f1 || echo "0")

    if [ "$DRY_RUN" = true ]; then
        # Preview files to delete
        OLD_FILES=$(find "$TRANSIT_DIR" -type f -mtime +1 2>/dev/null || echo "")
        if [ -n "$OLD_FILES" ]; then
            log_info "DRY-RUN: Supprimerait fichiers :"
            echo "$OLD_FILES" | while read -r file; do
                # H3 FIX: Use du -sb (portable) instead of stat -c%s (GNU only)
                SIZE=$(du -sb "$file" 2>/dev/null | cut -f1 || echo "0")
                log_info "  - $file ($(format_bytes $SIZE))"
            done
        else
            log_info "DRY-RUN: Aucun fichier >24h à supprimer"
        fi
        echo "0"
        return 0
    fi

    # Delete files older than 24h (mtime +1 = >24h)
    find "$TRANSIT_DIR" -type f -mtime +1 -delete 2>&1 | tee -a "$LOG_FILE"

    # After disk usage
    AFTER=$(du -sb "$TRANSIT_DIR" 2>/dev/null | cut -f1 || echo "0")

    FREED=$(calculate_diff "$BEFORE" "$AFTER")
    log_info "Libéré $(format_bytes $FREED) zone transit"
    echo "$FREED"
}

# ============================================================================
# Notification Function
# ============================================================================

send_telegram_notification() {
    local status="$1"
    local presidio_count="$2"
    local docker_freed="$3"
    local journald_freed="$4"
    local backup_freed="$5"
    local transit_freed="$6"
    local duration="$7"

    # Skip if Telegram not configured
    if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_SUPERGROUP_ID" ] || [ -z "$TOPIC_SYSTEM_ID" ]; then
        log_warn "Telegram non configuré - notification skip"
        return 0
    fi

    # Calculate total freed
    local total_freed=$((docker_freed + journald_freed + backup_freed + transit_freed))

    # Build message
    local message="🧹 <b>Cleanup Quotidien</b> - $(date '+%Y-%m-%d %H:%M')\n\n"

    if [ "$status" = "success" ]; then
        message+="✅ <b>Status:</b> Success\n\n"
    else
        message+="⚠️  <b>Status:</b> Partial\n\n"
    fi

    message+="📊 <b>Espace libéré:</b>\n"
    message+="  • Presidio mappings: $presidio_count enregistrements purgés\n"
    message+="  • Logs Docker: $(format_bytes $docker_freed)\n"
    message+="  • Logs journald: $(format_bytes $journald_freed)\n"
    message+="  • Backups VPS: $(format_bytes $backup_freed)\n"
    message+="  • Zone transit: $(format_bytes $transit_freed)\n\n"
    message+="💾 <b>Total libéré:</b> $(format_bytes $total_freed)\n"
    message+="⏱️  <b>Durée:</b> ${duration}s"

    # Send to Telegram topic System
    # L2 FIX: Add --max-time 10 to prevent indefinite hang
    # H4 FIX: Capture curl exit code to verify notification sent
    if curl -s --max-time 10 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_SUPERGROUP_ID}" \
        -d "message_thread_id=${TOPIC_SYSTEM_ID}" \
        -d "text=${message}" \
        -d "parse_mode=HTML" 2>&1 | tee -a "$LOG_FILE"; then
        log_info "Notification Telegram envoyée (topic System)"
    else
        log_error "Échec envoi notification Telegram (HTTP error or timeout)"
        return 1
    fi
}

# ============================================================================
# Main Function
# ============================================================================

main() {
    local start_time
    start_time=$(date +%s)

    log_info "=============================================="
    log_info "Cleanup Disk - Début $(date '+%Y-%m-%d %H:%M:%S')"
    log_info "=============================================="

    # Check for dry-run mode
    if [ "${1:-}" = "--dry-run" ]; then
        DRY_RUN=true
        log_info "MODE DRY-RUN - Aucune suppression réelle"
    fi

    # Execute cleanups (continue on error)
    local status="success"
    local errors=()

    local presidio_count=0
    local docker_freed=0
    local journald_freed=0
    local backup_freed=0
    local transit_freed=0

    # Cleanup Presidio
    if presidio_count=$(cleanup_presidio 2>&1); then
        log_info "✅ Presidio cleanup : OK ($presidio_count mappings)"
    else
        status="partial"
        errors+=("Presidio")
        log_error "❌ Presidio cleanup : ERREUR"
    fi

    # Cleanup Logs Docker
    if docker_freed=$(cleanup_logs_docker 2>&1); then
        log_info "✅ Docker logs cleanup : OK ($(format_bytes $docker_freed))"
    else
        status="partial"
        errors+=("Docker")
        log_error "❌ Docker logs cleanup : ERREUR"
    fi

    # Cleanup Logs Journald
    if journald_freed=$(cleanup_logs_journald 2>&1); then
        log_info "✅ Journald logs cleanup : OK ($(format_bytes $journald_freed))"
    else
        status="partial"
        errors+=("Journald")
        log_error "❌ Journald logs cleanup : ERREUR"
    fi

    # Cleanup Backups
    if backup_freed=$(cleanup_backups 2>&1); then
        log_info "✅ Backups cleanup : OK ($(format_bytes $backup_freed))"
    else
        status="partial"
        errors+=("Backups")
        log_error "❌ Backups cleanup : ERREUR"
    fi

    # Cleanup Transit
    if transit_freed=$(cleanup_transit 2>&1); then
        log_info "✅ Transit cleanup : OK ($(format_bytes $transit_freed))"
    else
        status="partial"
        errors+=("Transit")
        log_error "❌ Transit cleanup : ERREUR"
    fi

    # Cleanup Attachments Transit (Story 2.4)
    local attachments_freed=0
    if [ -x "$(dirname "${BASH_SOURCE[0]}")/cleanup-attachments-transit.sh" ]; then
        log_info "Exécution cleanup-attachments-transit.sh (Story 2.4)..."
        if "$(dirname "${BASH_SOURCE[0]}")/cleanup-attachments-transit.sh" 2>&1 | tee -a "$LOG_FILE"; then
            log_info "✅ Attachments transit cleanup : OK"
        else
            status="partial"
            errors+=("Attachments")
            log_error "❌ Attachments transit cleanup : ERREUR"
        fi
    else
        log_warn "cleanup-attachments-transit.sh non trouvé ou non exécutable (Story 2.4 skip)"
    fi

    # Calculate duration
    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # Report status
    if [ "$status" = "partial" ]; then
        log_warn "⚠️  Cleanup partiel - Erreurs: ${errors[*]}"
    else
        log_info "✅ Cleanup complet - Succès"
    fi

    # Send Telegram notification
    if [ "$DRY_RUN" = false ]; then
        send_telegram_notification "$status" "$presidio_count" "$docker_freed" "$journald_freed" "$backup_freed" "$transit_freed" "$duration"
    else
        log_info "DRY-RUN: Notification Telegram skip"
    fi

    log_info "=============================================="
    log_info "Cleanup Disk - Fin (durée: ${duration}s)"
    log_info "=============================================="

    # Exit with error code if partial
    if [ "$status" = "partial" ]; then
        exit 1
    fi

    exit 0
}

# ============================================================================
# Script Entry Point
# ============================================================================

main "$@"
