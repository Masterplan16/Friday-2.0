#!/bin/bash
# Friday 2.0 - Script orchestration backup PostgreSQL chiffré
# Story 1.12 - Task 2.1
# Exécute pg_dump → compress → encrypt age → log metadata

set -euo pipefail

# ════════════════════════════════════════════════════════════════════════
# Configuration
# ════════════════════════════════════════════════════════════════════════

# Couleurs pour output (si terminal interactif)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

# Paths
BACKUP_DIR="${BACKUP_DIR:-/backups}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Timestamp pour nom fichier
TIMESTAMP=$(date +%Y-%m-%d_%H%M)
BACKUP_FILENAME="friday_backup_${TIMESTAMP}.dump"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_FILENAME}"
ENCRYPTED_PATH="${BACKUP_PATH}.age"

# Database config (de .env ou docker-compose)
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-friday}"
POSTGRES_USER="${POSTGRES_USER:-friday}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD}"

# age encryption
AGE_PUBLIC_KEY="${AGE_PUBLIC_KEY}"

# Logging
LOG_FILE="${BACKUP_DIR}/backup.log"

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

cleanup_on_error() {
    log_error "Backup failed - cleaning up temporary files"

    # Supprimer fichiers temporaires (mais garder .age si existant)
    [ -f "$BACKUP_PATH" ] && rm -f "$BACKUP_PATH"

    exit 1
}

# Trap errors
trap cleanup_on_error ERR

# ════════════════════════════════════════════════════════════════════════
# Pre-flight checks
# ════════════════════════════════════════════════════════════════════════

log_info "═══════════════════════════════════════════════════"
log_info "   Friday 2.0 - Backup PostgreSQL Chiffré"
log_info "   Story 1.12 - Task 2.1"
log_info "═══════════════════════════════════════════════════"

# Vérifier que backup dir existe
if [ ! -d "$BACKUP_DIR" ]; then
    log_info "Creating backup directory: $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR"
fi

# Vérifier variables critiques
if [ -z "$POSTGRES_PASSWORD" ]; then
    log_error "POSTGRES_PASSWORD not set"
    exit 1
fi

if [ -z "$AGE_PUBLIC_KEY" ]; then
    log_error "AGE_PUBLIC_KEY not set - cannot encrypt backup"
    exit 1
fi

# Vérifier que age est installé
if ! command -v age &> /dev/null; then
    log_error "age CLI not found - install with: apk add age"
    exit 1
fi

# Vérifier que pg_dump est accessible
if ! command -v pg_dump &> /dev/null; then
    log_error "pg_dump not found - PostgreSQL client tools required"
    exit 1
fi

log_info "✅ Pre-flight checks passed"

# ════════════════════════════════════════════════════════════════════════
# Database Backup
# ════════════════════════════════════════════════════════════════════════

log_info ""
log_info "Step 1/5: Executing pg_dump..."
log_info "  Host: $POSTGRES_HOST:$POSTGRES_PORT"
log_info "  Database: $POSTGRES_DB"
log_info "  User: $POSTGRES_USER"
log_info "  Schemas: core, ingestion, knowledge (incl. pgvector)"

# Subtask 2.1.1: pg_dump avec format custom (-Fc)
# Subtask 2.1.2: Inclut automatiquement les 3 schemas + pgvector extension
# Subtask 2.1.3: Compression gzip niveau 6 (défaut PostgreSQL 16)
export PGPASSWORD="$POSTGRES_PASSWORD"

pg_dump \
    -h "$POSTGRES_HOST" \
    -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -F c \
    -Z 6 \
    -f "$BACKUP_PATH"

unset PGPASSWORD

if [ ! -f "$BACKUP_PATH" ]; then
    log_error "pg_dump failed - backup file not created"
    exit 1
fi

log_info "✅ pg_dump completed"

# ════════════════════════════════════════════════════════════════════════
# Validation
# ════════════════════════════════════════════════════════════════════════

log_info ""
log_info "Step 2/5: Validating backup file..."

# Subtask 2.1.7: Vérifier taille > 10 MB (sanity check)
BACKUP_SIZE_BYTES=$(stat -c%s "$BACKUP_PATH" 2>/dev/null || stat -f%z "$BACKUP_PATH" 2>/dev/null)
BACKUP_SIZE_MB=$((BACKUP_SIZE_BYTES / 1024 / 1024))

log_info "  File: $BACKUP_FILENAME"
log_info "  Size: ${BACKUP_SIZE_MB} MB (${BACKUP_SIZE_BYTES} bytes)"

if [ "$BACKUP_SIZE_BYTES" -lt 10485760 ]; then  # 10 MB = 10 * 1024 * 1024
    log_warn "Backup size < 10 MB - this may indicate an incomplete backup"
    log_warn "Continuing anyway, but manual verification recommended"
fi

