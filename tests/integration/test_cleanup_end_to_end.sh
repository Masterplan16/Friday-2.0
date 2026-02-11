#!/bin/bash
#
# test_cleanup_end_to_end.sh - Test E2E cleanup complet
# Story 1.15 - Friday 2.0
#
# Test intégration : Cleanup complet + vérification résultats

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=============================================="
echo "Test E2E : Cleanup Disk Complet"
echo "=============================================="

# Configuration
DB_USER="${POSTGRES_USER:-friday}"
DB_NAME="${POSTGRES_DB:-friday_test}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
TRANSIT_DIR="/tmp/test_transit_cleanup"
SCRIPT_PATH="scripts/cleanup-disk.sh"

# Check script exists
if [ ! -f "$SCRIPT_PATH" ]; then
    echo -e "${RED}❌ FAIL: Script cleanup-disk.sh not found${NC}"
    exit 1
fi

# ============================================================================
# Setup Test Data
# ============================================================================

echo ""
echo "1. Setup: Création données test..."

# Cleanup préalable
psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -c \
    "DELETE FROM core.action_receipts WHERE id LIKE 'e2e-test-%';" 2>/dev/null || true

psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -c \
    "DELETE FROM core.backup_metadata WHERE filename LIKE 'e2e-test-%';" 2>/dev/null || true

# Create old action receipt with encrypted_mapping (>30 days)
psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -c \
    "INSERT INTO core.action_receipts (id, module, action, created_at, encrypted_mapping, status, trust_level, confidence)
     VALUES ('e2e-test-old-receipt', 'test', 'test_action', NOW() - INTERVAL '31 days', 'encrypted_data'::bytea, 'auto', 'auto', 0.95);" || {
    echo -e "${RED}❌ FAIL: Cannot insert test receipt${NC}"
    exit 1
}

# Create recent action receipt (should NOT be purged)
psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -c \
    "INSERT INTO core.action_receipts (id, module, action, created_at, encrypted_mapping, status, trust_level, confidence)
     VALUES ('e2e-test-recent-receipt', 'test', 'test_action', NOW() - INTERVAL '10 days', 'encrypted_data_recent'::bytea, 'auto', 'auto', 0.95);" || {
    echo -e "${RED}❌ FAIL: Cannot insert recent receipt${NC}"
    exit 1
}

# Create old backup VPS (should be deleted)
psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -c \
    "INSERT INTO core.backup_metadata (filename, backup_date, size_bytes, checksum_sha256, retention_policy)
     VALUES ('e2e-test-old-vps-backup.dump.age', NOW() - INTERVAL '35 days', 1000000, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'keep_7_days');" || {
    echo -e "${RED}❌ FAIL: Cannot insert test backup${NC}"
    exit 1
}

# Create PC backup (should NOT be deleted)
psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -c \
    "INSERT INTO core.backup_metadata (filename, backup_date, size_bytes, checksum_sha256, retention_policy)
     VALUES ('e2e-test-pc-backup.dump.age', NOW() - INTERVAL '35 days', 1000000, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'keep_30_days');" || {
    echo -e "${RED}❌ FAIL: Cannot insert PC backup${NC}"
    exit 1
}

# Create transit directory with old file
mkdir -p "$TRANSIT_DIR"
echo "test content old" > "$TRANSIT_DIR/old_file_e2e.txt"
# Modify timestamp to 2 days ago
touch -d "2 days ago" "$TRANSIT_DIR/old_file_e2e.txt"

# Create recent file (should NOT be deleted)
echo "test content recent" > "$TRANSIT_DIR/recent_file_e2e.txt"

echo -e "${GREEN}✅ Setup complet${NC}"

# ============================================================================
# Execute Cleanup Script
# ============================================================================

echo ""
echo "2. Exécution: cleanup-disk.sh..."

# Export vars for script
export POSTGRES_USER="$DB_USER"
export POSTGRES_DB="$DB_NAME"
export POSTGRES_HOST="$DB_HOST"
export POSTGRES_PORT="$DB_PORT"
export TRANSIT_DIR="$TRANSIT_DIR"
export LOG_FILE="/tmp/test_cleanup_e2e.log"

# Execute script
if bash "$SCRIPT_PATH" 2>&1 | tee /tmp/test_cleanup_e2e_output.log; then
    echo -e "${GREEN}✅ Script exécuté avec succès${NC}"
else
    echo -e "${YELLOW}⚠️  Script avec erreurs (peut être normal si Docker/journald non dispo)${NC}"
fi

# ============================================================================
# Verify Results
# ============================================================================

echo ""
echo "3. Vérification: Résultats cleanup..."

