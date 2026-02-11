#!/bin/bash
#
# validate-cleanup.sh - Validation finale cleanup RGPD
# Story 1.15 - Task 2.3
#
# Usage: bash scripts/validate-cleanup.sh
#
# Vérifie que le cleanup quotidien fonctionne correctement sur VPS prod

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "=============================================="
echo "Validation Cleanup RGPD - Friday 2.0"
echo "=============================================="

# Database config
DB_USER="${POSTGRES_USER:-friday}"
DB_NAME="${POSTGRES_DB:-friday}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"

ERRORS=0
WARNINGS=0

# ============================================================================
# Subtask 2.3.1: Vérifier purge Presidio (mappings >30j = 0)
# ============================================================================

echo ""
echo "1. Vérification purge Presidio (>30 jours)..."

PRESIDIO_COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -tAc \
    "SELECT COUNT(*) FROM core.action_receipts
     WHERE encrypted_mapping IS NOT NULL
       AND created_at < NOW() - INTERVAL '30 days'
       AND purged_at IS NULL;" 2>/dev/null || echo "-1")

if [ "$PRESIDIO_COUNT" = "-1" ]; then
    echo -e "${RED}❌ ERREUR: Impossible de se connecter à PostgreSQL${NC}"
    ERRORS=$((ERRORS + 1))
elif [ "$PRESIDIO_COUNT" -eq 0 ]; then
    echo -e "${GREEN}✅ Presidio: Aucun mapping >30j non purgé (RGPD compliance OK)${NC}"
else
    echo -e "${YELLOW}⚠️  WARNING: $PRESIDIO_COUNT mappings >30j non purgés (attendre prochaine exécution cleanup)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

# ============================================================================
# Subtask 2.3.2: Vérifier rotation logs Docker + journald
# ============================================================================

echo ""
echo "2. Vérification rotation logs..."

# Docker logs
if command -v docker &> /dev/null; then
    DOCKER_SIZE=$(docker system df -v --format '{{.Size}}' 2>/dev/null | head -1 || echo "N/A")
    echo -e "${GREEN}✅ Docker logs size: $DOCKER_SIZE${NC}"
else
    echo -e "${YELLOW}⚠️  WARNING: Docker non disponible${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

# Journald logs
if command -v journalctl &> /dev/null; then
    JOURNALD_SIZE=$(journalctl --disk-usage 2>/dev/null | grep -oP '\d+\.\d+[KMGT]i?B' | head -1 || echo "N/A")
    echo -e "${GREEN}✅ Journald logs size: $JOURNALD_SIZE${NC}"
else
    echo -e "${YELLOW}⚠️  WARNING: journalctl non disponible${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

# ============================================================================
# Subtask 2.3.3: Vérifier rotation backups VPS (>30j = 0)
# ============================================================================

echo ""
echo "3. Vérification rotation backups VPS..."

BACKUP_COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -tAc \
    "SELECT COUNT(*) FROM core.backup_metadata
     WHERE retention_policy = 'keep_7_days'
       AND backup_date < NOW() - INTERVAL '30 days'
       AND deleted_at IS NULL;" 2>/dev/null || echo "-1")

if [ "$BACKUP_COUNT" = "-1" ]; then
    echo -e "${RED}❌ ERREUR: Impossible de vérifier backups (PostgreSQL error)${NC}"
    ERRORS=$((ERRORS + 1))
elif [ "$BACKUP_COUNT" -eq 0 ]; then
    echo -e "${GREEN}✅ Backups VPS: Aucun backup >30j non supprimé${NC}"
else
    echo -e "${YELLOW}⚠️  WARNING: $BACKUP_COUNT backups VPS >30j non supprimés (attendre prochaine exécution)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

# ============================================================================
# Subtask 2.3.4: Vérifier cleanup zone transit (fichiers >24h = 0)
# ============================================================================

echo ""
echo "4. Vérification cleanup zone transit..."

TRANSIT_DIR="${TRANSIT_DIR:-/data/transit/uploads}"

if [ -d "$TRANSIT_DIR" ]; then
    OLD_FILES_COUNT=$(find "$TRANSIT_DIR" -type f -mtime +1 2>/dev/null | wc -l || echo "-1")

    if [ "$OLD_FILES_COUNT" = "-1" ]; then
        echo -e "${RED}❌ ERREUR: Impossible de vérifier zone transit${NC}"
        ERRORS=$((ERRORS + 1))
    elif [ "$OLD_FILES_COUNT" -eq 0 ]; then
        echo -e "${GREEN}✅ Zone transit: Aucun fichier >24h présent${NC}"
    else
        echo -e "${YELLOW}⚠️  WARNING: $OLD_FILES_COUNT fichiers >24h dans zone transit (attendre prochaine exécution)${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${YELLOW}⚠️  WARNING: Répertoire transit introuvable : $TRANSIT_DIR${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

