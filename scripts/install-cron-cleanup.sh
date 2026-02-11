#!/bin/bash
#
# install-cron-cleanup.sh - Installation cron cleanup quotidien
# Story 1.15 - Task 1.2
#
# Usage: sudo bash scripts/install-cron-cleanup.sh
#
# Ce script configure le cleanup quotidien Friday 2.0 sur VPS prod

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "=============================================="
echo "Installation Cron Cleanup Friday 2.0"
echo "=============================================="

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ ERREUR: Ce script doit être exécuté avec sudo${NC}"
    echo "Usage: sudo bash scripts/install-cron-cleanup.sh"
    exit 1
fi

# Get actual user (not root if using sudo)
ACTUAL_USER="${SUDO_USER:-friday}"

echo ""
echo "Configuration utilisateur: $ACTUAL_USER"
echo ""

# ============================================================================
# Subtask 1.2.1: Créer entrée cron
# ============================================================================

echo "1. Configuration cron entry..."

# Cron entry: 5 3 * * * (03:05 daily)
CRON_ENTRY="5 3 * * * /opt/friday-2.0/scripts/cleanup-disk.sh >> /var/log/friday/cleanup-disk.log 2>&1"

# Check if cron entry already exists
if sudo -u "$ACTUAL_USER" crontab -l 2>/dev/null | grep -q "cleanup-disk.sh"; then
    echo -e "${YELLOW}⚠️  Cron entry déjà présente, mise à jour...${NC}"
    # Remove old entry
    sudo -u "$ACTUAL_USER" crontab -l 2>/dev/null | grep -v "cleanup-disk.sh" | sudo -u "$ACTUAL_USER" crontab -
fi

# Add new cron entry
(sudo -u "$ACTUAL_USER" crontab -l 2>/dev/null; echo "$CRON_ENTRY") | sudo -u "$ACTUAL_USER" crontab -

echo -e "${GREEN}✅ Cron entry créée : 5 3 * * * (03:05 quotidien)${NC}"

# Verify
echo ""
echo "Cron entry installée :"
sudo -u "$ACTUAL_USER" crontab -l | grep "cleanup-disk.sh"

# ============================================================================
# Subtask 1.2.2: Créer répertoire logs
# ============================================================================

echo ""
echo "2. Création répertoire logs..."

mkdir -p /var/log/friday
chown "$ACTUAL_USER:$ACTUAL_USER" /var/log/friday
chmod 755 /var/log/friday

echo -e "${GREEN}✅ Répertoire créé : /var/log/friday${NC}"

# ============================================================================
# Subtask 1.2.3: Configurer rotation logs cleanup
# ============================================================================

echo ""
echo "3. Configuration logrotate..."

# Copy logrotate config
LOGROTATE_CONFIG="/etc/logrotate.d/friday-cleanup"

if [ ! -f "$LOGROTATE_CONFIG" ]; then
    cp /opt/friday-2.0/config/logrotate.d/friday-cleanup "$LOGROTATE_CONFIG"
    chmod 644 "$LOGROTATE_CONFIG"
    echo -e "${GREEN}✅ Logrotate config installée : $LOGROTATE_CONFIG${NC}"
else
    echo -e "${YELLOW}⚠️  Logrotate config déjà présente${NC}"
fi

# Test logrotate config
if logrotate -d "$LOGROTATE_CONFIG" 2>&1 | grep -q "error"; then
    echo -e "${RED}❌ ERREUR: Logrotate config invalide${NC}"
    exit 1
else
    echo -e "${GREEN}✅ Logrotate config valide${NC}"
fi

# ============================================================================
# Subtask 1.2.4: Tester cron manuellement (dry-run)
# ============================================================================

echo ""
echo "4. Test manuel cleanup (dry-run)..."

# Make script executable
chmod +x /opt/friday-2.0/scripts/cleanup-disk.sh

# Run dry-run as actual user
if sudo -u "$ACTUAL_USER" bash /opt/friday-2.0/scripts/cleanup-disk.sh --dry-run; then
    echo -e "${GREEN}✅ Test dry-run : PASS${NC}"
else
    echo -e "${RED}❌ ERREUR: Test dry-run a échoué${NC}"
    exit 1
fi

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "=============================================="
echo -e "${GREEN}✅ Installation Cron Cleanup : COMPLETE${NC}"
echo "=============================================="
echo ""
echo "Configuration installée :"
echo "  • Cron entry : 5 3 * * * (03:05 quotidien)"
echo "  • Log directory : /var/log/friday/"
echo "  • Logrotate config : /etc/logrotate.d/friday-cleanup"
echo "  • Script exécutable : /opt/friday-2.0/scripts/cleanup-disk.sh"
echo ""
echo "Prochaines étapes :"
echo "  1. Attendre première exécution cron (demain 03:05)"
echo "  2. Vérifier logs : tail -f /var/log/friday/cleanup-disk.log"
echo "  3. Vérifier notification Telegram topic System"
echo ""
echo "Test manuel immédiat (optionnel) :"
echo "  sudo -u $ACTUAL_USER bash /opt/friday-2.0/scripts/cleanup-disk.sh"
echo ""
