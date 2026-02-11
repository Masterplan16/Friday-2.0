#!/bin/bash
#
# deploy-cleanup-to-vps.sh - Déploiement cleanup RGPD sur VPS prod
# Story 1.15 - Déploiement automatisé
#
# Usage: bash scripts/deploy-cleanup-to-vps.sh [VPS_HOST]
#
# Ce script déploie et installe le cleanup RGPD sur VPS prod via SSH/Tailscale

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "=============================================="
echo "Déploiement Cleanup RGPD sur VPS Friday 2.0"
echo "=============================================="
echo ""

# ============================================================================
# Configuration
# ============================================================================

VPS_HOST="${1:-friday-vps}"  # Nom Tailscale ou IP
VPS_USER="${VPS_USER:-friday}"
FRIDAY_DIR="/opt/friday-2.0"

echo -e "${BLUE}Configuration:${NC}"
echo "  VPS Host: $VPS_HOST"
echo "  VPS User: $VPS_USER"
echo "  Friday Dir: $FRIDAY_DIR"
echo ""

# ============================================================================
# Vérifications préalables
# ============================================================================

echo -e "${BLUE}1. Vérifications préalables...${NC}"

# Check SSH access
if ! ssh -q "$VPS_USER@$VPS_HOST" exit 2>/dev/null; then
    echo -e "${RED}❌ ERREUR: Impossible de se connecter à $VPS_USER@$VPS_HOST${NC}"
    echo ""
    echo "Vérifiez que :"
    echo "  1. Tailscale est actif sur ce PC et le VPS"
    echo "  2. La clé SSH est configurée : ssh-copy-id $VPS_USER@$VPS_HOST"
    echo "  3. Le nom d'hôte est correct (vérifier : tailscale status)"
    echo ""
    exit 1
fi

echo -e "${GREEN}✅ Connexion SSH opérationnelle${NC}"

# ============================================================================
# Étape 1: Upload des fichiers
# ============================================================================

echo ""
echo -e "${BLUE}2. Upload des fichiers sur VPS...${NC}"

# Create temp directory on VPS
ssh "$VPS_USER@$VPS_HOST" "mkdir -p /tmp/friday-cleanup-deploy"

# Upload scripts
echo "  → scripts/cleanup-disk.sh"
scp scripts/cleanup-disk.sh "$VPS_USER@$VPS_HOST:/tmp/friday-cleanup-deploy/"

echo "  → scripts/install-cron-cleanup.sh"
scp scripts/install-cron-cleanup.sh "$VPS_USER@$VPS_HOST:/tmp/friday-cleanup-deploy/"

echo "  → scripts/validate-cleanup.sh"
scp scripts/validate-cleanup.sh "$VPS_USER@$VPS_HOST:/tmp/friday-cleanup-deploy/"

echo "  → config/logrotate.d/friday-cleanup"
scp config/logrotate.d/friday-cleanup "$VPS_USER@$VPS_HOST:/tmp/friday-cleanup-deploy/"

echo -e "${GREEN}✅ Fichiers uploadés dans /tmp/friday-cleanup-deploy/${NC}"

# ============================================================================
# Étape 2: Déploiement dans /opt/friday-2.0
# ============================================================================

echo ""
echo -e "${BLUE}3. Déploiement dans $FRIDAY_DIR...${NC}"

ssh "$VPS_USER@$VPS_HOST" bash << 'ENDSSH'
set -e

# Copy scripts to Friday directory
sudo mkdir -p /opt/friday-2.0/scripts
sudo mkdir -p /opt/friday-2.0/config/logrotate.d

sudo cp /tmp/friday-cleanup-deploy/cleanup-disk.sh /opt/friday-2.0/scripts/
sudo cp /tmp/friday-cleanup-deploy/install-cron-cleanup.sh /opt/friday-2.0/scripts/
sudo cp /tmp/friday-cleanup-deploy/validate-cleanup.sh /opt/friday-2.0/scripts/
sudo cp /tmp/friday-cleanup-deploy/friday-cleanup /opt/friday-2.0/config/logrotate.d/

# Make scripts executable
sudo chmod +x /opt/friday-2.0/scripts/cleanup-disk.sh
sudo chmod +x /opt/friday-2.0/scripts/install-cron-cleanup.sh
sudo chmod +x /opt/friday-2.0/scripts/validate-cleanup.sh

# Set ownership
sudo chown -R friday:friday /opt/friday-2.0/scripts
sudo chown -R friday:friday /opt/friday-2.0/config

# Cleanup temp directory
rm -rf /tmp/friday-cleanup-deploy

echo "Déploiement terminé !"
ENDSSH

echo -e "${GREEN}✅ Scripts déployés dans $FRIDAY_DIR/scripts/${NC}"

# ============================================================================
# Étape 3: Installation cron
# ============================================================================

echo ""
echo -e "${BLUE}4. Installation cron cleanup...${NC}"
echo ""

ssh -t "$VPS_USER@$VPS_HOST" "sudo bash $FRIDAY_DIR/scripts/install-cron-cleanup.sh"

# ============================================================================
# Étape 4: Test manuel (optionnel)
# ============================================================================

echo ""
echo -e "${YELLOW}Voulez-vous exécuter un test manuel immédiat ? (y/N)${NC}"
read -r RESPONSE

if [[ "$RESPONSE" =~ ^[Yy]$ ]]; then
    echo ""
    echo -e "${BLUE}5. Exécution test manuel cleanup...${NC}"
    echo ""

    ssh -t "$VPS_USER@$VPS_HOST" "sudo -u friday bash $FRIDAY_DIR/scripts/cleanup-disk.sh"

    echo ""
    echo -e "${GREEN}✅ Test manuel terminé${NC}"
fi

# ============================================================================
# Étape 5: Validation finale
# ============================================================================

echo ""
echo -e "${BLUE}6. Validation installation...${NC}"
echo ""

ssh "$VPS_USER@$VPS_HOST" "bash $FRIDAY_DIR/scripts/validate-cleanup.sh"

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "=============================================="
echo -e "${GREEN}✅ Déploiement Cleanup RGPD : COMPLET${NC}"
echo "=============================================="
echo ""
echo "Installation réussie sur $VPS_HOST :"
echo "  ✅ Scripts déployés dans $FRIDAY_DIR/scripts/"
echo "  ✅ Cron installé : 5 3 * * * (03:05 quotidien)"
echo "  ✅ Logrotate configuré"
echo "  ✅ Validation passée"
echo ""
echo "Prochaines étapes :"
echo "  • Première exécution cron : demain 03:05"
echo "  • Vérifier logs : ssh $VPS_USER@$VPS_HOST 'tail -f /var/log/friday/cleanup-disk.log'"
echo "  • Vérifier notification Telegram topic System"
echo ""
echo "Commandes utiles :"
echo "  • Test manuel : ssh $VPS_USER@$VPS_HOST 'sudo -u friday bash $FRIDAY_DIR/scripts/cleanup-disk.sh'"
echo "  • Validation : ssh $VPS_USER@$VPS_HOST 'bash $FRIDAY_DIR/scripts/validate-cleanup.sh'"
echo "  • Voir cron : ssh $VPS_USER@$VPS_HOST 'crontab -l | grep cleanup'"
echo ""