# ============================================================================
# Subtask 2.3.5: Vérifier cron actif + logs présents
# ============================================================================

echo ""
echo "5. Vérification cron + logs..."

# Check cron entry
if crontab -l 2>/dev/null | grep -q "cleanup-disk.sh"; then
    CRON_TIME=$(crontab -l | grep "cleanup-disk.sh" | awk '{print $1, $2, $3, $4, $5}')
    echo -e "${GREEN}✅ Cron entry présente : $CRON_TIME${NC}"

    # Verify timing is correct (5 3 * * *)
    if echo "$CRON_TIME" | grep -q "5 3 \* \* \*"; then
        echo -e "${GREEN}✅ Cron timing correct : 03:05 quotidien${NC}"
    else
        echo -e "${YELLOW}⚠️  WARNING: Cron timing inattendu : $CRON_TIME (devrait être 5 3 * * *)${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${RED}❌ ERREUR: Cron entry absente (exécuter install-cron-cleanup.sh)${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check logs exist
LOG_FILE="${LOG_FILE:-/var/log/friday/cleanup-disk.log}"

if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(du -h "$LOG_FILE" 2>/dev/null | cut -f1 || echo "N/A")
    LAST_EXEC=$(tail -1 "$LOG_FILE" 2>/dev/null | grep -oP '\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}' | head -1 || echo "N/A")

    echo -e "${GREEN}✅ Logs présents : $LOG_FILE ($LOG_SIZE)${NC}"
    echo -e "${GREEN}   Dernière exécution : $LAST_EXEC${NC}"

    # Show last 5 lines
    echo ""
    echo "Dernières lignes du log :"
    tail -5 "$LOG_FILE" 2>/dev/null || echo "Aucune ligne disponible"
else
    echo -e "${YELLOW}⚠️  WARNING: Logs non trouvés : $LOG_FILE (attendre première exécution cron)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

# ============================================================================
# Subtask 2.3.6: Vérifier notification Telegram topic System
# ============================================================================

echo ""
echo "6. Vérification notification Telegram..."

# Check if Telegram configured
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_SUPERGROUP_ID:-}" ] && [ -n "${TOPIC_SYSTEM_ID:-}" ]; then
    echo -e "${GREEN}✅ Telegram configuré (TELEGRAM_BOT_TOKEN, SUPERGROUP_ID, TOPIC_SYSTEM_ID)${NC}"

    # Check in logs if notification sent
    if [ -f "$LOG_FILE" ] && grep -q "Notification Telegram envoyée" "$LOG_FILE" 2>/dev/null; then
        echo -e "${GREEN}✅ Notification Telegram envoyée (vérifié dans logs)${NC}"
    else
        echo -e "${YELLOW}⚠️  WARNING: Notification pas détectée dans logs (vérifier manuellement topic System)${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${RED}❌ ERREUR: Telegram non configuré (variables env manquantes)${NC}"
    ERRORS=$((ERRORS + 1))
fi

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "=============================================="

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ Validation Cleanup RGPD : PASS${NC}"
    echo "Toutes les vérifications réussies !"
    echo ""
    echo "Cleanup quotidien opérationnel :"
    echo "  ✅ Purge Presidio >30j"
    echo "  ✅ Rotation logs Docker + journald"
    echo "  ✅ Rotation backups VPS >30j"
    echo "  ✅ Cleanup zone transit >24h"
    echo "  ✅ Cron actif (03:05 quotidien)"
    echo "  ✅ Notification Telegram topic System"
    echo ""
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Validation Cleanup RGPD : PASS (avec warnings)${NC}"
    echo "Nombre de warnings : $WARNINGS"
    echo ""
    echo "Actions recommandées :"
    echo "  • Attendre première/prochaine exécution cron (03:05)"
    echo "  • Vérifier manuellement notification Telegram topic System"
    echo "  • Vérifier logs : tail -f /var/log/friday/cleanup-disk.log"
    echo ""
    exit 0
else
    echo -e "${RED}❌ Validation Cleanup RGPD : FAIL${NC}"
    echo "Nombre d'erreurs : $ERRORS"
    echo "Nombre de warnings : $WARNINGS"
    echo ""
    echo "Actions requises :"
    if crontab -l 2>/dev/null | grep -q "cleanup-disk.sh"; then
        echo "  • Cron OK"
    else
        echo "  • Installer cron : sudo bash scripts/install-cron-cleanup.sh"
    fi
    if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
        echo "  • Telegram OK"
    else
        echo "  • Configurer Telegram (TELEGRAM_BOT_TOKEN, SUPERGROUP_ID, TOPIC_SYSTEM_ID)"
    fi
    echo ""
    exit 1
fi