# Calculer checksum SHA256
CHECKSUM=$(sha256sum "$BACKUP_PATH" | awk '{print $1}')
log_info "  SHA256: $CHECKSUM"

log_info "✅ Backup file validated"

# ════════════════════════════════════════════════════════════════════════
# Encryption
# ════════════════════════════════════════════════════════════════════════

log_info ""
log_info "Step 3/5: Encrypting with age..."
log_info "  Public key: ${AGE_PUBLIC_KEY:0:20}...${AGE_PUBLIC_KEY: -10}"

# Subtask 2.1.6: Chiffrer avec age
age -r "$AGE_PUBLIC_KEY" -o "$ENCRYPTED_PATH" < "$BACKUP_PATH"

if [ ! -f "$ENCRYPTED_PATH" ]; then
    log_error "age encryption failed - encrypted file not created"
    exit 1
fi

ENCRYPTED_SIZE_BYTES=$(stat -c%s "$ENCRYPTED_PATH" 2>/dev/null || stat -f%z "$ENCRYPTED_PATH" 2>/dev/null)
ENCRYPTED_SIZE_MB=$((ENCRYPTED_SIZE_BYTES / 1024 / 1024))

log_info "  Encrypted file: ${BACKUP_FILENAME}.age"
log_info "  Size: ${ENCRYPTED_SIZE_MB} MB (${ENCRYPTED_SIZE_BYTES} bytes)"
log_info "✅ Backup encrypted"

# Supprimer fichier non chiffré
log_info "Removing unencrypted backup..."
rm -f "$BACKUP_PATH"

# ════════════════════════════════════════════════════════════════════════
# Metadata Logging
# ════════════════════════════════════════════════════════════════════════

log_info ""
log_info "Step 4/5: Logging metadata to PostgreSQL..."

# Subtask 2.1.8: Log succès dans core.backup_metadata
# Note: À implémenter après migration 019 (Task 2.3)
# Pour l'instant, skip si table n'existe pas encore

BACKUP_DATE=$(date '+%Y-%m-%d %H:%M:%S')
FILENAME_AGE="${BACKUP_FILENAME}.age"

if PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT 1 FROM information_schema.tables WHERE table_schema='core' AND table_name='backup_metadata'" | grep -q 1; then

    # Table existe - insérer metadata
    PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<EOF
INSERT INTO core.backup_metadata (
    backup_date,
    filename,
    size_bytes,
    checksum_sha256,
    encrypted_with_age,
    synced_to_pc,
    retention_policy
) VALUES (
    '$BACKUP_DATE',
    '$FILENAME_AGE',
    $ENCRYPTED_SIZE_BYTES,
    '$CHECKSUM',
    true,
    false,
    'keep_7_days'
);
EOF

    log_info "✅ Metadata logged to core.backup_metadata"
else
    log_warn "Table core.backup_metadata not found - skipping metadata logging"
    log_warn "Run migration 019 to create the table (Task 2.3)"
fi

unset PGPASSWORD

# ════════════════════════════════════════════════════════════════════════
# Cleanup Old Backups (>7 days)
# ════════════════════════════════════════════════════════════════════════

log_info ""
log_info "Step 5/5: Cleaning up old backups (>7 days)..."

# FIX H3: POSIX-compliant alternative to -delete (macOS/BSD compatible)
DELETED_COUNT=$(find "$BACKUP_DIR" -name "friday_backup_*.age" -type f -mtime +7 -exec rm -f {} \; -print | wc -l)

if [ "$DELETED_COUNT" -gt 0 ]; then
    log_info "✅ Deleted $DELETED_COUNT old backup(s)"
else
    log_info "No old backups to delete"
fi

# ════════════════════════════════════════════════════════════════════════
# Success Summary
# ════════════════════════════════════════════════════════════════════════

log_info ""
log_info "═══════════════════════════════════════════════════"
log_info "${GREEN}✅ BACKUP COMPLETED SUCCESSFULLY${NC}"
log_info "═══════════════════════════════════════════════════"
log_info ""
log_info "Backup file: $ENCRYPTED_PATH"
log_info "Size: ${ENCRYPTED_SIZE_MB} MB"
log_info "Checksum: $CHECKSUM"
log_info "Encrypted: ✅ (age)"
log_info ""
log_info "Next steps:"
log_info "  → Run scripts/rsync-to-pc.sh to sync to PC"
log_info "  → Or wait for n8n cron (03h00 daily)"
log_info ""

# FIX H1: Output JSON pour n8n (sur stdout, pas dans log file)
cat <<EOF
{
  "success": true,
  "filename": "${BACKUP_FILENAME}.age",
  "size_mb": ${ENCRYPTED_SIZE_MB},
  "size_bytes": ${ENCRYPTED_SIZE_BYTES},
  "checksum": "${CHECKSUM}",
  "backup_date": "${BACKUP_DATE}",
  "encrypted": true
}
EOF

# Subtask 2.1.9: Exit code 0 = succès
exit 0
