#!/bin/bash
# Friday 2.0 - Script sync backups vers PC Mainteneur via Tailscale
# Story 1.12 - Task 2.2
# Utilise rsync + SSH + Tailscale pour transmission sécurisée

set -euo pipefail

# ════════════════════════════════════════════════════════════════════════
# Configuration
# ════════════════════════════════════════════════════════════════════════

# Couleurs
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; NC=''
fi

# Paths
BACKUP_DIR="${BACKUP_DIR:-/backups}"
LOG_FILE="${BACKUP_DIR}/sync.log"

# Tailscale PC config (de .env)
PC_HOSTNAME="${TAILSCALE_PC_HOSTNAME:-mainteneur-pc}"
PC_USER="${PC_USER:-mainteneur}"
PC_BACKUP_DIR="${PC_BACKUP_DIR:-/mnt/backups/friday-vps}"

# SSH config
SSH_KEY="${SSH_KEY_PATH:-$HOME/.ssh/friday_backup_key}"
# FIX C3: Accept new hosts but reject changed keys (prevent MITM)
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=30"

# Database config (pour logging metadata)
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-friday}"
POSTGRES_USER="${POSTGRES_USER:-friday}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD}"

# ════════════════════════════════════════════════════════════════════════
# Functions
# ════════════════════════════════════════════════════════════════════════

log() {
    local level=$1
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    echo -e "${timestamp} [${level}] ${message}" | tee -a "$LOG_FILE"
}

log_info() {
    log "INFO" "${GREEN}$*${NC}"
}

log_warn() {
    log "WARN" "${YELLOW}$*${NC}"
}

log_error() {
    log "ERROR" "${RED}$*${NC}"
}

# ════════════════════════════════════════════════════════════════════════
# Pre-flight Checks
# ════════════════════════════════════════════════════════════════════════

log_info "═══════════════════════════════════════════════════"
log_info "   Friday 2.0 - Sync Backups vers PC"
log_info "   Story 1.12 - Task 2.2"
log_info "═══════════════════════════════════════════════════"

# Vérifier backup dir
if [ ! -d "$BACKUP_DIR" ]; then
    log_error "Backup directory not found: $BACKUP_DIR"
    exit 1
fi

# Compter backups à synchroniser
BACKUP_COUNT=$(find "$BACKUP_DIR" -name "friday_backup_*.age" -type f | wc -l)

if [ "$BACKUP_COUNT" -eq 0 ]; then
    log_warn "No encrypted backups found in $BACKUP_DIR"
    log_warn "Run scripts/backup.sh first"
    exit 0
fi

log_info "Found $BACKUP_COUNT encrypted backup(s) to sync"

# Vérifier clé SSH
if [ ! -f "$SSH_KEY" ]; then
    log_error "SSH key not found: $SSH_KEY"
    log_error "Generate with: ssh-keygen -t ed25519 -f $SSH_KEY -N \"\""
    log_error "Then copy to PC: ssh-copy-id -i $SSH_KEY $PC_USER@$PC_HOSTNAME"
    exit 1
fi

log_info "✅ SSH key found: $SSH_KEY"

# ════════════════════════════════════════════════════════════════════════
# Connectivity Test
# ════════════════════════════════════════════════════════════════════════

log_info ""
log_info "Testing connectivity to PC..."
log_info "  Target: $PC_USER@$PC_HOSTNAME"

# Test SSH connexion
if ssh -i "$SSH_KEY" $SSH_OPTS "$PC_USER@$PC_HOSTNAME" "echo 'SSH OK'" &> /dev/null; then
    log_info "✅ SSH connection successful"
else
    log_error "SSH connection failed to $PC_HOSTNAME"
    log_error ""
    log_error "Troubleshooting:"
    log_error "  1. Check PC is online: ping $PC_HOSTNAME"
    log_error "  2. Verify Tailscale: tailscale status | grep $PC_HOSTNAME"
    log_error "  3. Check SSH key authorized: ssh-copy-id -i $SSH_KEY $PC_USER@$PC_HOSTNAME"
    log_error "  4. Verify SSHD running on PC"
    exit 1
fi

# Vérifier/créer dossier destination sur PC
log_info "Ensuring destination directory exists on PC..."

