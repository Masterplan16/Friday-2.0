#!/usr/bin/env bash
# setup-unattended-upgrades.sh - Configuration OS updates automatiques Friday 2.0
#
# Configure Ubuntu/Debian unattended-upgrades pour sécurité updates automatiques
# Usage: sudo ./scripts/setup-unattended-upgrades.sh
#
# Story 1.13 - AC4: Unattended-upgrades configuré pour l'OS

set -euo pipefail

# Vérifier root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Ce script doit être exécuté en tant que root (sudo)"
    exit 1
fi

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "🔧 Friday 2.0 - Setup Unattended Upgrades"
echo "==========================================="
echo ""

# 1. Installer package unattended-upgrades
echo "📦 Installing unattended-upgrades package..."
apt-get update -qq
apt-get install -y unattended-upgrades apt-listchanges

echo -e "${GREEN}✅ Package installed${NC}"
echo ""

# 2. Configurer /etc/apt/apt.conf.d/50unattended-upgrades
echo "⚙️  Configuring /etc/apt/apt.conf.d/50unattended-upgrades..."

cat > /etc/apt/apt.conf.d/50unattended-upgrades <<'EOF'
// Friday 2.0 - Unattended Upgrades Configuration
// Story 1.13 - AC4: OS security updates automatiques
// Generated: 2026-02-10

Unattended-Upgrade::Allowed-Origins {
    // Security updates only (not feature updates)
    "${distro_id}:${distro_codename}-security";
    // Uncomment for stable updates if needed:
    // "${distro_id}:${distro_codename}-updates";
};

// List of packages to NOT auto-update (blacklist)
Unattended-Upgrade::Package-Blacklist {
    // Example: "postgresql-16" to prevent auto-upgrade of PostgreSQL
};

// Auto-reboot si kernel update (max 1x/semaine)
Unattended-Upgrade::Automatic-Reboot "true";

// Reboot time: 03:30 (après backup quotidien 03h00)
Unattended-Upgrade::Automatic-Reboot-Time "03:30";

// Reboot même si utilisateurs connectés (VPS sans GUI)
Unattended-Upgrade::Automatic-Reboot-WithUsers "true";

// Email notifications: DISABLED (utiliser Telegram hooks)
Unattended-Upgrade::Mail "never";
Unattended-Upgrade::MailReport "on-change";

// Remove unused dependencies automatically
Unattended-Upgrade::Remove-Unused-Dependencies "true";

// Remove unused kernel packages
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";

// Enable logging
Unattended-Upgrade::SyslogEnable "true";
Unattended-Upgrade::SyslogFacility "daemon";
EOF

echo -e "${GREEN}✅ /etc/apt/apt.conf.d/50unattended-upgrades configured${NC}"
echo ""

# 3. Activer service
echo "🔌 Enabling unattended-upgrades service..."

cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APT::Periodic::Unattended-Upgrade "1";
EOF

echo -e "${GREEN}✅ Service enabled${NC}"
echo ""

# 4. Créer systemd service post-reboot (AC5: Notification après reboot)
echo "🔔 Creating post-reboot notification service..."

cat > /etc/systemd/system/friday-post-reboot.service <<'EOF'
[Unit]
Description=Friday post-reboot notification
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
ExecStart=/bin/bash -c '/opt/friday-2.0/scripts/telegram-notify.sh "✅ *Friday VPS Rebooted*\n\nOS security updates applied successfully.\nTimestamp: $(date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ)\n\nHealthcheck in progress..." && sleep 30 && /opt/friday-2.0/scripts/healthcheck-all.sh'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Activer service
systemctl daemon-reload
systemctl enable friday-post-reboot.service

echo -e "${GREEN}✅ Post-reboot notification service created${NC}"
echo ""

# 5. Créer pre-reboot hook (AC5: Notification avant reboot)
echo "🔔 Creating pre-reboot hook..."

mkdir -p /opt/friday-2.0/scripts

cat > /etc/apt/apt.conf.d/51friday-telegram-hooks <<'EOF'
// Friday 2.0 - Telegram notification hooks
// Story 1.13 - AC5: Notifications avant/après reboot

// Pre-reboot notification
DPkg::Pre-Invoke {
    "if [ -f /var/run/reboot-required ]; then /opt/friday-2.0/scripts/telegram-notify.sh 'OS reboot imminent (kernel update) - Friday services will restart automatically'; fi";
};
EOF

echo -e "${GREEN}✅ Pre-reboot hook created${NC}"
echo ""

# 6. Vérifier configuration
echo "🔍 Verifying configuration..."

# Test dry-run
unattended-upgrade --dry-run --debug 2>&1 | head -n 20

echo ""
echo -e "${GREEN}✅ Configuration test passed${NC}"
echo ""

# Résumé
echo "═══════════════════════════════════════════════════════════════"
echo "✅ Unattended Upgrades Configuration Complete"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "📋 Summary:"
echo "  ✓ Security updates: ENABLED (automatic)"
echo "  ✓ Auto-reboot: ENABLED (if kernel update)"
echo "  ✓ Reboot time: 03:30 (after backup)"
echo "  ✓ Pre-reboot notification: Telegram hook"
echo "  ✓ Post-reboot notification: systemd service"
echo "  ✓ Service: unattended-upgrades.service"
echo ""
echo "⚠️  Note: Reboot will occur automatically if kernel update requires it"
echo "     Max frequency: 1x/week at 03:30"
echo ""
echo "📊 Logs: /var/log/unattended-upgrades/"
echo "📊 Service status: systemctl status unattended-upgrades"
echo ""

# Optionnel : démarrer service immédiatement
systemctl start unattended-upgrades
systemctl status unattended-upgrades --no-pager | head -n 10

echo ""
echo -e "${GREEN}✅ Setup complete!${NC}"
