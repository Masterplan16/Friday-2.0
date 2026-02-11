#!/bin/bash
# Quick deploy cleanup RGPD sur VPS - Story 1.15
# Usage: Copier-coller ce script DIRECTEMENT sur le VPS après connexion SSH

set -e

echo "🚀 Déploiement cleanup RGPD..."

# Deploy scripts
sudo mkdir -p /opt/friday-2.0/scripts /opt/friday-2.0/config/logrotate.d
sudo cp /tmp/cleanup-disk.sh /tmp/install-cron-cleanup.sh /tmp/validate-cleanup.sh /opt/friday-2.0/scripts/
sudo cp /tmp/friday-cleanup /opt/friday-2.0/config/logrotate.d/
sudo chmod +x /opt/friday-2.0/scripts/*.sh
sudo chown -R friday:friday /opt/friday-2.0/

echo "✅ Scripts déployés"

# Install cron
echo "⏰ Installation cron..."
sudo bash /opt/friday-2.0/scripts/install-cron-cleanup.sh

echo ""
echo "✅ Déploiement terminé !"
echo ""
echo "Prochaines étapes :"
echo "  1. Validation : bash /opt/friday-2.0/scripts/validate-cleanup.sh"
echo "  2. Test manuel : sudo -u friday bash /opt/friday-2.0/scripts/cleanup-disk.sh"
echo "  3. Voir logs : tail -f /var/log/friday/cleanup-disk.log"
echo ""