if ssh -i "$SSH_KEY" $SSH_OPTS "$PC_USER@$PC_HOSTNAME" "mkdir -p $PC_BACKUP_DIR && test -w $PC_BACKUP_DIR"; then
    log_info "✅ Destination directory ready: $PC_BACKUP_DIR"
else
    log_error "Cannot create or write to $PC_BACKUP_DIR on PC"
    exit 1
fi

# ════════════════════════════════════════════════════════════════════════
# Rsync Execution
# ════════════════════════════════════════════════════════════════════════

log_info ""
log_info "Starting rsync transfer..."
log_info "  Source: $BACKUP_DIR/*.age"
log_info "  Destination: $PC_USER@$PC_HOSTNAME:$PC_BACKUP_DIR/"

# Subtask 2.2.1: rsync via SSH + Tailscale
# Subtask 2.2.2: Clé SSH Ed25519 sans passphrase (automation)
rsync \
    -avz \
    --progress \
    -e "ssh -i $SSH_KEY $SSH_OPTS" \
    --include="friday_backup_*.age" \
    --exclude="*" \
    "$BACKUP_DIR/" \
    "$PC_USER@$PC_HOSTNAME:$PC_BACKUP_DIR/"

RSYNC_EXIT_CODE=$?

# Subtask 2.2.3: Vérifier transfert réussi (exit code rsync)
if [ $RSYNC_EXIT_CODE -eq 0 ]; then
    log_info "✅ rsync transfer completed successfully"
else
    log_error "rsync failed with exit code: $RSYNC_EXIT_CODE"
    exit $RSYNC_EXIT_CODE
fi

# ════════════════════════════════════════════════════════════════════════
# Metadata Update
# ════════════════════════════════════════════════════════════════════════

log_info ""
log_info "Updating sync metadata..."

# Subtask 2.2.4: Log sync succès dans core.backup_metadata
# Mettre à jour tous les backups récemment syncés
SYNC_TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

if PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT 1 FROM information_schema.tables WHERE table_schema='core' AND table_name='backup_metadata'" | grep -q 1; then

    # Table existe - update synced_to_pc
    UPDATED_COUNT=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t <<EOF
UPDATE core.backup_metadata
SET
    synced_to_pc = true,
    pc_arrival_time = '$SYNC_TIMESTAMP'
WHERE
    synced_to_pc = false
    AND filename LIKE 'friday_backup_%.age';

SELECT COUNT(*) FROM core.backup_metadata WHERE synced_to_pc = true;
EOF
)

    log_info "✅ Metadata updated: $UPDATED_COUNT backup(s) marked as synced"
else
    log_warn "Table core.backup_metadata not found - skipping metadata update"
    log_warn "Run migration 019 to create the table (Task 2.3)"
fi

unset PGPASSWORD

# ════════════════════════════════════════════════════════════════════════
# Verification
# ════════════════════════════════════════════════════════════════════════

log_info ""
log_info "Verifying synced files on PC..."

PC_FILE_COUNT=$(ssh -i "$SSH_KEY" $SSH_OPTS "$PC_USER@$PC_HOSTNAME" \
    "find $PC_BACKUP_DIR -name 'friday_backup_*.age' -type f | wc -l")

log_info "  Files on PC: $PC_FILE_COUNT"
log_info "  Files on VPS: $BACKUP_COUNT"

if [ "$PC_FILE_COUNT" -ge "$BACKUP_COUNT" ]; then
    log_info "✅ Verification passed"
else
    log_warn "⚠️  File count mismatch - some files may not have synced"
fi

# ════════════════════════════════════════════════════════════════════════
# Success Summary
# ════════════════════════════════════════════════════════════════════════

log_info ""
log_info "═══════════════════════════════════════════════════"
log_info "${GREEN}✅ SYNC COMPLETED SUCCESSFULLY${NC}"
log_info "═══════════════════════════════════════════════════"
log_info ""
log_info "Backups synced: $BACKUP_COUNT file(s)"
log_info "Destination: $PC_USER@$PC_HOSTNAME:$PC_BACKUP_DIR/"
log_info "Transport: SSH + Tailscale (WireGuard encrypted)"
log_info ""
log_info "PC backup status:"
log_info "  → Check with: ssh $PC_USER@$PC_HOSTNAME \"ls -lh $PC_BACKUP_DIR\""
log_info "  → Verify encryption: File extension .age indicates encrypted data"
log_info ""

exit 0