ERRORS=0

# Verify old receipt purged
OLD_RECEIPT=$(psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -tAc \
    "SELECT COUNT(*) FROM core.action_receipts
     WHERE id = 'e2e-test-old-receipt' AND encrypted_mapping IS NULL AND purged_at IS NOT NULL;")

if [ "$OLD_RECEIPT" -eq 1 ]; then
    echo -e "${GREEN}✅ Presidio: Old receipt purgé${NC}"
else
    echo -e "${RED}❌ FAIL: Old receipt non purgé (encrypted_mapping toujours présent)${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Verify recent receipt NOT purged
RECENT_RECEIPT=$(psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -tAc \
    "SELECT COUNT(*) FROM core.action_receipts
     WHERE id = 'e2e-test-recent-receipt' AND encrypted_mapping IS NOT NULL AND purged_at IS NULL;")

if [ "$RECENT_RECEIPT" -eq 1 ]; then
    echo -e "${GREEN}✅ Presidio: Recent receipt préservé${NC}"
else
    echo -e "${RED}❌ FAIL: Recent receipt incorrectement purgé${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Verify VPS backup deleted
VPS_BACKUP=$(psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -tAc \
    "SELECT COUNT(*) FROM core.backup_metadata
     WHERE filename = 'e2e-test-old-vps-backup.dump.age' AND deleted_at IS NOT NULL;")

if [ "$VPS_BACKUP" -eq 1 ]; then
    echo -e "${GREEN}✅ Backups: VPS backup marqué deleted${NC}"
else
    echo -e "${RED}❌ FAIL: VPS backup non marqué deleted${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Verify PC backup preserved
PC_BACKUP=$(psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -tAc \
    "SELECT COUNT(*) FROM core.backup_metadata
     WHERE filename = 'e2e-test-pc-backup.dump.age' AND deleted_at IS NULL;")

if [ "$PC_BACKUP" -eq 1 ]; then
    echo -e "${GREEN}✅ Backups: PC backup préservé${NC}"
else
    echo -e "${RED}❌ FAIL: PC backup incorrectement marqué deleted${NC}"
    ERRORS=$((ERRORS + 1))
fi

# M4 FIX: Verify Docker/journald logs cleanup (AC2)
if command -v docker &> /dev/null; then
    # Check Docker cleanup executed (look for message in logs)
    if grep -q "Docker prune" /tmp/test_cleanup_e2e_output.log 2>/dev/null; then
        echo -e "${GREEN}✅ Docker logs: Cleanup executed${NC}"
    else
        echo -e "${YELLOW}⚠️  WARNING: Docker cleanup not detected in logs${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  WARNING: Docker not available, skipping Docker logs verification${NC}"
fi

if command -v journalctl &> /dev/null; then
    # Check journald cleanup executed (look for message in logs)
    if grep -q "journald vacuum" /tmp/test_cleanup_e2e_output.log 2>/dev/null; then
        echo -e "${GREEN}✅ Journald logs: Cleanup executed${NC}"
    else
        echo -e "${YELLOW}⚠️  WARNING: Journald cleanup not detected in logs${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  WARNING: journalctl not available, skipping journald verification${NC}"
fi

# Verify old transit file deleted
if [ ! -f "$TRANSIT_DIR/old_file_e2e.txt" ]; then
    echo -e "${GREEN}✅ Transit: Old file supprimé${NC}"
else
    echo -e "${RED}❌ FAIL: Old file transit toujours présent${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Verify recent transit file preserved
if [ -f "$TRANSIT_DIR/recent_file_e2e.txt" ]; then
    echo -e "${GREEN}✅ Transit: Recent file préservé${NC}"
else
    echo -e "${RED}❌ FAIL: Recent file transit incorrectement supprimé${NC}"
    ERRORS=$((ERRORS + 1))
fi

# ============================================================================
# Cleanup
# ============================================================================

echo ""
echo "4. Cleanup: Suppression données test..."

psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -c \
    "DELETE FROM core.action_receipts WHERE id LIKE 'e2e-test-%';" 2>/dev/null || true

psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -c \
    "DELETE FROM core.backup_metadata WHERE filename LIKE 'e2e-test-%';" 2>/dev/null || true

rm -rf "$TRANSIT_DIR"

echo -e "${GREEN}✅ Cleanup test complet${NC}"

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "=============================================="
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ Test E2E Cleanup : PASS${NC}"
    echo "Tous les résultats attendus vérifiés"
    exit 0
else
    echo -e "${RED}❌ Test E2E Cleanup : FAIL${NC}"
    echo "Nombre d'erreurs: $ERRORS"
    exit 1
fi
